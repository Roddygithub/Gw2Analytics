"""Tests for :class:`BuffStateTracker`.

Phase C v0.11.0: foundation for the 14 boon uptime columns + 13 outgoing
boon columns in OrmFightPlayerSummary (plan 172 Phase B).
"""

from __future__ import annotations

import pytest

from gw2_analytics.buff_state import (
    TRACKED_BUFFS,
    BuffStateTracker,
)
from gw2_core import (
    BoonApplyEvent,
    BuffApplyEvent,
    BuffExtensionEvent,
    BuffInfoEvent,
    BuffStackActiveEvent,
    BuffStackDeactiveEvent,
)


def _boon_apply(
    skill_id: int,
    source: int = 1,
    target: int = 1,
    time_ms: int = 0,
    duration_ms: int = 10000,
    stacks: int = 1,
    kind: str = "apply",
) -> BoonApplyEvent:
    return BoonApplyEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=skill_id,
        duration_ms=duration_ms,
        stacks=stacks,
        kind=kind,
    )


class TestBuffStateTracker:
    """BuffStateTracker contract tests."""

    def test_empty_stream(self) -> None:
        """No events → no uptime for anyone."""
        tracker = BuffStateTracker()
        uptimes = tracker.compute_all_uptimes(duration_s=100.0)
        assert uptimes == {}

    def test_zero_active_duration_does_not_fall_back_to_full_fight(self) -> None:
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["fury"],
                target=1,
                time_ms=0,
                duration_ms=1000,
            )
        )

        uptimes = tracker.compute_player_uptimes(
            agent_id=1,
            duration_ms=1000,
            active_duration_ms=0,
        )

        assert uptimes["fury"] == 0.0

    def test_single_boon_apply_full_fight(self) -> None:
        """A boon applied at t=0 that lasts the whole fight → 100% uptime."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=0, duration_ms=100000))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        assert uptimes["fury"] == pytest.approx(100.0, rel=0.01)

    def test_half_uptime(self) -> None:
        """Boons applied for only half the fight → ~50% uptime."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=0, duration_ms=50000))
        # remove at t=50000
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=50000, kind="remove_all"))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        assert uptimes["fury"] == pytest.approx(50.0, rel=0.01)

    @pytest.mark.parametrize("buff_name", TRACKED_BUFFS)
    def test_buffinfo_capacity_applies_to_every_tracked_buff(self, buff_name: str) -> None:
        """Positive EI MaxStacks metadata overrides the fallback for tracked buffs."""
        tracker = BuffStateTracker()
        tracker.process(
            BuffInfoEvent(time_ms=0, skill_id=TRACKED_BUFFS[buff_name], max_stacks=99)
        )

        assert tracker._capacity_for(buff_name) == 99

    def test_buffinfo_zero_capacity_keeps_five_stack_fallback(self) -> None:
        """Missing EI capacity keeps the existing five-entry fallback."""
        skill_id = TRACKED_BUFFS["protection"]
        tracker = BuffStateTracker()
        tracker.process(BuffInfoEvent(time_ms=0, skill_id=skill_id, max_stacks=0))
        for _ in range(6):
            tracker.process(_boon_apply(skill_id=skill_id, time_ms=0, duration_ms=1000))

        tracker.process(_boon_apply(skill_id=skill_id, time_ms=6000, kind="remove_all"))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=6000)
        assert uptimes["protection"] == pytest.approx(83.3333333333)

    def test_might_stacking(self) -> None:
        """Intensity boons report average stacks, matching Elite Insights."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        # Apply 25 stacks at fight start
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=0, duration_ms=100000, stacks=25)
        )
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        assert uptimes["might"] == pytest.approx(25.0, rel=0.01)

    def test_partial_might_uptime(self) -> None:
        """10 stacks of might for half a fight averages 5 stacks."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=0, duration_ms=50000, stacks=10)
        )
        tracker.process(_boon_apply(skill_id=might_id, target=1, time_ms=50000, kind="remove_all"))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        assert uptimes["might"] == pytest.approx(5.0, rel=0.01)

    def test_outgoing_boon(self) -> None:
        """Boon applied to another player tracks as outgoing."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=fury_id, source=1, target=2, time_ms=0, duration_ms=30000)
        )
        outgoing = tracker.compute_player_outgoing(agent_id=1, duration_s=100.0)
        assert outgoing["fury"] == 30000  # 30000ms * 1 stack

    def test_self_apply_not_outgoing(self) -> None:
        """Boon applied to self is NOT counted as outgoing."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=fury_id, source=1, target=1, time_ms=0, duration_ms=30000)
        )
        outgoing = tracker.compute_player_outgoing(agent_id=1, duration_s=100.0)
        assert outgoing["fury"] == 0

    def test_untracked_buff_ignored(self) -> None:
        """A buff not in TRACKED_BUFFS is silently ignored."""
        unknown_id = 99999  # not in TRACKED_BUFFS
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=unknown_id, target=1, time_ms=0, duration_ms=100000))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        # No tracked buffs should be set
        assert all(v == 0.0 for v in uptimes.values())

    def test_multiple_players(self) -> None:
        """Different players get independent uptime tracking."""
        fury_id = TRACKED_BUFFS["fury"]
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        # Player 1: fury for 50% of fight
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=0, duration_ms=50000))
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=50000, kind="remove_all"))
        # Player 2: might for 100% of fight
        tracker.process(
            _boon_apply(skill_id=might_id, target=2, time_ms=0, duration_ms=100000, stacks=25)
        )
        uptimes = tracker.compute_all_uptimes(duration_s=100.0)
        assert uptimes[1]["fury"] == pytest.approx(50.0, rel=0.01)
        assert uptimes[2]["might"] == pytest.approx(25.0, rel=0.01)

    def test_remove_single_stacks(self) -> None:
        """remove_single decrements by 1 stack."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=0, duration_ms=100000, stacks=5)
        )
        tracker.process(
            _boon_apply(
                skill_id=might_id,
                target=1,
                time_ms=50000,
                duration_ms=50000,
                kind="remove_single",
            )
        )
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        # 5 stacks for 50s + 4 stacks for 50s averages 4.5 stacks.
        assert uptimes["might"] == pytest.approx(4.5, rel=0.01)

    def test_zero_duration(self) -> None:
        """Zero fight duration → empty uptimes dict."""
        tracker = BuffStateTracker()
        uptimes = tracker.compute_all_uptimes(duration_s=0.0)
        assert uptimes == {}

    def test_tail_after_last_event(self) -> None:
        """Stack state after the last event continues to end of fight."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        # Apply fury at t=50000 for 100000ms (should last until t=150000)
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=50000, duration_ms=100000))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=200000)
        # The encoded duration expires at t=150000 without a removal event.
        assert uptimes["fury"] == pytest.approx(50.0, rel=0.01)

    def test_preserves_tracked_buffs_count(self) -> None:
        """All 14 tracked buffs are present in the output dict."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=0, duration_ms=100000))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        assert set(uptimes.keys()) == set(TRACKED_BUFFS.keys())
        assert len(uptimes) == 14

    def test_multiple_apply_remove_cycle(self) -> None:
        """Multiple apply/remove cycles accumulate correctly."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        # Cycle 1: apply at 0, remove at 25000
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=0, duration_ms=25000))
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=25000, kind="remove_all"))
        # Cycle 2: apply at 50000, remove at 75000
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=50000, duration_ms=25000))
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=75000, kind="remove_all"))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        # 2 periods of 25000ms active = 50000ms out of 100000ms = 50%
        assert uptimes["fury"] == pytest.approx(50.0, rel=0.01)

    def test_outgoing_multiple_targets(self) -> None:
        """Outgoing to multiple targets accumulates correctly."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=fury_id, source=1, target=2, time_ms=0, duration_ms=10000)
        )
        tracker.process(
            _boon_apply(skill_id=fury_id, source=1, target=3, time_ms=0, duration_ms=20000)
        )
        outgoing = tracker.compute_player_outgoing(agent_id=1, duration_s=100.0)
        assert outgoing["fury"] == 30000  # 10000 + 20000

    def test_all_outgoing_sources(self) -> None:
        """Multiple players with outgoing boons."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=fury_id, source=1, target=2, time_ms=0, duration_ms=10000)
        )
        tracker.process(
            _boon_apply(skill_id=fury_id, source=7, target=3, time_ms=0, duration_ms=20000)
        )
        all_outgoing = tracker.compute_all_outgoing(duration_s=100.0)
        assert all_outgoing[1]["fury"] == 10000
        assert all_outgoing[7]["fury"] == 20000

    def test_no_outgoing_if_no_applications(self) -> None:
        """Player with no BoonApplyEvents has all outgoing values at 0."""
        tracker = BuffStateTracker()
        outgoing = tracker.compute_player_outgoing(agent_id=99, duration_s=100.0)
        # Returns all 14 tracked buffs at 0 for schema consistency
        assert set(outgoing.keys()) == set(TRACKED_BUFFS.keys())
        assert all(v == 0 for v in outgoing.values())

    def test_buff_apply_event_initializes_stack(self) -> None:
        """A BuffApplyEvent alone should initialize the buff stack.

        Regression: prior to the BuffApplyEvent handler, providing only a
        CBTS_BUFFAPPLY snapshot yielded 0% uptime because the tracker only
        processed BoonApplyEvent mid-combat applies.
        """
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            BuffApplyEvent(
                time_ms=500,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=fury_id,
                duration_ms=10_000,
            )
        )
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=10000)
        # Active from 500ms to 10000ms -> 95% uptime
        assert uptimes["fury"] == pytest.approx(95.0, rel=0.01)

    def test_buff_apply_event_tracked_and_untracked(self) -> None:
        """Tracked BuffApplyEvent initializes; untracked is ignored."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            BuffApplyEvent(
                time_ms=0,
                source_agent_id=0,
                target_agent_id=2,
                skill_id=fury_id,
                duration_ms=5_000,
            )
        )
        # untracked skill_id should be ignored without affecting tracked state
        tracker.process(
            BuffApplyEvent(
                time_ms=0,
                source_agent_id=0,
                target_agent_id=2,
                skill_id=99999,
            )
        )
        uptimes = tracker.compute_player_uptimes(agent_id=2, duration_ms=5000)
        assert uptimes["fury"] == pytest.approx(100.0, rel=0.01)

    def test_buff_apply_event_then_remove_restores(self) -> None:
        """BuffApplyEvent followed by remove_all, then another apply."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            BuffApplyEvent(
                time_ms=1000,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=fury_id,
                duration_ms=2_000,
            )
        )
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=3000, kind="remove_all"))
        tracker.process(
            BuffApplyEvent(
                time_ms=6000,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=fury_id,
                duration_ms=4_000,
            )
        )
        # Active 1000..3000 and 6000..10000 = 6000ms out of 10000ms
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=10000)
        assert uptimes["fury"] == pytest.approx(60.0, rel=0.01)

    def test_buff_apply_event_might_reports_average_stack(self) -> None:
        """A single might stack reports one average stack."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        tracker.process(
            BuffApplyEvent(
                time_ms=0,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=might_id,
                duration_ms=5_000,
            )
        )
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=5000)
        assert uptimes["might"] == pytest.approx(1.0, rel=0.01)

    def test_equal_duration_might_stacks_match_ei_midpoint_insertion(self) -> None:
        tracker = BuffStateTracker()
        for stack_id in (1, 2, 3):
            tracker.process(
                BuffApplyEvent(
                    time_ms=0,
                    source_agent_id=0,
                    target_agent_id=1,
                    skill_id=TRACKED_BUFFS["might"],
                    duration_ms=5_000,
                    stack_id=stack_id,
                )
            )

        # EI's midpoint+1 insertion yields this non-stable equal-duration order.
        assert tracker._get_stack(1, "might").stack_ids == [1, 3, 2]

    def test_buff_apply_snapshots_preserve_all_initial_stacks(self) -> None:
        tracker = BuffStateTracker()
        for duration_ms in (2_000, 3_000):
            tracker.process(
                BuffApplyEvent(
                    time_ms=0,
                    source_agent_id=0,
                    target_agent_id=1,
                    skill_id=TRACKED_BUFFS["fury"],
                    duration_ms=duration_ms,
                )
            )

        assert tracker.compute_player_uptimes(1, 10_000)["fury"] == pytest.approx(50.0)

    @pytest.mark.parametrize("skill_id", [TRACKED_BUFFS["protection"], 718])
    def test_zero_duration_queue_and_regeneration_expire_over_positive_fight(
        self, skill_id: int
    ) -> None:
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=skill_id, target=1, time_ms=0, duration_ms=0))
        buff = "regeneration" if skill_id == 718 else "protection"
        assert tracker.compute_player_uptimes(1, 1_000)[buff] == 0

    @pytest.mark.parametrize("skill_id", [TRACKED_BUFFS["protection"], 718])
    def test_max_duration_queue_and_regeneration_remain_active(self, skill_id: int) -> None:
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=skill_id, target=1, time_ms=0, duration_ms=2**31 - 1)
        )
        buff = "regeneration" if skill_id == 718 else "protection"
        assert tracker.compute_player_uptimes(1, 1_000)[buff] == 100

    def test_intensity_expiry_at_event_time_is_removed_before_new_apply(self) -> None:
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=0, duration_ms=100)
        )

        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=100, duration_ms=100)
        )

        stack = tracker._agent_buffs[1]["might"]
        assert stack.expirations == [200]
        assert stack.total_durations == [100]
        assert stack.cumulative_stack_ms == 100

    def test_override_single_removal_matches_duration_not_stack_id(self) -> None:
        tracker = BuffStateTracker()
        for stack_id, duration in ((11, 1_000), (22, 2_000)):
            tracker.process(
                _boon_apply(
                    skill_id=TRACKED_BUFFS["might"], target=1, duration_ms=duration
                ).model_copy(update={"stack_id": stack_id})
            )

        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["might"],
                target=1,
                duration_ms=2_000,
                kind="remove_single",
            ).model_copy(update={"stack_id": 11})
        )

        stack = tracker._agent_buffs[1]["might"]
        assert stack.stack_ids == [11]
        assert stack.total_durations == [1_000]

    def test_deactive_event_does_not_mutate_tracker(self) -> None:
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["might"], target=1, duration_ms=1_000
            ).model_copy(update={"stack_id": 11})
        )
        stack = tracker._agent_buffs[1]["might"]
        before = (stack.expirations.copy(), stack.stack_ids.copy(), stack.total_durations.copy())

        tracker.process(
            BuffStackDeactiveEvent(
                time_ms=100, source_agent_id=0, target_agent_id=1,
                skill_id=TRACKED_BUFFS["might"], stack_id=11,
            )
        )

        assert (
            stack.expirations, stack.stack_ids, stack.total_durations
        ) == before

    def test_stability_buff_apply_preserves_original_duration_for_removal(self) -> None:
        tracker = BuffStateTracker(stability_duration_correction=True)
        tracker.process(
            BuffApplyEvent(
                time_ms=0,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=TRACKED_BUFFS["stability"],
                duration_ms=1_500,
                original_duration_ms=2_000,
                stack_id=22,
            )
        )

        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                time_ms=500,
                duration_ms=2_000,
                kind="remove_single",
            ).model_copy(update={"stack_id": 22})
        )

        assert tracker._agent_buffs[1]["stability"].expirations == []

    def test_stability_removal_uses_ei_instance_duration_correction(self) -> None:
        tracker = BuffStateTracker(stability_duration_correction=True)
        for stack_id, duration in ((11, 1_000), (22, 2_000)):
            tracker.process(
                _boon_apply(
                    skill_id=TRACKED_BUFFS["stability"], target=1, duration_ms=duration
                ).model_copy(update={"stack_id": stack_id})
            )

        # EI recognizes the original applied duration and normalizes it to the
        # remaining duration using the instance ID before simulator removal.
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                time_ms=1_000,
                duration_ms=2_000,
                kind="remove_single",
            ).model_copy(update={"stack_id": 22})
        )

        assert tracker._agent_buffs[1]["stability"].expirations == []

    def test_stability_extension_updates_ei_original_duration_for_removal(self) -> None:
        tracker = BuffStateTracker(stability_duration_correction=True)
        tracker.process(
            _boon_apply(skill_id=TRACKED_BUFFS["stability"], target=1, duration_ms=2_000)
            .model_copy(update={"stack_id": 22})
        )
        tracker.process(
            BuffExtensionEvent(
                time_ms=500,
                source_agent_id=1,
                target_agent_id=1,
                skill_id=TRACKED_BUFFS["stability"],
                extended_duration_ms=500,
                new_duration_ms=2_500,
                stack_id=22,
            )
        )

        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                time_ms=1_000,
                duration_ms=2_500,
                kind="remove_single",
            ).model_copy(update={"stack_id": 22})
        )

        assert tracker._agent_buffs[1]["stability"].expirations == []

    def test_stability_reused_instance_uses_latest_apply_and_extension_window(self) -> None:
        tracker = BuffStateTracker(stability_duration_correction=True)
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                time_ms=0,
                duration_ms=2_000,
            ).model_copy(update={"stack_id": 22})
        )
        tracker.process(
            BuffExtensionEvent(
                time_ms=300,
                source_agent_id=1,
                target_agent_id=1,
                skill_id=TRACKED_BUFFS["stability"],
                extended_duration_ms=500,
                new_duration_ms=2_500,
                stack_id=22,
            )
        )
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                time_ms=400,
                duration_ms=1_000,
            ).model_copy(update={"stack_id": 22})
        )

        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                time_ms=900,
                duration_ms=1_000,
                kind="remove_single",
            ).model_copy(update={"stack_id": 22})
        )

        stack = tracker._agent_buffs[1]["stability"]
        assert stack.total_durations == [1_600]
        assert stack.stack_ids == [22]

    def test_stability_extension_keeps_normalization_id_separate_from_simulator_match(
        self,
    ) -> None:
        tracker = BuffStateTracker()
        for stack_id, duration in ((11, 1_000), (22, 2_000)):
            tracker.process(
                _boon_apply(
                    skill_id=TRACKED_BUFFS["stability"], target=1, duration_ms=duration
                ).model_copy(update={"stack_id": stack_id})
            )

        tracker.process(
            BuffExtensionEvent(
                time_ms=0,
                source_agent_id=1,
                target_agent_id=1,
                skill_id=TRACKED_BUFFS["stability"],
                extended_duration_ms=500,
                new_duration_ms=2_500,
                stack_id=11,
            )
        )

        stack = tracker._agent_buffs[1]["stability"]
        assert stack.stack_ids == [11, 22]
        assert stack.total_durations == [1_000, 2_500]
        assert stack.expirations == [1_000, 2_500]
        assert tracker._stability_extensions[(1, 11)] == [(0, 500)]

    def test_stability_duration_correction_disabled_matches_raw_duration(self) -> None:
        tracker = BuffStateTracker()
        for duration in (1_000, 2_000):
            tracker.process(
                _boon_apply(
                    skill_id=TRACKED_BUFFS["stability"], target=1, duration_ms=duration
                ).model_copy(update={"stack_id": 0})
            )

        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                time_ms=1_000,
                duration_ms=2_000,
                kind="remove_single",
            ).model_copy(update={"stack_id": 0})
        )

        assert tracker._agent_buffs[1]["stability"].stack_ids == [0]

    def test_might_max_duration_removal_is_normalized_by_instance_history(self) -> None:
        tracker = BuffStateTracker(might_duration_correction=True)
        max_duration = 2**31 - 1
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["might"],
                target=1,
                duration_ms=max_duration,
            ).model_copy(update={"stack_id": 22})
        )
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["might"],
                target=1,
                time_ms=100,
                duration_ms=max_duration,
                kind="remove_single",
            ).model_copy(update={"stack_id": 22})
        )

        assert tracker._agent_buffs[1]["might"].stack_ids == []

    def test_stability_without_instance_ids_matches_duration(self) -> None:
        tracker = BuffStateTracker()
        for duration in (1_000, 2_000):
            tracker.process(
                _boon_apply(
                    skill_id=TRACKED_BUFFS["stability"], target=1, duration_ms=duration
                ).model_copy(update={"stack_id": 0})
            )

        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["stability"],
                target=1,
                duration_ms=2_000,
                kind="remove_single",
            ).model_copy(update={"stack_id": 0})
        )

        stack = tracker._agent_buffs[1]["stability"]
        assert stack.total_durations == [1_000]
        assert stack.stack_ids == [0]

    def test_manual_expiry_marker_does_not_remove_next_stack(self) -> None:
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=TRACKED_BUFFS["fury"], duration_ms=5_000))
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["fury"],
                time_ms=5_000,
                duration_ms=5_000,
                kind="remove_single",
                stacks=1,
            )
        )
        tracker.process(_boon_apply(skill_id=TRACKED_BUFFS["fury"], time_ms=5_000))

        assert tracker.compute_player_uptimes(1, 10_000)["fury"] == pytest.approx(100.0)

    def test_early_manual_removal_still_clears_active_stack(self) -> None:
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=TRACKED_BUFFS["fury"], duration_ms=10_000))
        tracker.process(
            _boon_apply(
                skill_id=TRACKED_BUFFS["fury"],
                time_ms=5_000,
                duration_ms=5_000,
                kind="remove_single",
                stacks=1,
            )
        )

        assert tracker.compute_player_uptimes(1, 10_000)["fury"] == pytest.approx(50.0)

    def test_buff_apply_event_then_remove_all(self) -> None:
        """BuffApplyEvent at t=0 followed by remove_all at t=5000 -> 50%."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(
            BuffApplyEvent(
                time_ms=0,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=fury_id,
                duration_ms=5_000,
            )
        )
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=5000, kind="remove_all"))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=10000)
        # Active 0..5000 =  50% uptime
        assert uptimes["fury"] == pytest.approx(50.0, rel=0.01)

    def test_compute_player_uptimes_is_idempotent(self) -> None:
        """Calling compute_player_uptimes twice must return the same result."""
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=0, duration_ms=50000))
        first = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        second = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        assert first["fury"] == pytest.approx(second["fury"])
        assert first["fury"] == pytest.approx(50.0, rel=0.01)

    def test_absolute_event_times_use_fight_origin(self) -> None:
        fury_id = TRACKED_BUFFS["fury"]
        tracker = BuffStateTracker(start_time_ms=42_047_693)
        tracker.process(
            _boon_apply(
                skill_id=fury_id,
                target=1,
                time_ms=42_047_693,
                duration_ms=5_000,
            )
        )
        assert tracker.compute_player_uptimes(1, 10_000)["fury"] == pytest.approx(50.0)

    def test_merged_uptime_keeps_late_recycled_slice_after_despawn(self) -> None:
        fury_id = TRACKED_BUFFS["fury"]
        origin = 1_000_000
        tracker = BuffStateTracker(start_time_ms=origin)
        tracker.process(
            _boon_apply(
                skill_id=fury_id,
                target=1,
                time_ms=origin,
                duration_ms=4_000,
            )
        )
        tracker.end_agent(1, origin + 4_000)
        tracker.process(
            _boon_apply(
                skill_id=fury_id,
                target=2,
                time_ms=origin + 6_000,
                duration_ms=4_000,
            )
        )
        tracker.end_agent(2, origin + 10_000)

        merged = tracker.compute_merged_uptimes(
            [1, 2],
            duration_ms=10_000,
            slice_lo_ms=0,
            slice_hi_ms=10_000,
            awareness_spans={1: (0, 4_000), 2: (6_000, 10_000)},
        )

        assert merged["fury"] == pytest.approx(80.0)

    def test_buff_extension_extends_active_duration_stack(self) -> None:
        protection_id = TRACKED_BUFFS["protection"]
        tracker = BuffStateTracker()
        tracker.process(_boon_apply(skill_id=protection_id, duration_ms=2_000))
        tracker.process(
            BuffExtensionEvent(
                time_ms=1_000,
                source_agent_id=1,
                target_agent_id=1,
                skill_id=protection_id,
                extended_duration_ms=3_000,
                new_duration_ms=4_000,
            )
        )

        stack = tracker._agent_buffs[1]["protection"]
        assert stack.expirations == [1_000]
        assert stack.queue_extensions == [[3_000]]
        assert tracker.compute_player_uptimes(1, 10_000)["protection"] == pytest.approx(50.0)

    def test_queue_extension_targets_active_front_not_matching_stack_id(self) -> None:
        swiftness_id = TRACKED_BUFFS["swiftness"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=swiftness_id, time_ms=0, duration_ms=2_000)
            .model_copy(update={"stack_id": 11})
        )
        tracker.process(
            _boon_apply(skill_id=swiftness_id, time_ms=0, duration_ms=1_000)
            .model_copy(update={"stack_id": 22})
        )
        tracker.process(
            BuffExtensionEvent(
                time_ms=100,
                source_agent_id=1,
                target_agent_id=1,
                skill_id=swiftness_id,
                extended_duration_ms=100,
                new_duration_ms=1_000,
                stack_id=22,
            )
        )

        stack = tracker._agent_buffs[1]["swiftness"]
        assert stack.expirations == [1_900, 1_000]
        assert stack.queue_extensions == [[100], []]

    def test_queue_logic_single_removal_matches_total_duration_before_stack_id(self) -> None:
        protection_id = TRACKED_BUFFS["protection"]
        tracker = BuffStateTracker()
        for stack_id, duration in ((11, 1_000), (22, 2_000)):
            tracker.process(
                _boon_apply(
                    skill_id=protection_id, target=7, duration_ms=duration,
                ).model_copy(update={"stack_id": stack_id})
            )

        tracker.process(
            _boon_apply(
                skill_id=protection_id, target=7, time_ms=100,
                duration_ms=2_000, kind="remove_single",
            ).model_copy(update={"stack_id": 11})
        )

        assert tracker._agent_buffs[7]["protection"].stack_ids == [11]


