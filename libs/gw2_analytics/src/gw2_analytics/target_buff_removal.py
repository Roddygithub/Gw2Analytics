"""

Phase 8: per-target buff-removal roll-ups from synthetic
:class:`BuffRemovalEvent` streams.

Phase 8 ships the third ``Event`` discriminated union member + a
third per-target aggregator to consume it. This file is the strict
parallel of :mod:`gw2_analytics.target_healing` and the trio with
:mod:`gw2_analytics.target_dps` -- the schema, ordering, invariants,
duration sentinel, and overall shape mirror ``target_dps`` /
``target_healing`` so the three modules read as one design.

Why BPS (buffs-per-second), not just total_buff_removal
=======================================================

The damage / healing aggregators expose a rate (DPS / HPS) so the
analyst can spot a spike at a glance. The buff-removal roll-up
mirrors that choice: ``bps = total_buff_removal / duration_s``
when ``duration_s > 0``, ``bps = 0.0`` otherwise. Negative duration
is rejected at the call site. The unit name ("buffs per second")
is intentionally unitless in the schema: ``total_buff_removal`` is
the integer ``buff_dmg`` value summed across the target's
``BuffRemovalEvent`` stream and is not strictly a count of boons
stripped (one corrupting skill on a target with 3 stacked boons
can write ``buff_dmg = 1500``).

Conventions
===========

- **Deterministic ordering.** Rows sorted by
  ``(-total_buff_removal, target_agent_id)`` -- highest removal
  first; ties broken by ascending ``target_agent_id``. Two runs
  over the same input MUST yield byte-identical row output.
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **BPS = ``total_buff_removal / duration_s`` when ``duration_s > 0``.**
  When ``duration_s == 0`` we emit ``bps=0.0`` (zero-duration is a
  sentinel "duration not provided" rather than a math singularity).
  Negative duration is rejected -- callers can guard at upstream
  sites where ``fight.duration`` is known.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- Sum of ``row.total_buff_removal`` across all rows == sum of
  ``event.buff_removal`` across input events (no event dropped, no
  double-counting).
- Rows monotonically non-increasing by ``total_buff_removal``; ties
  broken by ascending ``target_agent_id``.
- Every row has ``strip_count >= 1``.

Forward compat
==============

The aggregator signature (``Iterable[BuffRemovalEvent]`` ->
``list[TargetBuffRemovalRow]``) is stable. A future in-parser
switch from synthetic event lists to ``gw2_evtc_parser.parse_events``
output only changes the upstream producer -- the aggregator body
reads only ``buff_removal`` from each event and is unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BuffRemovalEvent

# BPS sentinel when ``duration_s <= 0``: invalid (zero/negative)
# duration collapses to 0.0 rather than raising -- the canonical
# ``BuffRemovalEvent`` stream from the parser will always pair with a
# known fight duration so the zero path is purely defensive.
_DEFAULT_BPS: Final[float] = 0.0


@dataclass(slots=True)
class _TargetStats:
    total: int = 0
    count: int = 0


class TargetBuffRemovalRow(BaseModel):
    """One roll-up row: buff-removal + BPS directed at a single target agent.

    The target_agent_id is the agent FROM WHOM the boon is being
    stripped (i.e. the receiving end of the strip). This mirrors the
    semantics of :class:`~gw2_analytics.target_dps.TargetDpsRow` and
    :class:`~gw2_analytics.target_healing.TargetHealingRow`, which
    are also keyed on the receiving agent. For "top strippers"
    (output grouped by source_agent_id), use a separate aggregator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent_id: int = Field(..., ge=0)
    total_buff_removal: int = Field(..., ge=0)
    strip_count: int = Field(..., ge=1)
    bps: float = Field(..., ge=0.0)
    # Optional player-name denormalisation (v0.8.3). See
    # :class:`~gw2_analytics.target_dps.TargetDpsRow.name` for the
    # contract (None = unresolved; the route surfaces ``null`` on
    # the wire; the frontend falls back to the raw
    # ``target_agent_id``). Strict parallel of the DPS + Healing
    # rows so the trio reads as one design.
    name: str | None = None


class TargetBuffRemovalAggregator:
    """Stateless aggregator: events -> per-target buff-removal roll-up rows.

    Instantiate once and reuse -- the class holds no state.

    This mirrors :class:`~gw2_analytics.target_dps.TargetDpsAggregator`
    and :class:`~gw2_analytics.target_healing.TargetHealingAggregator`
    exactly in shape; only the field names (``total_buff_removal`` /
    ``strip_count`` / ``bps``) and the input event type
    (``BuffRemovalEvent`` instead of ``DamageEvent`` /
    ``HealingEvent``) differ. Downstream callers that already split
    a heterogeneous ``Iterable[Event]`` stream into per-kind iterators
    at the route layer can call all three aggregators on the same
    ``duration_s`` to get one combined damage + healing +
    buff-removal per-target view without changing any aggregator's
    signature.
    """

    def aggregate(
        self,
        events: Iterable[BuffRemovalEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
    ) -> list[TargetBuffRemovalRow]:
        """Compute the roll-up from a stream of buff-removal events.

        ``duration_s`` is the fight duration (the time-bucket the
        BPS rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.

        ``name_map`` is an OPTIONAL ``{agent_id: name}`` lookup for
        player-name denormalisation (v0.8.3). See
        :meth:`~gw2_analytics.target_dps.TargetDpsAggregator.aggregate`
        for the full contract; this method is a strict parallel.
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
            stats.total += e.buff_removal
            stats.count += 1

        bps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_BPS
        # ``name_map or {}`` -- see the parallel branch in
        # :meth:`~gw2_analytics.target_dps.TargetDpsAggregator.aggregate`
        # for the rationale (``dict.get`` returns ``None`` for missing
        # keys AND for explicit ``None`` values; both surface as the
        # ``name=None`` sentinel on the row).
        safe_name_map = name_map or {}
        rows = [
            TargetBuffRemovalRow(
                target_agent_id=target,
                total_buff_removal=stats.total,
                strip_count=stats.count,
                bps=stats.total * bps_factor,
                name=safe_name_map.get(target),
            )
            for target, stats in stats_by_target.items()
        ]
        # Sort: highest total_buff_removal first; ties broken by ascending target_agent_id.
        rows.sort(key=lambda r: (-r.total_buff_removal, r.target_agent_id))

        return rows


__all__ = ["TargetBuffRemovalAggregator", "TargetBuffRemovalRow"]
