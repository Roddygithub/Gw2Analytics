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
from gw2_core import BoonApplyEvent, BuffApplyEvent


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

    def test_might_stacking(self) -> None:
        """Might stacks up to 25; 25 might at 100% = 100% uptime per stack cap."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        # Apply 25 stacks at fight start
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=0, duration_ms=100000, stacks=25)
        )
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        assert uptimes["might"] == pytest.approx(100.0, rel=0.01)

    def test_partial_might_uptime(self) -> None:
        """10 stacks of might for half fight → 20% uptime (10/25 * 50%)."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=0, duration_ms=50000, stacks=10)
        )
        tracker.process(_boon_apply(skill_id=might_id, target=1, time_ms=50000, kind="remove_all"))
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        # 10 stacks for 50s out of 100s → (10*50000) / (25*100000) = 500000/2500000 = 0.2 → 20%
        assert uptimes["might"] == pytest.approx(20.0, rel=0.01)

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
        assert uptimes[2]["might"] == pytest.approx(100.0, rel=0.01)

    def test_remove_single_stacks(self) -> None:
        """remove_single decrements by 1 stack."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=0, duration_ms=100000, stacks=5)
        )
        tracker.process(
            _boon_apply(skill_id=might_id, target=1, time_ms=50000, kind="remove_single")
        )
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=100000)
        # 5 stacks for 50s + 4 stacks for 50s = (5*50000 + 4*50000) / (25*100000)
        # = 450000 / 2500000 = 0.18 → 18%
        assert uptimes["might"] == pytest.approx(18.0, rel=0.01)

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
        # fury is active from t=50000 to t=200000 (end) = 150000ms out of 200000ms
        # But the remove_all at the end of duration_ms is not emitted by parser
        # So the stack is active from 50000 to end = 150000ms
        # 150000 / 200000 = 75%
        assert uptimes["fury"] == pytest.approx(75.0, rel=0.01)

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
            )
        )
        tracker.process(_boon_apply(skill_id=fury_id, target=1, time_ms=3000, kind="remove_all"))
        tracker.process(
            BuffApplyEvent(
                time_ms=6000,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=fury_id,
            )
        )
        # Active 1000..3000 and 6000..10000 = 6000ms out of 10000ms
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=10000)
        assert uptimes["fury"] == pytest.approx(60.0, rel=0.01)

    def test_buff_apply_event_might_one_stack_is_four_pct(self) -> None:
        """A single might stack from BuffApplyEvent yields %/25 stacks."""
        might_id = TRACKED_BUFFS["might"]
        tracker = BuffStateTracker()
        tracker.process(
            BuffApplyEvent(
                time_ms=0,
                source_agent_id=0,
                target_agent_id=1,
                skill_id=might_id,
            )
        )
        uptimes = tracker.compute_player_uptimes(agent_id=1, duration_ms=5000)
        # 1 stack of might / 25 max stacks for full fight -> 4%
        assert uptimes["might"] == pytest.approx(4.0, rel=0.01)

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
        assert first["fury"] == pytest.approx(100.0, rel=0.01)