def test_intensity_total_duration_decreases_with_elapsed_time() -> None:
    tracker = BuffStateTracker()
    tracker.process(
        _boon_apply(
            skill_id=TRACKED_BUFFS["might"],
            duration_ms=1_000,
            stacks=2,
        )
    )
    stack = tracker._agent_buffs[1]["might"]

    BuffStateTracker._advance(stack, 400)

    assert stack.total_durations == [600, 600]


def test_override_extension_without_live_stack_creates_absolute_expiry() -> None:
    tracker = BuffStateTracker()
    tracker.process(
        BuffExtensionEvent(
            time_ms=100,
            source_agent_id=1,
            target_agent_id=1,
            skill_id=TRACKED_BUFFS["might"],
            extended_duration_ms=1_000,
            new_duration_ms=1_000,
            stack_id=11,
        )
    )

    stack = tracker._agent_buffs[1]["might"]
    assert stack.expirations == [1_100]
    assert stack.total_durations == [1_000]
    assert stack.stack_ids == [11]
    assert tracker.compute_player_uptimes(1, 10_000)["might"] == pytest.approx(0.1)


def test_regeneration_extension_without_live_stack_creates_ei_duration() -> None:
    tracker = BuffStateTracker()
    tracker.process(
        BuffExtensionEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            extended_duration_ms=100,
            new_duration_ms=1_100,
            stack_id=9,
        )
    )

    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.expirations == [1_100]
    assert stack.total_durations == [1_100]
    assert stack.stack_ids == [9]
    assert stack.regen_extensions == [[]]
    assert tracker.compute_player_uptimes(7, 1_100)["regeneration"] == pytest.approx(100.0)


