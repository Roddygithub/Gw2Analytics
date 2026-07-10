"""Plan 084 tests for :class:`PerTargetRollupBase`.

The base class factors the shared accumulate / rate / sort / invariant
logic out of the 3 per-target aggregators (DPS / HPS / BPS). These tests
exercise the base directly via a synthetic subclass (the invariant guards
that ``aggregate()`` can never trip because it always sorts correctly),
plus a cross-check that the 3 real subclasses still round-trip identically
after the refactor. The pre-existing ``test_target_dps`` /
``test_target_healing`` / ``test_target_buff_removal`` suites remain the
per-module regression contract.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._per_target_base import PerTargetRollupBase, PerTargetRollupSpec
from gw2_analytics.target_buff_removal import TargetBuffRemovalAggregator
from gw2_analytics.target_dps import TargetDpsAggregator
from gw2_analytics.target_healing import TargetHealingAggregator
from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent


class _FakeRow(BaseModel):
    """Synthetic per-target row mirroring the real trio's shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent_id: int = Field(..., ge=0)
    total_x: int = Field(..., ge=0)
    x_count: int = Field(..., ge=1)
    xps: float = Field(..., ge=0.0)
    name: str | None = None


@dataclass
class _FakeEvent:
    """Synthetic event with the two attributes the base reads."""

    target_agent_id: int
    x: int


_FAKE_SPEC = PerTargetRollupSpec(
    event_attr="x",
    total_field="total_x",
    count_field="x_count",
    rate_field="xps",
)


class _FakeAggregator(PerTargetRollupBase[_FakeEvent, _FakeRow]):
    def __init__(self) -> None:
        super().__init__(_FAKE_SPEC, _FakeRow)


def _row(target: int, total: int, count: int = 1) -> _FakeRow:
    return _FakeRow(target_agent_id=target, total_x=total, x_count=count, xps=0.0)


class TestPerTargetRollupBaseInvariants:
    """Direct exercise of the invariant guards (bypassing the sort)."""

    def test_empty_rows_do_not_raise(self) -> None:
        _FakeAggregator()._check_invariants([], 0)

    def test_single_row_matching_sum_passes(self) -> None:
        _FakeAggregator()._check_invariants([_row(7, 100)], 100)

    def test_multi_row_correct_order_passes(self) -> None:
        rows = [_row(3, 200), _row(5, 200), _row(8, 100)]
        _FakeAggregator()._check_invariants(rows, 500)

    def test_sum_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match=r"sum of row\.total_x"):
            _FakeAggregator()._check_invariants([_row(7, 100)], 999)

    def test_wrong_total_order_raises(self) -> None:
        # Ascending total instead of descending.
        rows = [_row(1, 100), _row(2, 200)]
        with pytest.raises(ValueError, match="not ordered"):
            _FakeAggregator()._check_invariants(rows, 300)

    def test_tie_not_broken_by_target_asc_raises(self) -> None:
        # Equal totals, but target ids are descending (5 then 3).
        rows = [_row(5, 200), _row(3, 200)]
        with pytest.raises(ValueError, match="tie on total_x"):
            _FakeAggregator()._check_invariants(rows, 400)

    def test_count_below_one_raises(self) -> None:
        # ``x_count`` has ``ge=1`` at the schema layer; bypass validation
        # via ``model_construct`` to feed the base a degenerate row and
        # confirm the base's own count guard (independent of Pydantic)
        # fires.
        forged = _FakeRow.model_construct(target_agent_id=7, total_x=100, x_count=0, xps=0.0)
        with pytest.raises(ValueError, match="must be >= 1"):
            _FakeAggregator()._check_invariants([forged], 100)


class TestSpecValidation:
    """The base rejects a spec whose slugs do not match the row schema."""

    def test_bad_slug_fails_at_construction(self) -> None:
        bad_spec = PerTargetRollupSpec(
            event_attr="x",
            total_field="does_not_exist",  # typo -> not a _FakeRow field
            count_field="x_count",
            rate_field="xps",
        )
        with pytest.raises(ValueError, match="missing spec field"):
            PerTargetRollupBase(bad_spec, _FakeRow)

    def test_valid_slugs_construct_cleanly(self) -> None:
        # The real specs must pass the construction guard.
        assert TargetDpsAggregator() is not None
        assert TargetHealingAggregator() is not None
        assert TargetBuffRemovalAggregator() is not None


class TestConcreteSubclassesAfterRefactor:
    """The 3 real subclasses still behave identically post-refactor."""

    def test_dps_empty_input(self) -> None:
        assert TargetDpsAggregator().aggregate([], duration_s=10.0) == []

    def test_dps_rate_math_unchanged(self) -> None:
        rows = TargetDpsAggregator().aggregate(
            [
                DamageEvent(
                    time_ms=0,
                    source_agent_id=1,
                    target_agent_id=7,
                    skill_id=42,
                    damage=100,
                )
            ],
            duration_s=2.0,
        )
        assert len(rows) == 1
        assert rows[0].total_damage == 100
        assert rows[0].dps == 50.0  # 100 / 2.0

    def test_three_subclasses_share_behaviour_on_parallel_fixtures(self) -> None:
        # Same target/value shape across the 3 event types -> identical
        # ordering + totals + rate, modulo the per-module field names.
        dps = TargetDpsAggregator().aggregate(
            [
                DamageEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=5, skill_id=1, damage=200
                ),
                DamageEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=3, skill_id=1, damage=200
                ),
                DamageEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=8, skill_id=1, damage=100
                ),
            ],
            duration_s=10.0,
        )
        hps = TargetHealingAggregator().aggregate(
            [
                HealingEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=5, skill_id=1, healing=200
                ),
                HealingEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=3, skill_id=1, healing=200
                ),
                HealingEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=8, skill_id=1, healing=100
                ),
            ],
            duration_s=10.0,
        )
        bps = TargetBuffRemovalAggregator().aggregate(
            [
                BuffRemovalEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=5, skill_id=1, buff_removal=200
                ),
                BuffRemovalEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=3, skill_id=1, buff_removal=200
                ),
                BuffRemovalEvent(
                    time_ms=0, source_agent_id=1, target_agent_id=8, skill_id=1, buff_removal=100
                ),
            ],
            duration_s=10.0,
        )
        # Identical ordering (tie 200 broken by target asc: 3, 5, then 8).
        assert [r.target_agent_id for r in dps] == [3, 5, 8]
        assert [r.target_agent_id for r in hps] == [3, 5, 8]
        assert [r.target_agent_id for r in bps] == [3, 5, 8]
        # Identical totals + rate across the trio.
        assert [r.total_damage for r in dps] == [200, 200, 100]
        assert [r.total_healing for r in hps] == [200, 200, 100]
        assert [r.total_buff_removal for r in bps] == [200, 200, 100]
        assert [r.dps for r in dps] == [r.hps for r in hps] == [r.bps for r in bps]
