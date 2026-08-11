"""Per-player down-contribution DPS + kill attribution.

Phase C v0.11.0: live down-contribution DPS and kill attribution
in the Combat readout Damage table (shipped v0.11.0; kills
wired via Phase 6 v2 parser since v0.12.1).

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
- ``DeathEvent.killed_by_agent_id`` is an Optional field
  (Phase 6 v2 parser yields the actual value since v0.12.1).
- Legacy (pre-v0.12.x) streams: ``killed_by_agent_id`` is
  ``None`` → kills stay at ``0`` for all players.
- v0.12.1+: each ``DeathEvent`` with a non-``None``
  ``killed_by_agent_id`` increments that agent's kill count.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._boon_ids import BOON_SKILL_IDS
from gw2_analytics.damage_predicates import landed_hit
from gw2_core import (
    CCEvent,
    CombatOutcomeEvent,
    DamageEvent,
    DeathEvent,
    DownEvent,
    HealthUpdateEvent,
    UpEvent,
)


class DownContributionRow(BaseModel):
    """One player's down-contribution DPS + kill count.

    Model is frozen (immutable) and schema is forward-compat
    (``extra="forbid"``). Both fields default to ``0`` so the
    wire shape is stable for legacy (pre-v0.12.x) streams where
    kills are not yet attributable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent_id: int = Field(..., ge=0)
    down_contribution_damage: int = Field(default=0, ge=0)
    down_contribution_dps: float = Field(default=0.0, ge=0.0)
    against_downed_damage: int = Field(default=0, ge=0)
    against_downed_count: int = Field(default=0, ge=0)
    downs: int = Field(default=0, ge=0)
    kills: int = Field(default=0, ge=0)
    down_contribution_cc_count: int = Field(default=0, ge=0)
    down_contribution_cc_duration_ms: int = Field(default=0, ge=0)


@dataclass(slots=True)
class _DownAccumulator:
    """Mutable accumulator for one source agent's down-contribution stats."""

    damage_to_down: int = 0
    against_downed_damage: int = 0
    against_downed_count: int = 0
    downs: int = 0
    kills: int = 0
    down_contribution_cc_count: int = 0
    down_contribution_cc_duration_ms: int = 0