def test_regeneration_added_extension_uses_last_expired_seed_healing() -> None:
    tracker = BuffStateTracker(healing_by_agent={1: 5, 2: 50, 3: 100})
    tracker.process(_regen_apply(0, 100, 1).model_copy(update={"source_agent_id": 1}))
    tracker.process(_regen_apply(0, 1_000, 2).model_copy(update={"source_agent_id": 2}))
    tracker.process(
        BuffStackActiveEvent(
            time_ms=0, source_agent_id=1, target_agent_id=7,
            skill_id=718, stack_id=1,
        )
    )
    tracker.process(
        BuffExtensionEvent(
            time_ms=100, source_agent_id=3, target_agent_id=7, skill_id=718,
            extended_duration_ms=100, new_duration_ms=100, stack_id=3,
        )
    )

    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.stack_ids == [3, 2]
    assert stack.healing_scores == [5, 50]


def test_regeneration_extension_with_zero_old_value_adds_active_stack() -> None:
    tracker = BuffStateTracker()
    tracker.process(_regen_apply(0, 5_000, 1))
    tracker.process(
        BuffExtensionEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            extended_duration_ms=100,
            new_duration_ms=100,
            stack_id=2,
        )
    )

    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.stack_ids == [2, 1]
    assert stack.expirations == [100, 5_000]


