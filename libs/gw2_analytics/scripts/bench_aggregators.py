"""Micro-benchmarks for the hot loop of gw2_analytics aggregators.

Run with ``uv run python libs/gw2_analytics/scripts/bench_aggregators.py``.

The script generates synthetic event streams of various sizes and
measures the ``aggregate()`` wall time for each aggregator. It is
intended to be run manually before/after optimization work; it is NOT
part of the CI test suite.
"""

from __future__ import annotations

import timeit
from collections import defaultdict
from collections.abc import Callable
from functools import partial
from typing import Any

from gw2_analytics.per_fight_timeline import PerFightTimelineAggregator
from gw2_analytics.per_player_timeline import PerPlayerTimelineAggregator
from gw2_analytics.player_boons import PlayerBoonsAggregator
from gw2_analytics.player_damage import PlayerDamageAggregator
from gw2_analytics.player_defense import PlayerDefenseAggregator
from gw2_analytics.player_heal import PlayerHealAggregator
from gw2_analytics.target_buff_removal import TargetBuffRemovalAggregator
from gw2_analytics.target_dps import TargetDpsAggregator
from gw2_analytics.target_healing import TargetHealingAggregator
from gw2_core import (
    BaseEvent,
    BoonApplyEvent,
    BuffRemovalEvent,
    DamageEvent,
    Event,
    HealingEvent,
)

# ---------------------------------------------------------------------------
# Synthetic event factories
# ---------------------------------------------------------------------------


def _damage_event(source: int, target: int, time_ms: int, damage: int) -> DamageEvent:
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=42,
        damage=damage,
    )


def _healing_event(source: int, target: int, time_ms: int, healing: int) -> HealingEvent:
    return HealingEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=43,
        healing=healing,
    )


def _strip_event(source: int, target: int, time_ms: int, value: int) -> BuffRemovalEvent:
    return BuffRemovalEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=44,
        buff_removal=value,
    )


# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------


def _bench(name: str, stmt: Callable[[], Any], *, number: int = 10) -> float:
    """Return the best of ``number`` runs of ``stmt`` in milliseconds."""
    total = timeit.timeit(stmt, number=number)
    best = total / number * 1000.0
    print(f"  {name}: {best:.3f} ms (best of {number})")
    return best


def _make_damage_events(count: int) -> list[DamageEvent]:
    return [
        _damage_event(source=i % 50, target=i % 30, time_ms=i * 100, damage=1000)
        for i in range(count)
    ]


def _make_healing_events(count: int) -> list[HealingEvent]:
    return [
        _healing_event(source=i % 50, target=i % 30, time_ms=i * 100, healing=500)
        for i in range(count)
    ]


def _make_strip_events(count: int) -> list[BuffRemovalEvent]:
    return [
        _strip_event(source=i % 50, target=i % 30, time_ms=i * 100, value=100)
        for i in range(count)
    ]


def _make_boon_events(count: int) -> list[BoonApplyEvent]:
    # Cycle through the 6 known boon IDs so the benchmark exercises
    # the fixed-column partition rather than flooding the fallback
    # ``other_boons_out`` bucket.
    known_boon_ids = [1122, 30328, 894, 743, 597, 1305]
    return [
        BoonApplyEvent(
            time_ms=i * 100,
            source_agent_id=i % 50,
            target_agent_id=i % 30,
            skill_id=known_boon_ids[i % len(known_boon_ids)],
            kind="apply",
            duration_ms=5000,
            stacks=1,
        )
        for i in range(count)
    ]


class _FakeAgent:
    """Minimal stand-in for an ORM agent used by PerPlayerTimelineAggregator."""

    def __init__(self, agent_id: int, account_name: str) -> None:
        self.agent_id = agent_id
        self.account_name = account_name
        self.is_player = True
        self.name = f"Player{agent_id}"


def _make_agents() -> list[_FakeAgent]:
    return [_FakeAgent(agent_id=i, account_name=f":acc.{i}") for i in range(50)]


# ---------------------------------------------------------------------------
# Naive (pre-optimization) implementations for A/B comparison
# ---------------------------------------------------------------------------


def _naive_target_dps(events: list[DamageEvent], _duration_s: float) -> None:
    total_by_target: dict[int, int] = defaultdict(int)
    count_by_target: dict[int, int] = defaultdict(int)
    for e in events:
        total_by_target[e.target_agent_id] += e.damage
        count_by_target[e.target_agent_id] += 1
    rows = []
    for target in set(total_by_target) | set(count_by_target):
        rows.append((target, total_by_target[target], count_by_target[target]))


