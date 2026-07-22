"""Per-target, squad, and skill aggregation glue for /fights endpoints.

Wraps the library-side aggregators (Target{Dps,Healing,BuffRemoval}Agg,
SquadRollupAggregator, SkillUsageAggregator) with the 3-event-type fanout
so route handlers stay thin. Extracted from the pre-A2 god module
``aggregators.py`` (plan 021).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Final, cast

from gw2_analytics.condi_power_split import KNOWN_CONDI_NAMES
from gw2_analytics.player_damage import DpsSplitGetter
from gw2_analytics.player_heal import HealBarrierGetter
from gw2_analytics.skill_usage import SkillUsageAggregator, SkillUsageRow
from gw2_analytics.squad_rollup import SquadRollupAggregator, SquadRollupRow
from gw2_analytics.target_buff_removal import (
    TargetBuffRemovalAggregator,
    TargetBuffRemovalRow,
)
from gw2_analytics.target_dps import TargetDpsAggregator, TargetDpsRow
from gw2_analytics.target_healing import TargetHealingAggregator, TargetHealingRow
from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent


def _split_three_event_streams(
    events: Iterable[Event],
) -> tuple[list[DamageEvent], list[HealingEvent], list[BuffRemovalEvent]]:
    damage_events: list[DamageEvent] = []
    healing_events: list[HealingEvent] = []
    buff_removal_events: list[BuffRemovalEvent] = []

    append_damage = damage_events.append
    append_healing = healing_events.append
    append_buff_removal = buff_removal_events.append

    for event in events:
        if isinstance(event, DamageEvent):
            append_damage(event)
        elif isinstance(event, HealingEvent):
            append_healing(event)
        elif isinstance(event, BuffRemovalEvent):
            append_buff_removal(event)

    return damage_events, healing_events, buff_removal_events


def _aggregate_per_target_rollup(
    events: list[Event],
    agent_id_to_name_map: dict[int, str | None],
    duration_s: float,
    event_cls: type[Event],
) -> Sequence[TargetDpsRow | TargetHealingRow | TargetBuffRemovalRow]:
    assert all(isinstance(e, event_cls) for e in events), (
        f"_aggregate_per_target_rollup: caller must pre-filter events to "
        f"{event_cls.__name__}; got mixed event stream"
    )
    if event_cls is DamageEvent:
        return TargetDpsAggregator().aggregate(
            cast(Iterable[DamageEvent], events),
            duration_s,
            name_map=agent_id_to_name_map,
        )
    if event_cls is HealingEvent:
        return TargetHealingAggregator().aggregate(
            cast(Iterable[HealingEvent], events),
            duration_s,
            name_map=agent_id_to_name_map,
        )
    if event_cls is BuffRemovalEvent:
        return TargetBuffRemovalAggregator().aggregate(
            cast(Iterable[BuffRemovalEvent], events),
            duration_s,
            name_map=agent_id_to_name_map,
        )
    raise ValueError(
        f"_aggregate_per_target_rollup: unknown event_cls {event_cls!r}; "
        f"expected DamageEvent | HealingEvent | BuffRemovalEvent"
    )


def aggregate_squad_rollup(
    events: list[Event],
    agent_id_to_subgroup_map: dict[int, str],
    duration_s: float,
) -> list[SquadRollupRow]:
    damage_events, healing_events, buff_removal_events = _split_three_event_streams(events)
    return SquadRollupAggregator().aggregate(
        damage_events,
        healing_events,
        buff_removal_events,
        agent_id_to_subgroup_map,
        duration_s,
    )


def aggregate_skill_usage(
    events: list[Event],
    skill_id_to_name_map: dict[int, str],
) -> list[SkillUsageRow]:
    damage_events, healing_events, buff_removal_events = _split_three_event_streams(events)
    return SkillUsageAggregator().aggregate(
        damage_events,
        healing_events,
        buff_removal_events,
        skill_id_to_name_map,
    )


_BUILD_DATE_GATE: Final[str] = "20240501"


def make_dps_split_getter(
    build_date: str,
    skill_name_getter: Callable[[int], str | None],
) -> DpsSplitGetter:
    is_new = build_date.isdigit() and int(build_date) >= int(_BUILD_DATE_GATE)
    cache: dict[int, str | None] = {}
    known = KNOWN_CONDI_NAMES

    if is_new:

        def _new_splitter(e: DamageEvent) -> tuple[int, int]:
            condi = min(e.damage, max(0, e.buff_dmg))
            return (condi, e.damage - condi)

        return _new_splitter

    def _old_splitter(e: DamageEvent) -> tuple[int, int]:
        sid = e.skill_id
        if sid not in cache:
            cache[sid] = skill_name_getter(sid)
        if cache[sid] in known:
            return (e.damage, 0)
        return (0, e.damage)

    return _old_splitter


def make_barrier_portion_getter() -> HealBarrierGetter:
    return lambda e: e.barrier


__all__ = [
    "_BUILD_DATE_GATE",
    "_aggregate_per_target_rollup",
    "aggregate_skill_usage",
    "aggregate_squad_rollup",
    "make_barrier_portion_getter",
    "make_dps_split_getter",
]