def test_regeneration_extension_at_capacity_extends_front_with_zero_old_value() -> None:
    tracker = BuffStateTracker()
    for sid in range(5):
        tracker.process(_regen_apply(0, 5_000 + sid, sid))
    tracker.process(
        BuffExtensionEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            extended_duration_ms=100,
            new_duration_ms=100,
            stack_id=9,
        )
    )

    stack = tracker._agent_buffs[7]["regeneration"]
    assert len(stack.expirations) == 5
    assert stack.expirations[0] == 5_000
    assert stack.total_durations[0] == 5_100
    assert stack.regen_extensions[0] == [100]


def test_regeneration_extensions_stay_aligned_after_healing_priority_sort() -> None:
    tracker = BuffStateTracker(healing_by_agent={1: 10, 2: 30, 3: 20})
    tracker.process(
        BuffApplyEvent(
            time_ms=0, source_agent_id=1, target_agent_id=7, skill_id=718,
            duration_ms=1_000, stack_id=1,
        )
    )
    tracker.process(
        BuffExtensionEvent(
            time_ms=0, source_agent_id=1, target_agent_id=7, skill_id=718,
            extended_duration_ms=100, new_duration_ms=1_100, stack_id=1,
        )
    )
    tracker.process(
        BuffApplyEvent(
            time_ms=0, source_agent_id=2, target_agent_id=7, skill_id=718,
            duration_ms=2_000, stack_id=2,
        )
    )
    tracker.process(
        BuffApplyEvent(
            time_ms=0, source_agent_id=3, target_agent_id=7, skill_id=718,
            duration_ms=3_000, stack_id=3,
        )
    )

    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.stack_ids == [2, 3, 1]
    assert stack.healing_scores == [30, 20, 10]
    assert stack.expirations == [2_000, 3_000, 1_000]
    assert stack.total_durations == [2_000, 3_000, 1_100]
    assert stack.regen_extensions == [[], [], [100]]


