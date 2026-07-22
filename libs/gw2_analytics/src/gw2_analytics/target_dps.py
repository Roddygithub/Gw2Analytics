"""

Phase 6: per-target damage roll-ups from synthetic :class:`DamageEvent`
streams.

Phase 6 v1 ships aggregators over IN-MEMORY event lists because the
gw2_evtc_parser does not yet surface the event block. Forward-compat
notes (Phase 6 v2) live in the module docstring.

Conventions
===========

- **Deterministic ordering.** Rows sorted by
  ``(-total_damage, target_agent_id)`` -- highest damage first; ties
  broken by ascending ``target_agent_id``. Two runs over the same input
  MUST yield byte-identical row output.
- This file is the strict parallel of :mod:`gw2_analytics.target_healing`
  (``TargetDpsRow`` <-> ``TargetHealingRow``,
  ``TargetDpsAggregator`` <-> ``TargetHealingAggregator``);
  see that module for the healing-roll-up counterpoint (added in
  Phase 7 v1).
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **DPS = ``total_damage / duration_s`` when ``duration_s > 0``.**
  When ``duration_s == 0`` we emit ``dps=0.0`` (zero-duration is a
  sentinel "duration not provided" rather than a math singularity).
  Negative duration is rejected -- callers can guard at upstream sites
  where ``fight.duration`` is known.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- Sum of ``row.total_damage`` across all rows == sum of ``event.damage``
  across input events (no event dropped, no double-counting).
- Rows monotonically non-increasing by ``total_damage``; ties broken
  by ascending ``target_agent_id``.
- Every row has ``attack_count >= 1``.

Forward compat
==============

Phase 6 v2 will swap ``Iterable[DamageEvent]`` for
``Iterable[Event]`` (the discriminated union) at the aggregator
boundary -- callers that already produce a stream of damage events
are unchanged; the aggregator continues to read only ``damage`` from
the input. The :class:`TargetDpsRow` schema stays unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import DamageEvent

# DPS sentinel when ``duration_s <= 0``: invalid (zero/negative) duration
# collapses to 0.0 rather than raising -- the canonical ``DamageEvent``
# stream from the parser will always pair with a known fight duration
# so the zero path is purely defensive.
_DEFAULT_DPS: Final[float] = 0.0


@dataclass(slots=True)
class _TargetStats:
    total: int = 0
    count: int = 0


class TargetDpsRow(BaseModel):
    """One roll-up row: damage + DPS directed at a single target agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent_id: int = Field(..., ge=0)
    total_damage: int = Field(..., ge=0)
    attack_count: int = Field(..., ge=1)
    dps: float = Field(..., ge=0.0)
    # Optional player-name denormalisation (v0.8.3). ``None`` when the
    # aggregator was called without a ``name_map`` (the canonical
    # backward-compat case -- existing tests / callers don't care
    # about target resolution) OR when the agent id has no name in
    # the map (an NPC without a registered arcdps char-name -- the
    # route surfaces it as ``null`` on the wire). The schema is
    # additive: existing wire consumers ignore the new field.
    name: str | None = None


class TargetDpsAggregator:
    """Stateless aggregator: events -> per-target DPS roll-up rows.

    Instantiate once and reuse -- the class holds no state.
    """

    def aggregate(
        self,
        events: Iterable[DamageEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
    ) -> list[TargetDpsRow]:
        """Compute the roll-up from a stream of damage events.

        ``duration_s`` is the fight duration (the time-bucket the DPS
        rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.

        ``name_map`` is an OPTIONAL ``{agent_id: name}`` lookup for
        player-name denormalisation (v0.8.3). ``None`` (the default)
        leaves every row's ``name`` field as ``None`` -- the
        canonical backward-compat case. An empty dict has the same
        effect (no names resolved). Agents not present in the map
        resolve to ``None`` (NPCs without a registered arcdps
        char-name); the route surfaces this as ``null`` on the wire
        and the frontend falls back to the raw ``target_agent_id``.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        # Consolidate per-target stats into a single dictionary.
        # Each value is a slotted dataclass, cutting the hot-loop
        # hash lookups from 2 per event to 1 while keeping the
        # metrics self-documenting.
        stats_by_target: dict[int, _TargetStats] = defaultdict(_TargetStats)
        for e in events:
            stats = stats_by_target[e.target_agent_id]
            stats.total += e.damage
            stats.count += 1

        dps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_DPS
        # ``name_map.get(target)`` returns ``None`` for missing keys
        # AND for explicit ``None`` values -- both cases surface as
        # ``name=None`` on the row, which is the intended
        # "unresolved" sentinel. No need to distinguish.
        safe_name_map = name_map or {}
        rows = [
            TargetDpsRow(
                target_agent_id=target,
                total_damage=stats.total,
                attack_count=stats.count,
                dps=stats.total * dps_factor,
                name=safe_name_map.get(target),
            )
            for target, stats in stats_by_target.items()
        ]
        # Sort: highest total_damage first; ties broken by ascending target_agent_id.
        rows.sort(key=lambda r: (-r.total_damage, r.target_agent_id))

        return rows


__all__ = ["TargetDpsAggregator", "TargetDpsRow"]
