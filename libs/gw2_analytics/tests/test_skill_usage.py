"""Tests for :mod:`gw2_analytics.skill_usage`.

Sister suite to ``test_target_healing.py``. Mirrors the in-place
``DamageEvent`` / ``HealingEvent`` / ``BuffRemovalEvent`` construction
pattern so we are not dependent on the EVTC binary parser's edge-case
coverage -- the :class:`SkillUsageAggregator` is fed synthetic event
inputs.

Invariants locked down here:

- every cross-field contract listed on
  :class:`gw2_analytics.skill_usage.SkillUsageAggregator`
- deterministic ordering: highest ``total_damage`` first, ties
  broken by ascending ``skill_id``
- one skill can carry damage + healing + strip from independent
  events (dual-emit pattern from Phase 8 lands in the same row)
- unknown ``skill_id`` renders as ``skill_name=""``
- the returned row is immutable (frozen pydantic model)
"""

from __future__ import annotations

import pytest

from gw2_analytics.skill_usage import SkillUsageAggregator
from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent


def _damage(time_ms: int, src: int, dst: int, value: int, skill_id: int) -> DamageEvent:
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill_id,
        damage=value,
    )


def _heal(time_ms: int, src: int, dst: int, value: int, skill_id: int) -> HealingEvent:
    return HealingEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill_id,
        healing=value,
    )


def _strip(time_ms: int, src: int, dst: int, value: int, skill_id: int) -> BuffRemovalEvent:
    return BuffRemovalEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill_id,
        buff_removal=value,
    )


# ---------------------------------------------------------------------------
# Empty + single-skill cases
# ---------------------------------------------------------------------------


def test_empty_input_yields_no_rows() -> None:
    """Empty input + empty map -> ``[]`` (no synthesised rows)."""
    rows = SkillUsageAggregator().aggregate([], [], [], {})
    assert rows == []


def test_single_skill_damage_heal_strip() -> None:
    """One skill, three event kinds, all in one row."""
    rows = SkillUsageAggregator().aggregate(
        [_damage(0, src=10, dst=20, value=500, skill_id=1)],
        [_heal(1, src=10, dst=30, value=200, skill_id=1)],
        [_strip(2, src=10, dst=40, value=100, skill_id=1)],
        {1: "Whirlwind"},
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.skill_id == 1
    assert r.skill_name == "Whirlwind"
    assert r.total_damage == 500
    assert r.total_healing == 200
    assert r.total_buff_removal == 100
    assert r.hit_count == 3


# ---------------------------------------------------------------------------
# Multi-skill split
# ---------------------------------------------------------------------------


def test_two_skills_split_by_skill_id() -> None:
    """Two skills get independent roll-ups; sort by -total_damage."""
    rows = SkillUsageAggregator().aggregate(
        [
            _damage(0, src=10, dst=20, value=1_000, skill_id=1),
            _damage(1, src=11, dst=20, value=500, skill_id=2),
        ],
        [_heal(2, src=11, dst=30, value=300, skill_id=2)],
        [],
        {1: "Whirlwind", 2: "Burning"},
    )
    assert len(rows) == 2
    assert [r.skill_id for r in rows] == [1, 2]
    r1, r2 = rows
    assert r1.total_damage == 1_000
    assert r1.hit_count == 1
    assert r2.total_damage == 500
    assert r2.total_healing == 300
    assert r2.hit_count == 2


def test_dual_emit_lands_on_same_skill_row() -> None:
    """A skill that dual-emits (heal + strip from the same cbtevent) is one row.

    The Phase 8 parser yields BOTH a ``HealingEvent`` AND a
    ``BuffRemovalEvent`` from the same record (corrupting /
    confusion). Both events carry the same ``skill_id``, so the
    aggregator folds them into one row with both totals populated.
    """
    rows = SkillUsageAggregator().aggregate(
        [],
        [_heal(0, src=10, dst=20, value=200, skill_id=1)],
        [_strip(0, src=10, dst=20, value=150, skill_id=1)],
        {1: "Mimic"},
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.skill_id == 1
    assert r.skill_name == "Mimic"
    assert r.total_healing == 200
    assert r.total_buff_removal == 150
    assert r.total_damage == 0
    assert r.hit_count == 2


# ---------------------------------------------------------------------------
# Unknown skill_id + name lookup
# ---------------------------------------------------------------------------


def test_unknown_skill_id_renders_empty_name() -> None:
    """An event with ``skill_id`` not in the map renders ``skill_name=""``."""
    rows = SkillUsageAggregator().aggregate(
        [_damage(0, src=10, dst=20, value=200, skill_id=99)],
        [],
        [],
        {1: "Whirlwind"},
    )
    assert len(rows) == 1
    assert rows[0].skill_id == 99
    assert rows[0].skill_name == ""


# ---------------------------------------------------------------------------
# Ordering + frozen
# ---------------------------------------------------------------------------


def test_deterministic_ordering_by_total_damage_desc() -> None:
    """Sort is stable; ties broken by ascending ``skill_id``."""
    rows = SkillUsageAggregator().aggregate(
        [
            _damage(0, src=10, dst=20, value=300, skill_id=2),
            _damage(1, src=11, dst=20, value=300, skill_id=1),
            _damage(2, src=12, dst=20, value=1_000, skill_id=3),
        ],
        [],
        [],
        {1: "A", 2: "B", 3: "C"},
    )
    # 1000-damage row first; tie at 300 broken by ascending skill_id.
    assert [r.skill_id for r in rows] == [3, 1, 2]


def test_row_is_frozen_pydantic() -> None:
    """Mutating a returned row is rejected (``frozen=True``)."""
    rows = SkillUsageAggregator().aggregate(
        [_damage(0, src=10, dst=20, value=100, skill_id=1)],
        [],
        [],
        {1: "Whirlwind"},
    )
    r = rows[0]
    with pytest.raises((TypeError, ValueError, AttributeError)):
        r.total_damage = 999  # type: ignore[misc]