def test_regeneration_extension_extends_front_stack() -> None:
    tracker = BuffStateTracker()
    tracker.process(_regen_apply(0, 5_000, 1))
    tracker.process(_regen_apply(0, 1_000, 2))
    tracker.process(
        BuffExtensionEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            extended_duration_ms=100,
            new_duration_ms=1_100,
            stack_id=2,
        )
    )
    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.expirations == [5_000, 1_000]
    assert stack.total_durations == [5_100, 1_000]
    assert stack.regen_extensions == [[100], []]


def test_regeneration_total_duration_is_not_reduced_by_elapsed_time() -> None:
    tracker = BuffStateTracker()
    tracker.process(_regen_apply(0, 1_000, 1))
    tracker.process(_regen_apply(400, 1_000, 2))
    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.expirations == [600, 1_000]
    assert stack.total_durations == [600, 1_000]


def test_regeneration_pending_extension_keeps_stack_metadata_at_expiry() -> None:
    tracker = BuffStateTracker()
    tracker.process(_regen_apply(0, 1_000, 1))
    tracker.process(
        BuffExtensionEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            extended_duration_ms=100,
            new_duration_ms=1_100,
            stack_id=1,
        )
    )
    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.expirations == [1_000]
    assert stack.total_durations == [1_100]
    assert stack.regen_extensions == [[100]]
    assert tracker.compute_player_uptimes(7, 1_100)["regeneration"] == pytest.approx(100.0)
    assert tracker.compute_merged_uptimes([7], 1_100)["regeneration"] == pytest.approx(100.0)

    BuffStateTracker._advance(stack, 1_000)

    assert stack.expirations == [100]
    assert stack.total_durations == [100]
    assert stack.stack_ids == [1]


