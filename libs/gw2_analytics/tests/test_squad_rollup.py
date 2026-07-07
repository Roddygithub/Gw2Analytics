"""Tests for :mod:`gw2_analytics.squad_rollup`.

Sister suite to ``test_target_healing.py``. Mirrors the in-place
``DamageEvent`` / ``HealingEvent`` / ``BuffRemovalEvent`` construction
pattern so we are not dependent on the EVTC binary parser's edge-case
coverage -- the :class:`SquadRollupAggregator` is fed synthetic event
inputs.

Invariants locked down here:

- every cross-field contract listed on
  :class:`gw2_analytics.squad_rollup.SquadRollupAggregator`
- deterministic ordering: highest ``total_damage`` first, ties
  broken by ascending ``subgroup``
- source-side roll-up (event's ``source_agent_id`` -> subgroup)
- empty-string subgroup is a valid label
- unknown ``source_agent_id`` lands in the empty-string bucket
- the returned row is immutable (frozen pydantic model)
- ``duration_s < 0`` is rejected
- rate = 0.0 when ``duration_s == 0``
"""

from __future__ import annotations

import pytest

from gw2_analytics.squad_rollup import SquadRollupAggregator
from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent


def _damage(
    time_ms: int,
    src: int,
    dst: int,
    value: int,
    skill_id: int = 1,
) -> DamageEvent:
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill_id,
        damage=value,
    )


def _heal(
    time_ms: int,
    src: int,
    dst: int,
    value: int,
    skill_id: int = 2,
) -> HealingEvent:
    return HealingEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill_id,
        healing=value,
    )


def _strip(
    time_ms: int,
    src: int,
    dst: int,
    value: int,
    skill_id: int = 3,
) -> BuffRemovalEvent:
    return BuffRemovalEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=dst,
        skill_id=skill_id,
        buff_removal=value,
    )


# ---------------------------------------------------------------------------
# Empty + single-squad cases
# ---------------------------------------------------------------------------


def test_empty_input_yields_no_rows() -> None:
    """Empty input + empty map -> ``[]`` (no synthesised rows)."""
    rows = SquadRollupAggregator().aggregate([], [], [], {}, 10.0)
    assert rows == []


def test_single_squad_damage_heal_strip() -> None:
    """One squad, three event kinds, all in one row."""
    rows = SquadRollupAggregator().aggregate(
        [_damage(0, src=10, dst=20, value=500)],
        [_heal(1, src=10, dst=30, value=200)],
        [_strip(2, src=10, dst=40, value=100)],
        {10: "Squad-1"},
        5.0,
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.subgroup == "Squad-1"
    assert r.total_damage == 500
    assert r.total_healing == 200
    assert r.total_buff_removal == 100
    assert r.hit_count == 3
    assert r.dps == pytest.approx(100.0)
    assert r.hps == pytest.approx(40.0)
    assert r.bps == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Multi-squad split
# ---------------------------------------------------------------------------


def test_two_squads_split_by_source_agent() -> None:
    """Two squads get independent roll-ups; sort by -total_damage."""
    rows = SquadRollupAggregator().aggregate(
        [
            _damage(0, src=10, dst=20, value=1_000),
            _damage(1, src=11, dst=20, value=500),
        ],
        [_heal(2, src=11, dst=30, value=300)],
        [],
        {10: "Squad-1", 11: "Squad-2"},
        10.0,
    )
    assert len(rows) == 2
    assert [r.subgroup for r in rows] == ["Squad-1", "Squad-2"]
    r1, r2 = rows
    assert r1.total_damage == 1_000
    assert r1.total_healing == 0
    assert r1.hit_count == 1
    assert r2.total_damage == 500
    assert r2.total_healing == 300
    assert r2.hit_count == 2


def test_unknown_source_agent_lands_in_empty_string_bucket() -> None:
    """An event whose source isn't in the map is attributed to ``""``."""
    rows = SquadRollupAggregator().aggregate(
        [_damage(0, src=99, dst=20, value=200)],  # 99 not in map
        [],
        [],
        {10: "Squad-1"},
        5.0,
    )
    assert len(rows) == 1
    assert rows[0].subgroup == ""
    assert rows[0].total_damage == 200


# ---------------------------------------------------------------------------
# Rate computation
# ---------------------------------------------------------------------------


def test_zero_duration_yields_zero_rates() -> None:
    """``duration_s == 0`` collapses every rate to 0.0 (sentinel, not NaN)."""
    rows = SquadRollupAggregator().aggregate(
        [_damage(0, src=10, dst=20, value=500)],
        [_heal(1, src=10, dst=30, value=200)],
        [_strip(2, src=10, dst=40, value=100)],
        {10: "Squad-1"},
        0.0,
    )
    r = rows[0]
    assert r.dps == 0.0
    assert r.hps == 0.0
    assert r.bps == 0.0
    # Totals are still computed (they don't depend on duration).
    assert r.total_damage == 500


def test_negative_duration_raises() -> None:
    """``duration_s < 0`` is rejected at the aggregator boundary."""
    with pytest.raises(ValueError, match="duration_s"):
        SquadRollupAggregator().aggregate([], [], [], {}, -1.0)


# ---------------------------------------------------------------------------
# Ordering + frozen
# ---------------------------------------------------------------------------


def test_deterministic_ordering_by_total_damage_desc() -> None:
    """Sort is stable; ties broken by ascending ``subgroup``."""
    rows = SquadRollupAggregator().aggregate(
        [
            _damage(0, src=10, dst=20, value=300),
            _damage(1, src=11, dst=20, value=300),
            _damage(2, src=12, dst=20, value=1_000),
        ],
        [],
        [],
        {10: "B-Squad", 11: "A-Squad", 12: "C-Squad"},
        10.0,
    )
    # 1000-damage row first; tie at 300 broken by ascending subgroup.
    assert [r.subgroup for r in rows] == ["C-Squad", "A-Squad", "B-Squad"]


def test_row_is_frozen_pydantic() -> None:
    """Mutating a returned row is rejected (``frozen=True``)."""
    rows = SquadRollupAggregator().aggregate(
        [_damage(0, src=10, dst=20, value=100)],
        [],
        [],
        {10: "Squad-1"},
        5.0,
    )
    r = rows[0]
    with pytest.raises((TypeError, ValueError, AttributeError)):
        r.total_damage = 999  # type: ignore[misc]
