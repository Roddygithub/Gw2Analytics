"""Hermetic tests for :mod:`gw2_analytics.buff_uptime` (v0.10.5 plan 137).

The 3 plan-spec tests (invalid history, total_uptime_ms, interval_pct)
+ edge cases for empty history and append-stacks convenience. Phase 9
advisor-plan 026 added :func:`accumulate_buff_events` + 7 tests that
fold :class:`gw2_core.BoonApplyEvent` streams into per-skill-id
:class:`BuffState` instances.
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from gw2_analytics.buff_uptime import (
    BuffState,
    accumulate_buff_events,
    interval_uptime_pct,
    total_uptime_ms,
)
from gw2_core import BoonApplyEvent

# ``Literal[...]`` typing for ``kind`` avoids the previous
# ``# type: ignore[arg-type]`` on each call site -- the parameter is
# narrowed to the union literal at the static type level, so mypy
# accepts ``kind=<literal-string>`` at every call.
_KIND_LITERAL = Literal["apply", "remove_single", "remove_all"]


def _boon_apply(
    time_ms: int,
    skill_id: int,
    stacks: int = 1,
    kind: _KIND_LITERAL = "apply",
) -> BoonApplyEvent:
    """Build a :class:`BoonApplyEvent` for the aggregator tests."""
    return BoonApplyEvent(
        time_ms=time_ms,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=skill_id,
        duration_ms=0,
        stacks=stacks,
        kind=kind,
    )


# ---------------------------------------------------------------------------
# Pre-Phase-9 tests (plan 137 spec + edge cases) -- unchanged
# ---------------------------------------------------------------------------


def test_buff_state_rejects_invalid_history_entry() -> None:
    """Plan 137 spec test 1: BuffState rejects non-tuple / malformed history."""
    with pytest.raises(ValidationError):
        BuffState(history=[(1, "x")])


def test_total_uptime_ms_rejects_fight_end_before_last_history_time() -> None:
    """total_uptime_ms raises ValueError when fight_end_ms precedes history."""
    state = BuffState(history=[(0, 0), (1000, 5), (2000, 0)])
    with pytest.raises(ValueError):
        total_uptime_ms(state, fight_end_ms=1500)


def test_total_uptime_ms_sums_history_correctly() -> None:
    """Plan 137 spec test 2: total uptime on a 3-pair history.

    History: [(0, 0), (1000, 5), (2000, 0)] + fight_end=3000.
    - 0..1000: 0 stacks -> 0
    - 1000..2000: 5 stacks -> 5000
    - 2000..3000: 0 stacks -> 0
    Total = 5000.
    """
    state = BuffState(history=[(0, 0), (1000, 5), (2000, 0)])
    assert total_uptime_ms(state, fight_end_ms=3000) == 5000


def test_interval_uptime_pct_returns_fifty_percent() -> None:
    """Plan 137 spec test 3: half-the-time active returns 50.0."""
    state = BuffState(history=[(0, 0), (1000, 5), (1500, 0)])
    pct = interval_uptime_pct(state, fight_end_ms=5000, fight_start_ms=0)
    assert pct == 50.0


def test_empty_history_yields_zero_uptime() -> None:
    """Empty history => total uptime 0 and interval pct 0.0."""
    state = BuffState(history=[])
    assert total_uptime_ms(state, fight_end_ms=3000) == 0
    assert interval_uptime_pct(state, fight_end_ms=3000) == 0.0


def test_append_stacks_enforces_monotonic_time() -> None:
    """append_stacks raises ValueError on backward-time append."""
    state = BuffState(history=[(1000, 5)])
    with pytest.raises(ValueError):
        state.append_stacks(time_ms=500, stacks=3)


def test_append_stacks_returns_new_state() -> None:
    """append_stacks is immutable and returns a new BuffState."""
    state = BuffState(history=[(0, 0)])
    new_state = state.append_stacks(time_ms=1000, stacks=5)
    assert state is not new_state
    assert new_state.history == [(0, 0), (1000, 5)]


def test_buff_state_validates_monotonic_history() -> None:
    """BuffState raises NonMonotonicHistoryError on non-monotonic history."""
    with pytest.raises(ValidationError) as exc_info:
        BuffState(history=[(1000, 5), (500, 3)])
    errors = exc_info.value.errors()
    assert any("time_ms must be non-decreasing" in str(e) for e in errors)


def test_buff_state_validates_negative_stacks() -> None:
    """BuffState raises NegativeStacksError on negative stacks."""
    with pytest.raises(ValidationError) as exc_info:
        BuffState(history=[(0, -1)])
    errors = exc_info.value.errors()
    assert any("stacks must be non-negative" in str(e) for e in errors)


# ---------------------------------------------------------------------------
# Phase 9 tests: accumulate_buff_events (advisor-plan 026 step 3)
# ---------------------------------------------------------------------------


def test_accumulate_buff_events_empty_stream_returns_empty_dict() -> None:
    """Empty input -> empty output (dict, not None). The aggregator does
    NOT raise; an empty fight has every buff_id absent."""
    assert accumulate_buff_events([]) == {}


def test_accumulate_buff_events_single_apply_no_seed() -> None:
    """A single apply event produces a BuffState whose history begins at
    the event's time_ms -- no (fight_start_ms, 0) seed entry. The
    pre-first-event interval is implicitly 0-stacks for the
    read-side uptime computation (no contribution to
    total_uptime_ms because 0 stacks x duration_ms == 0).
    """
    events = [_boon_apply(time_ms=500, skill_id=100, stacks=1, kind="apply")]
    result = accumulate_buff_events(events)
    assert set(result.keys()) == {100}
    assert result[100].history == [(500, 1)]


def test_accumulate_buff_events_apply_then_remove_single_zeroes_stacks() -> None:
    """apply(+1) -> remove_single(-1) -> 0 stacks; "buff active for 1.5s"."""
    events = [
        _boon_apply(time_ms=500, skill_id=100, stacks=1, kind="apply"),
        _boon_apply(time_ms=2_000, skill_id=100, stacks=1, kind="remove_single"),
    ]
    result = accumulate_buff_events(events)
    assert result[100].history == [(500, 1), (2_000, 0)]
    # 500..2000 is the only active window: 1 stack * 1500 ms = 1500.
    assert total_uptime_ms(result[100], fight_end_ms=10_000) == 1_500


def test_accumulate_buff_events_remove_all_zeroes_stacks() -> None:
    """apply(+2) -> remove_all(wipe) -> 0 stacks regardless of prior count."""
    events = [
        _boon_apply(time_ms=500, skill_id=100, stacks=2, kind="apply"),
        _boon_apply(time_ms=2_000, skill_id=100, stacks=1, kind="remove_all"),
    ]
    result = accumulate_buff_events(events)
    assert result[100].history == [(500, 2), (2_000, 0)]
    # Active interval: 500..2000 -> 2 stacks * 1500 ms = 3000.
    assert total_uptime_ms(result[100], fight_end_ms=10_000) == 3_000


def test_accumulate_buff_events_remove_single_from_zero_stacks_clamps() -> None:
    """Defensive: removing a stack from 0 stacks stays at 0 (no negative
    clamps into the BuffState validator's NegativeStacksError domain)."""
    events = [_boon_apply(time_ms=500, skill_id=100, stacks=1, kind="remove_single")]
    result = accumulate_buff_events(events)
    assert result[100].history == [(500, 0)]


def test_accumulate_buff_events_multiple_skill_ids_partition() -> None:
    """Per-skill-id partitioning: every distinct skill_id gets its own
    BuffState, independent of the others."""
    events = [
        _boon_apply(time_ms=500, skill_id=100, stacks=1, kind="apply"),
        _boon_apply(time_ms=500, skill_id=200, stacks=2, kind="apply"),
        _boon_apply(time_ms=500, skill_id=300, stacks=1, kind="apply"),
    ]
    result = accumulate_buff_events(events)
    assert set(result.keys()) == {100, 200, 300}
    assert result[100].history == [(500, 1)]
    assert result[200].history == [(500, 2)]
    assert result[300].history == [(500, 1)]


def test_accumulate_buff_events_3_way_apply_remove_remove_sequence() -> None:
    """End-to-end 3-way dispatch: apply @ t=0, remove_single @ t=500,
    remove_all @ t=1500, apply @ t=3000 (mid-fight reapply after the
    cleanse). The BuffState history should reflect all 4 transitions
    with no pre-seed entry."""
    events = [
        _boon_apply(time_ms=0, skill_id=100, stacks=3, kind="apply"),
        _boon_apply(time_ms=500, skill_id=100, stacks=1, kind="remove_single"),
        _boon_apply(time_ms=1_500, skill_id=100, stacks=1, kind="remove_all"),
        _boon_apply(time_ms=3_000, skill_id=100, stacks=2, kind="apply"),
    ]
    result = accumulate_buff_events(events)
    assert result[100].history == [
        (0, 3),
        (500, 2),
        (1_500, 0),
        (3_000, 2),
    ]
    # Total uptime-sum:
    # 0..500: 3 stacks * 500 = 1500
    # 500..1500: 2 stacks * 1000 = 2000
    # 1500..3000: 0 stacks * 1500 = 0
    # 3000..5000: 2 stacks * 2000 = 4000
    # Total = 7500
    assert total_uptime_ms(result[100], fight_end_ms=5_000) == 7_500