def test_regeneration_stack_active_record_moves_the_stack_to_the_front() -> None:
    """An explicit stack-active record activates a queued regeneration stack.

    Regeneration is a queue: only the front stack burns down, the rest wait.
    Activating a queued stack therefore changes which duration is spent
    first, and Elite Insights latches "stop sorting" off the back of it.
    """
    tracker = BuffStateTracker()

    def apply(time_ms: int, duration_ms: int, stack_id: int) -> BoonApplyEvent:
        return BoonApplyEvent(
            time_ms=time_ms,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            duration_ms=duration_ms,
            stacks=1,
            stack_id=stack_id,
        )

    tracker.process(apply(0, 1_000, 11))
    tracker.process(apply(0, 5_000, 22))
    assert tracker._healing_no_sort is False

    tracker.process(
        BuffStackActiveEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            stack_id=22,
        )
    )
    assert tracker._healing_no_sort is True

    # The long stack now burns first, so a 3 s window is fully covered.
    assert tracker.compute_player_uptimes(7, 3_000)["regeneration"] == 100.0


def test_initial_regeneration_snapshot_preserves_stack_order() -> None:
    tracker = BuffStateTracker()

    tracker.process(
        BuffApplyEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            duration_ms=1_000,
            stack_id=11,
        )
    )
    tracker.process(
        BuffApplyEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=718,
            duration_ms=5_000,
            stack_id=22,
        )
    )

    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.stack_ids == [11, 22]
    assert tracker._healing_no_sort is False


