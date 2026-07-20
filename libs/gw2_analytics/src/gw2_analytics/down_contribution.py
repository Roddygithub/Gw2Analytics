"""Per-player down-contribution DPS + kill attribution.

Phase C v0.11.0: replaces the ``down_contribution_dps=0.0`` and
``kills=0`` SCAFFOLD stubs in the Combat readout Damage table.

Down-contribution DPS
=====================
Tracks which agents are currently in the downed state (via
``DownEvent`` + ``DeathEvent``) and attributes each
``DamageEvent`` to its source when ``target_agent_id`` is a
downed player.

Downed-state tracking without a ``ChangeUp`` (rally) event:
- ``DownEvent``: the source agent enters the downed state.
  If the agent is already in the downed set, a rally-and-re-down
  occurred; damage continues to accumulate correctly (we don't
  know the precise rally moment without the ChangeUp event).
- ``DeathEvent``: the source agent leaves the downed set
  (dies permanently). Subsequent damage to this target is no
  longer down-contribution.
- The lack of a ``ChangeUp`` event means damage dealt to a
  player *after* they rally (but before their next down/death)
  is *conservatively over-counted* as down contribution. This
  is acceptable for Phase C and strictly better than ``0.0``.

Kill attribution
================
- ``DeathEvent.killed_by_agent_id`` is a ``Forward-compat``
  Optional field (Phase 6 v2 parser yields the actual value).
- Pre-Phase-6-v2 streams: ``killed_by_agent_id`` is ``None``
  → kills stay at ``0`` for all players.
- Post-Phase-6-v2: each ``DeathEvent`` with a non-``None``
  ``killed_by_agent_id`` increments that agent's kill count.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._boon_ids import BOON_SKILL_IDS
from gw2_core import DamageEvent, DeathEvent, DownEvent


class DownContributionRow(BaseModel):
    """One player's down-contribution DPS + kill count.

    Model is frozen (immutable) and schema is forward-compat
    (``extra="forbid"``). Both fields default to ``0`` so the
    wire shape is stable for pre-Phase-6-v2 streams where kills
    are not yet attributable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent_id: int = Field(..., ge=0)
    down_contribution_dps: float = Field(default=0.0, ge=0.0)
    kills: int = Field(default=0, ge=0)


@dataclass(slots=True)
class _DownAccumulator:
    """Mutable accumulator for one source agent's down-contribution stats."""

    damage_to_down: int = 0
    kills: int = 0


class DownContributionAggregator:
    """Stateless aggregator: damage/down/death events -> per-player down-contribution + kills.

    Instantiate once and reuse — the class holds no state.
    """

    def aggregate(
        self,
        damage_events: list[DamageEvent],
        down_events: list[DownEvent],
        death_events: list[DeathEvent],
        duration_s: float,
    ) -> list[DownContributionRow]:
        """Compute per-player down-contribution DPS + kill attribution.

        **Chronological processing**: all events are interleaved by
        ``time_ms`` so that state changes (``DownEvent`` adds agent
        to downed set; ``DeathEvent`` removes agent from downed set
        + attributes kill) and damage checks occur in correct temporal
        order. This avoids the batch-order bug where a DeathEvent
        processed ahead of a DamageEvent would incorrectly clear the
        downed state before damage attribution.

        ``duration_s`` is the fight duration used to compute the
        per-second rate. When ``duration_s <= 0``, ``down_contribution_dps``
        is ``0.0`` for all rows (defensive guard).

        Returns rows sorted by ``-down_contribution_dps`` (highest
        first), ties broken by ascending ``source_agent_id``.

        Empty input yields ``[]``.
        """
        if not damage_events and not down_events and not death_events:
            return []

        # Chronological processing: build a unified timeline of all
        # 3 event types, sorted by (time_ms, type_priority).
        # type_priority ensures deterministic ordering when events
        # share the same time_ms: 0=DownEvent, 1=DeathEvent, 2=DamageEvent.
        # DownEvents come first so the downed state is set before
        # DamageEvents at the same timestamp check it.
        timeline: list[tuple[int, int, DownEvent | DeathEvent | DamageEvent]] = []
        for de in down_events:
            timeline.append((de.time_ms, 0, de))
        for death in death_events:
            timeline.append((death.time_ms, 1, death))
        for dmg in damage_events:
            timeline.append((dmg.time_ms, 2, dmg))
        timeline.sort(key=lambda x: (x[0], x[1]))

        # Track which agent_ids are currently in the downed state.
        downed_targets: set[int] = set()
        stats: dict[int, _DownAccumulator] = defaultdict(_DownAccumulator)

        for _time_ms, _prio, event in timeline:
            if isinstance(event, DownEvent):
                downed_targets.add(event.source_agent_id)
            elif isinstance(event, DeathEvent):
                downed_targets.discard(event.source_agent_id)
                if event.killed_by_agent_id is not None:
                    stats[event.killed_by_agent_id].kills += 1
            elif isinstance(event, DamageEvent) and event.target_agent_id in downed_targets:
                if event.skill_id in BOON_SKILL_IDS:
                    continue
                stats[event.source_agent_id].damage_to_down += event.damage

        dps_factor = 1.0 / duration_s if duration_s > 0 else 0.0
        rows = [
            DownContributionRow(
                source_agent_id=source,
                down_contribution_dps=acc.damage_to_down * dps_factor,
                kills=acc.kills,
            )
            for source, acc in stats.items()
        ]
        # Sort: highest down_contribution_dps first; ties by source_agent_id ASC.
        rows.sort(key=lambda r: (-r.down_contribution_dps, r.source_agent_id))
        return rows


__all__ = ["DownContributionAggregator", "DownContributionRow"]