class DownContributionAggregator:
    """Stateless aggregator: damage/down/death events -> per-player down-contribution + kills.

    Instantiate once and reuse — the class holds no state.
    """

    def aggregate(  # noqa: PLR0912
        self,
        damage_events: list[DamageEvent],
        down_events: list[DownEvent],
        death_events: list[DeathEvent],
        duration_s: float,
        *,
        health_events: list[HealthUpdateEvent] | None = None,
        up_events: list[UpEvent] | None = None,
        outcome_events: list[CombatOutcomeEvent] | None = None,
        cc_events: list[CCEvent] | None = None,
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
        if not damage_events and not down_events and not death_events and not outcome_events:
            return []

        stats: dict[int, _DownAccumulator] = defaultdict(_DownAccumulator)
        if health_events:
            windows = self._pre_down_windows(
                health_events, down_events, up_events or [], death_events
            )
            for damage in damage_events:
                acc = stats[damage.source_agent_id]
                # Elite Insights counts an against-downed hit when it
                # *landed*, not when it carried damage: a hit fully absorbed
                # or wholly converted to barrier still counts. The damage
                # sums are unaffected, which is why only the counters drifted.
                if damage.against_downed and landed_hit(damage):
                    acc.against_downed_count += 1
                    acc.against_downed_damage += damage.damage
                if damage.damage > 0 and self._in_windows(
                    damage.target_agent_id, damage.time_ms, windows
                ):
                    acc.damage_to_down += damage.damage
            for crowd_control in cc_events or []:
                if self._in_windows(crowd_control.target_agent_id, crowd_control.time_ms, windows):
                    acc = stats[crowd_control.source_agent_id]
                    acc.down_contribution_cc_count += 1
                    acc.down_contribution_cc_duration_ms += crowd_control.cc_value
        else:
            self._accumulate_legacy_against_downed(
                damage_events,
                down_events,
                death_events,
                up_events or [],
                stats,
            )

        for outcome in outcome_events or []:
            acc = stats[outcome.source_agent_id]
            if outcome.outcome == "downed":
                acc.downs += 1
            else:
                acc.kills += 1
        for death in death_events:
            if death.killed_by_agent_id is not None:
                stats[death.killed_by_agent_id].kills += 1

        return self._rows(stats, duration_s)

    @staticmethod
    def _pre_down_windows(
        health_events: list[HealthUpdateEvent],
        down_events: list[DownEvent],
        up_events: list[UpEvent],
        death_events: list[DeathEvent],
    ) -> dict[int, list[tuple[int, int]]]:
        health_by_target: dict[int, list[HealthUpdateEvent]] = defaultdict(list)
        for event in health_events:
            health_by_target[event.source_agent_id].append(event)
        # Elite Insights builds a downed *segment* per down event and drops
        # any whose start is not strictly before its end, so an actor that
        # dies on the same millisecond it goes down has no downed segment at
        # all -- and therefore earns nobody a down contribution. The rule
        # reads like an implementation detail and behaves like one, but it
        # is load-bearing: it is the whole gap on ``20260129-110256``.
        instant_deaths: dict[int, set[int]] = defaultdict(set)
        for death in death_events:
            instant_deaths[death.source_agent_id].add(death.time_ms)
        for up in up_events:
            instant_deaths[up.source_agent_id].discard(up.time_ms)
        windows: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for down in down_events:
            if down.time_ms in instant_deaths.get(down.source_agent_id, ()):
                continue
            start: int | None = None
            last_up = max(
                (
                    up.time_ms
                    for up in up_events
                    if up.source_agent_id == down.source_agent_id and up.time_ms < down.time_ms
                ),
                default=-1,
            )
            saw_above_90 = False
            for health in health_by_target.get(down.source_agent_id, []):
                if health.time_ms <= last_up:
                    continue
                if health.time_ms >= down.time_ms:
                    break
                if health.health_percent > 90.0:
                    start = None
                    saw_above_90 = True
                elif start is None:
                    start = health.time_ms
            # Elite Insights' IsDownedBeforeNext90 treats a hit delivered before
            # the target's first HealthUpdate as hitting at unknown HP (<=90%),
            # so the pre-down window opens right after the last rally even when
            # no HealthUpdate has been seen yet. Without this, parity with EI is
            # off by the damage dealt before the first recorded HealthUpdate.
            if not saw_above_90:
                start = last_up + 1
            if start is not None:
                windows[down.source_agent_id].append((start, down.time_ms))
        return windows

    @staticmethod
    def _in_windows(
        target_agent_id: int,
        time_ms: int,
        windows: dict[int, list[tuple[int, int]]],
    ) -> bool:
        return any(start <= time_ms < end for start, end in windows.get(target_agent_id, []))

    @staticmethod
    def _accumulate_legacy_against_downed(
        damage_events: list[DamageEvent],
        down_events: list[DownEvent],
        death_events: list[DeathEvent],
        up_events: list[UpEvent],
        stats: dict[int, _DownAccumulator],
    ) -> None:

        # Chronological processing: build a unified timeline of all
        # 3 event types, sorted by (time_ms, type_priority).
        # Combat impacts resolve before state transitions on the same tick,
        # matching Elite Insights' against-downed attribution.
        timeline: list[tuple[int, int, DownEvent | DeathEvent | UpEvent | DamageEvent]] = []
        for de in down_events:
            timeline.append((de.time_ms, 1, de))
        for death in death_events:
            timeline.append((death.time_ms, 2, death))
        for up in up_events:
            timeline.append((up.time_ms, 2, up))
        for dmg in damage_events:
            timeline.append((dmg.time_ms, 0, dmg))
        timeline.sort(key=lambda x: (x[0], x[1]))

        # Track which agent_ids are currently in the downed state.
        downed_targets: set[int] = set()
        for _time_ms, _prio, event in timeline:
            if isinstance(event, DownEvent):
                downed_targets.add(event.source_agent_id)
            elif isinstance(event, (DeathEvent, UpEvent)):
                downed_targets.discard(event.source_agent_id)
            elif isinstance(event, DamageEvent) and event.target_agent_id in downed_targets:
                if event.skill_id in BOON_SKILL_IDS:
                    continue
                stats[event.source_agent_id].damage_to_down += event.damage

    @staticmethod
    def _rows(stats: dict[int, _DownAccumulator], duration_s: float) -> list[DownContributionRow]:
        dps_factor = 1.0 / duration_s if duration_s > 0 else 0.0
        rows = [
            DownContributionRow(
                source_agent_id=source,
                down_contribution_damage=acc.damage_to_down,
                down_contribution_dps=acc.damage_to_down * dps_factor,
                against_downed_damage=acc.against_downed_damage,
                against_downed_count=acc.against_downed_count,
                downs=acc.downs,
                kills=acc.kills,
                down_contribution_cc_count=acc.down_contribution_cc_count,
                down_contribution_cc_duration_ms=acc.down_contribution_cc_duration_ms,
            )
            for source, acc in stats.items()
        ]
        # Sort: highest down_contribution_dps first; ties by source_agent_id ASC.
        rows.sort(key=lambda r: (-r.down_contribution_dps, r.source_agent_id))
        return rows


__all__ = ["DownContributionAggregator", "DownContributionRow"]