def test_regeneration_single_removal_matches_total_duration_before_stack_id() -> None:
    tracker = BuffStateTracker()
    tracker.process(_regen_apply(0, 1_000, 11))
    tracker.process(_regen_apply(0, 2_000, 22))
    tracker.process(
        _regen_apply(0, 1_000, 22).model_copy(update={"kind": "remove_single"})
    )

    assert tracker._agent_buffs[7]["regeneration"].stack_ids == [22]


def test_stability_fallback_capacity_without_buff_info_is_25() -> None:
    tracker = BuffStateTracker()
    tracker.process(
        _boon_apply(
            skill_id=TRACKED_BUFFS["stability"],
            target=7,
            duration_ms=5_000,
            stacks=26,
        )
    )

    assert len(tracker._agent_buffs[7]["stability"].expirations) == 25


def test_override_extension_keeps_capacity_eviction_order_and_metadata_aligned() -> None:
    tracker = BuffStateTracker(healing_by_agent={1: 10})
    skill_id = TRACKED_BUFFS["might"]
    for stack_id, duration in enumerate(range(100, 2_600, 100), start=1):
        tracker.process(
            _boon_apply(skill_id, target=7, duration_ms=duration)
            .model_copy(update={"stack_id": stack_id})
        )

    tracker.process(
        BuffExtensionEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=skill_id,
            extended_duration_ms=10_000,
            new_duration_ms=10_100,
            stack_id=1,
        )
    )
    tracker.process(
        _boon_apply(skill_id, target=7, duration_ms=300)
        .model_copy(update={"stack_id": 99})
    )

    stack = tracker._agent_buffs[7]["might"]
    assert 1 not in stack.stack_ids
    assert 2 in stack.stack_ids
    assert len(stack.expirations) == 25
    assert len(stack.total_durations) == 25
    assert len(stack.stack_ids) == 25
    assert len(stack.healing_scores) == 25
    assert stack.stack_ids == [2, 3, 99, *range(4, 26)]
    assert all(score == 10 for score in stack.healing_scores)
    assert all(
        expiry == duration
        for expiry, duration in zip(stack.expirations, stack.total_durations, strict=True)
    )


def _regen_apply(time_ms: int, duration_ms: int, stack_id: int) -> BoonApplyEvent:
    return BoonApplyEvent(
        time_ms=time_ms,
        source_agent_id=1,
        target_agent_id=7,
        skill_id=718,
        duration_ms=duration_ms,
        stacks=1,
        stack_id=stack_id,
    )


def _fill_regen_queue(tracker: BuffStateTracker) -> None:
    """Fill queue to capacity (15), longest last, so evicting the tail is expensive."""
    # 14 short stacks + 1 long stack = 15 total (capacity)
    durations = [1_000] * 14 + [60_000]
    for index, duration in enumerate(durations):
        tracker.process(_regen_apply(0, duration, 100 + index))


def test_regeneration_overstack_hint_names_the_displaced_stack() -> None:
    """arcdps says which stack an application displaced; the queue obeys it.

    Without the hint the sixth application evicts the tail -- here a 60 s
    stack -- and the whole queue is worth barely a second afterwards.
    """
    tracker = BuffStateTracker(regen_overstacks={7: [(5, 1_000, 102)]})
    _fill_regen_queue(tracker)
    tracker.process(_regen_apply(10, 2_000, 999))

    # The hint named instance 102, a 1 s stack, so the 60 s one survives.
    assert tracker.compute_player_uptimes(7, 30_000)["regeneration"] == 100.0


def test_initial_regeneration_overflow_hint_evicts_named_non_tail_stack() -> None:
    tracker = BuffStateTracker(regen_overstacks={7: [(0, 10_000, 102)]})
    for stack_id, duration in zip(
        (100, 101, 102, 103, 104), (5_000, 9_000, 10_000, 11_000, 12_000), strict=True
    ):
        tracker.process(_regen_apply(0, duration, stack_id))

    tracker.process(_regen_apply(0, 2_000, 999))

    stack = tracker._agent_buffs[7]["regeneration"]
    assert 102 not in stack.stack_ids
    assert 104 in stack.stack_ids


