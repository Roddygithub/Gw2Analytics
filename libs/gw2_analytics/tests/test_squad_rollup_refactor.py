"""Plan 085 tests for the extracted ``_accumulate_subgroup_totals`` helper.

The 3 formerly byte-identical per-stream loops in
:class:`SquadRollupAggregator.aggregate` were factored into one shared
helper. These tests exercise the helper directly (empty input, single
event with the empty-subgroup fallback, map-driven subgroup routing) and
confirm the refactored aggregator output matches the hand-computed
expectation on a mixed multi-stream input. The pre-existing
``test_squad_rollup.py`` remains the full aggregator regression contract.
"""

from __future__ import annotations

from collections import defaultdict

from gw2_analytics.squad_rollup import (
    SquadRollupAggregator,
    _accumulate_subgroup_totals,
)
from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent


def _damage(src: int, value: int, dst: int = 99, time_ms: int = 0) -> DamageEvent:
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=1,
        damage=value,
    )


class TestAccumulateSubgroupTotals:
    def test_empty_stream_returns_zero(self) -> None:
        total: dict[str, int] = defaultdict(int)
        hits: dict[str, int] = defaultdict(int)
        grand = _accumulate_subgroup_totals([], {}, "damage", total, hits)
        assert grand == 0
        assert total == {}
        assert hits == {}

    def test_single_event_falls_back_to_empty_subgroup(self) -> None:
        # Source agent 42 is NOT in the (empty) map -> empty-string bucket.
        total: dict[str, int] = defaultdict(int)
        hits: dict[str, int] = defaultdict(int)
        grand = _accumulate_subgroup_totals([_damage(src=42, value=100)], {}, "damage", total, hits)
        assert grand == 100
        assert total[""] == 100
        assert hits[""] == 1

    def test_map_routes_event_to_named_subgroup(self) -> None:
        total: dict[str, int] = defaultdict(int)
        hits: dict[str, int] = defaultdict(int)
        grand = _accumulate_subgroup_totals(
            [_damage(src=7, value=50), _damage(src=9, value=200)],
            {7: "Subgroup 1", 9: "Subgroup 2"},
            "damage",
            total,
            hits,
        )
        assert grand == 250
        assert total["Subgroup 1"] == 50
        assert total["Subgroup 2"] == 200
        assert hits["Subgroup 1"] == 1
        assert hits["Subgroup 2"] == 1

    def test_shared_hit_dict_accumulates_across_calls(self) -> None:
        # The aggregator passes the SAME hit_dict to all 3 streams; the
        # sum of its values is the grand hit-count. Confirm shared
        # accumulation into one dict.
        total_a: dict[str, int] = defaultdict(int)
        total_b: dict[str, int] = defaultdict(int)
        hits: dict[str, int] = defaultdict(int)
        _accumulate_subgroup_totals([_damage(src=7, value=10)], {7: "S1"}, "damage", total_a, hits)
        _accumulate_subgroup_totals(
            [HealingEvent(time_ms=0, source_agent_id=7, target_agent_id=7, skill_id=1, healing=5)],
            {7: "S1"},
            "healing",
            total_b,
            hits,
        )
        assert hits["S1"] == 2  # one damage + one healing
        assert sum(hits.values()) == 2

    def test_buff_removal_contribution_attr(self) -> None:
        # Round out the 3 event types at the helper level: the strip
        # stream reads the ``buff_removal`` attribute.
        total: dict[str, int] = defaultdict(int)
        hits: dict[str, int] = defaultdict(int)
        grand = _accumulate_subgroup_totals(
            [
                BuffRemovalEvent(
                    time_ms=0, source_agent_id=3, target_agent_id=9, skill_id=1, buff_removal=40
                )
            ],
            {3: "S2"},
            "buff_removal",
            total,
            hits,
        )
        assert grand == 40
        assert total["S2"] == 40
        assert hits["S2"] == 1


class TestAggregatorOutputAfterRefactor:
    def test_multi_stream_output_matches_expectation(self) -> None:
        agent_map = {1: "S1", 2: "S1", 3: "S2"}
        damage = [_damage(src=1, value=300), _damage(src=3, value=100)]
        healing = [
            HealingEvent(time_ms=0, source_agent_id=2, target_agent_id=1, skill_id=1, healing=80)
        ]
        strip = [
            BuffRemovalEvent(
                time_ms=0, source_agent_id=3, target_agent_id=9, skill_id=1, buff_removal=40
            )
        ]
        rows = SquadRollupAggregator().aggregate(damage, healing, strip, agent_map, duration_s=10.0)
        by_sg = {r.subgroup: r for r in rows}
        # S1: 300 damage (agent 1) + 80 healing (agent 2); 2 hits.
        assert by_sg["S1"].total_damage == 300
        assert by_sg["S1"].total_healing == 80
        assert by_sg["S1"].total_buff_removal == 0
        assert by_sg["S1"].hit_count == 2
        assert by_sg["S1"].dps == 30.0  # 300 / 10
        # S2: 100 damage + 40 strip (both agent 3); 2 hits.
        assert by_sg["S2"].total_damage == 100
        assert by_sg["S2"].total_buff_removal == 40
        assert by_sg["S2"].hit_count == 2
        assert by_sg["S2"].bps == 4.0  # 40 / 10
        # Ordering: S1 (300) before S2 (100).
        assert [r.subgroup for r in rows] == ["S1", "S2"]