def _naive_player_damage(events: list[DamageEvent], _duration_s: float) -> None:
    total_by_source: dict[int, int] = defaultdict(int)
    count_by_source: dict[int, int] = defaultdict(int)
    for e in events:
        total_by_source[e.source_agent_id] += e.damage
        count_by_source[e.source_agent_id] += 1
    rows = []
    for source in set(total_by_source) | set(count_by_source):
        rows.append((source, total_by_source[source], count_by_source[source]))


def _naive_per_fight_timeline(events: list[Event], window_s: int) -> None:
    window_ms = window_s * 1000
    damage_by_bucket: dict[int, int] = defaultdict(int)
    healing_by_bucket: dict[int, int] = defaultdict(int)
    strip_by_bucket: dict[int, int] = defaultdict(int)
    last_bucket_index = -1
    for e in events:
        bucket_index = e.time_ms // window_ms
        last_bucket_index = max(last_bucket_index, bucket_index)
        if isinstance(e, DamageEvent):
            damage_by_bucket[bucket_index] += e.damage
        elif isinstance(e, HealingEvent):
            healing_by_bucket[bucket_index] += e.healing
        elif isinstance(e, BuffRemovalEvent):
            strip_by_bucket[bucket_index] += e.buff_removal
    for idx in range(last_bucket_index + 1):
        _ = (
            damage_by_bucket.get(idx, 0),
            healing_by_bucket.get(idx, 0),
            strip_by_bucket.get(idx, 0),
        )


# ---------------------------------------------------------------------------
# Benchmark suites
# ---------------------------------------------------------------------------


def _benchmark_target_aggregators(event_counts: list[int]) -> None:
    print("\n=== Target aggregators (damage / healing / buff removal) ===")
    for count in event_counts:
        print(f"\n-- {count} events --")
        damage_events = _make_damage_events(count)
        healing_events = _make_healing_events(count)
        strip_events = _make_strip_events(count)

        _bench(
            "TargetDpsAggregator (optimized)",
            partial(TargetDpsAggregator().aggregate, damage_events, duration_s=120.0),
        )
        _bench(
            "TargetDpsAggregator (naive)",
            partial(_naive_target_dps, damage_events, 120.0),
        )
        _bench(
            "TargetHealingAggregator",
            partial(TargetHealingAggregator().aggregate, healing_events, duration_s=120.0),
        )
        _bench(
            "TargetBuffRemovalAggregator",
            partial(TargetBuffRemovalAggregator().aggregate, strip_events, duration_s=120.0),
        )


def _benchmark_player_aggregators(event_counts: list[int]) -> None:
    print("\n=== Player aggregators (damage / heal / defense / boons) ===")
    for count in event_counts:
        print(f"\n-- {count} events --")
        damage_events = _make_damage_events(count)
        healing_events = _make_healing_events(count)
        boon_events = _make_boon_events(count)

        _bench(
            "PlayerDamageAggregator (optimized)",
            partial(PlayerDamageAggregator().aggregate, damage_events, duration_s=120.0),
        )
        _bench(
            "PlayerDamageAggregator (naive)",
            partial(_naive_player_damage, damage_events, 120.0),
        )
        _bench(
            "PlayerHealAggregator",
            partial(PlayerHealAggregator().aggregate, healing_events, duration_s=120.0),
        )
        _bench(
            "PlayerDefenseAggregator",
            partial(
                PlayerDefenseAggregator().aggregate,
                damage_events,
                [],
                [],
                dodge_events=[],
                block_events=[],
                interrupt_events=[],
            ),
        )
        _bench(
            "PlayerBoonsAggregator",
            partial(PlayerBoonsAggregator().aggregate, boon_events, duration_s=120.0),
        )


def _benchmark_timeline_aggregators(event_counts: list[int]) -> None:
    print("\n=== Timeline aggregators ===")
    agents = _make_agents()
    for count in event_counts:
        print(f"\n-- {count} events --")
        events: list[BaseEvent] = list(_make_damage_events(count))
        events.extend(_make_healing_events(count))
        events.extend(_make_strip_events(count))

        _bench(
            "PerFightTimelineAggregator (optimized)",
            partial(PerFightTimelineAggregator().aggregate, events, duration_s=120.0, window_s=5),
        )
        _bench(
            "PerFightTimelineAggregator (naive)",
            partial(_naive_per_fight_timeline, events, 5),
        )
        _bench(
            "PerPlayerTimelineAggregator",
            partial(PerPlayerTimelineAggregator().aggregate, events, agents, window_s=5),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run all aggregator micro-benchmarks."""
    event_counts = [1_000, 10_000, 100_000]
    _benchmark_target_aggregators(event_counts)
    _benchmark_player_aggregators(event_counts)
    _benchmark_timeline_aggregators(event_counts)


if __name__ == "__main__":
    main()