def test_initial_regeneration_overflow_without_hint_evicts_lowest_heal_tail() -> None:
    tracker = BuffStateTracker(healing_by_agent={1: 10, 2: 20})
    for stack_id, duration in zip(
        (100, 101, 102, 103, 104), range(5_000, 10_000, 1_000), strict=True
    ):
        tracker.process(
            _regen_apply(0, duration, stack_id).model_copy(update={"source_agent_id": 1})
        )
    tracker.process(_regen_apply(10, 2_000, 999).model_copy(update={"source_agent_id": 2}))

    stack = tracker._agent_buffs[7]["regeneration"]
    assert stack.stack_ids == [999, 100, 101, 102, 103]
    assert stack.healing_scores == [20, 10, 10, 10, 10]


def test_regeneration_overstack_hint_is_consumed_once() -> None:
    tracker = BuffStateTracker(regen_overstacks={7: [(5, 10_000, 102)]})
    for stack_id, duration in zip(
        (100, 101, 102, 103, 104),
        (5_000, 9_000, 10_000, 11_000, 12_000),
        strict=True,
    ):
        tracker.process(_regen_apply(0, duration, stack_id))

    tracker.process(_regen_apply(10, 2_000, 999))
    tracker.process(_regen_apply(10, 2_000, 1_000))

    stack = tracker._agent_buffs[7]["regeneration"]
    assert 102 not in stack.stack_ids
    assert 101 in stack.stack_ids
    assert 1_000 in stack.stack_ids


def test_regeneration_overstack_hint_falls_back_to_the_closest_duration() -> None:
    """With no matching instance, the stack closest to the removed duration goes."""
    tracker = BuffStateTracker(regen_overstacks={7: [(5, 1_000, 0)]})
    _fill_regen_queue(tracker)
    tracker.process(_regen_apply(10, 2_000, 999))

    assert tracker.compute_player_uptimes(7, 30_000)["regeneration"] == 100.0


def test_regeneration_without_a_hint_still_evicts_the_tail() -> None:
    """A hint too far from the application is not one, and the tail goes."""
    from gw2_analytics.buff_state import _capacity_for

    # Temporarily reduce capacity for this test to match original test design (capacity 5)
    original_capacity_for = _capacity_for

    def test_capacity_for(name: str) -> int:
        if name == "regeneration":
            return 5
        return original_capacity_for(name)

    import gw2_analytics.buff_state as bs

    bs._capacity_for = test_capacity_for

    tracker = BuffStateTracker(regen_overstacks={7: [(5, 1_000, 102)]})
    # Fill to capacity (5): 4 short (1s) + 1 long (60s) = 5 stacks
    for index, duration in enumerate([1_000] * 4 + [60_000]):
        tracker.process(_regen_apply(0, duration, 100 + index))
    # 6th application at 100ms: should overflow and evict tail (60s stack)
    tracker.process(_regen_apply(100, 2_000, 999))

    # The 60 s stack was evicted, so the queue runs dry long before 30 s.
    assert tracker.compute_player_uptimes(7, 30_000)["regeneration"] < 30.0

    # Restore
    bs._capacity_for = original_capacity_for


def test_queue_logic_overflow_replaces_shortest_stack_in_place() -> None:
    """EI QueueLogic.FindLowestValue replaces the shortest non-front stack
    in place (stacks[IndexOf(toRemove)] = toAdd), preserving queue order.

    The old port popped the victim and appended the new stack at the end,
    rotating the queue and changing which stack fronts next.
    """
    protection_id = TRACKED_BUFFS["protection"]
    tracker = BuffStateTracker()
    # Fill to capacity (5 per EI 3.26) with durations so the shortest non-front stack
    # (300 ms) sits at index 3, not at the tail.
    durations = [5_000, 1_000, 900, 300, 400]
    for index, duration in enumerate(durations):
        tracker.process(
            BoonApplyEvent(
                time_ms=0,
                source_agent_id=1,
                target_agent_id=7,
                skill_id=protection_id,
                duration_ms=duration,
                stacks=1,
                stack_id=100 + index,
            )
        )
    stack = tracker._agent_buffs[7]["protection"]
    assert len(stack.expirations) == 5

    # Overflow apply: EI replaces the 300 ms stack at index 3 in place.
    tracker.process(
        BoonApplyEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=7,
            skill_id=protection_id,
            duration_ms=9_999,
            stacks=1,
            stack_id=999,
        )
    )
    assert len(stack.expirations) == 5
    assert stack.expirations[3] == 9_999  # replaced in place, not appended
    assert stack.expirations[0] == 5_000  # front untouched
    assert stack.expirations[4] == 400  # tail order preserved


def test_queue_logic_overflow_compares_duration_plus_pending_extensions() -> None:
    protection_id = TRACKED_BUFFS["protection"]
    tracker = BuffStateTracker()
    for stack_id, duration in enumerate((100, 200, 300, 400, 500), start=1):
        tracker.process(
            _boon_apply(
                skill_id=protection_id, target=7, time_ms=0,
                duration_ms=duration,
            ).model_copy(update={"stack_id": stack_id})
        )
    tracker.process(
        BuffExtensionEvent(
            time_ms=0, source_agent_id=1, target_agent_id=7,
            skill_id=protection_id, extended_duration_ms=500,
            new_duration_ms=600, stack_id=1,
        )
    )
    tracker.process(
        _boon_apply(
            skill_id=protection_id, target=7, time_ms=0,
            duration_ms=9_000,
        ).model_copy(update={"stack_id": 99})
    )
    tracker.process(
        _boon_apply(
            skill_id=protection_id, target=7, time_ms=0,
            duration_ms=8_000,
        ).model_copy(update={"stack_id": 100})
    )

    stack = tracker._agent_buffs[7]["protection"]
    assert 1 in stack.stack_ids
    assert 3 not in stack.stack_ids
    assert stack.stack_ids.count(100) == 1
