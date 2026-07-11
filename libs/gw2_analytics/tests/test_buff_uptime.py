"""Hermetic tests for :mod:`gw2_analytics.buff_uptime` (v0.10.5 plan 137).

The 3 plan-spec tests (invalid history, total_uptime_ms, interval_pct)
+ edge cases for empty history and append-stacks convenience.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.buff_uptime import (
    BuffState,
    interval_uptime_pct,
    total_uptime_ms,
)


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
