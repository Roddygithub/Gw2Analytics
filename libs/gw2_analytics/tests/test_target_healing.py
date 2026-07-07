"""Phase 7 v1 tests for :class:`TargetHealingAggregator`.

Six tests locking the Phase 7 v1 contract mirror-for-mirror with
:class:`TargetDpsAggregator`: empty input, single-row shape, zero /
negative duration edge, deterministic ordering (healing desc +
target id asc on tie), cross-field invariant (sum preservation),
and the frozen-Pydantic schema guarantee. The two suites MUST stay
parallel in shape -- the schema parity between
:class:`TargetDpsRow` and :class:`TargetHealingRow` is the
documented invariant of Phase 7 v1.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.target_healing import TargetHealingAggregator, TargetHealingRow
from gw2_core import HealingEvent


def _healing(
    target: int,
    healing: int,
    time_ms: int = 0,
    source: int = 1,
) -> HealingEvent:
    """Convenience factory for a healing event in favour of ``target``."""
    return HealingEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=43,
        healing=healing,
    )


class TestTargetHealingAggregator:
    """Phase 7 v1 contract matrix for :class:`TargetHealingAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = TargetHealingAggregator().aggregate([], duration_s=10.0)
        assert rows == []

    def test_single_event_yields_one_row(self) -> None:
        rows = TargetHealingAggregator().aggregate(
            [_healing(target=7, healing=120)],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].target_agent_id == 7
        assert rows[0].total_healing == 120
        assert rows[0].heal_count == 1
        assert rows[0].hps == 12.0

    def test_zero_and_negative_duration_yields_zero_hps(self) -> None:
        # Zero duration collapses to hps=0.0 (sentinel).
        rows = TargetHealingAggregator().aggregate(
            [_healing(target=7, healing=120)],
            duration_s=0.0,
        )
        assert rows[0].hps == 0.0
        assert rows[0].total_healing == 120

        # Negative duration is a hard error -- unbounded negative
        # would produce negative HPS rows, which is meaningless.
        with pytest.raises(ValueError, match="duration_s must be >= 0"):
            TargetHealingAggregator().aggregate(
                [_healing(target=7, healing=120)],
                duration_s=-1.0,
            )

    def test_deterministic_ordering_healing_desc_target_asc(self) -> None:
        rows = TargetHealingAggregator().aggregate(
            [
                _healing(target=5, healing=300),  # tied highest
                _healing(target=3, healing=300),  # tied -> lower id first
                _healing(target=8, healing=150),  # lowest
            ],
            duration_s=10.0,
        )
        assert [r.target_agent_id for r in rows] == [3, 5, 8]
        assert [r.total_healing for r in rows] == [300, 300, 150]

    def test_cross_field_sum_invariant(self) -> None:
        rows = TargetHealingAggregator().aggregate(
            [
                _healing(target=1, healing=75),
                _healing(target=2, healing=250),
                _healing(target=1, healing=175),
            ],
            duration_s=5.0,
        )
        # Sum preservation: 75 + 250 + 175 == 500
        assert sum(r.total_healing for r in rows) == 500
        # Per-target roll-ups. HPS at duration=5.0: 250/5 = 50.0 for both.
        assert rows[0].target_agent_id == 1  # tie on healing -> lower id first
        assert rows[0].total_healing == 250
        assert rows[0].heal_count == 2
        assert rows[0].hps == 50.0
        assert rows[1].target_agent_id == 2
        assert rows[1].total_healing == 250
        assert rows[1].heal_count == 1
        assert rows[1].hps == 50.0

    def test_model_is_frozen_pydantic(self) -> None:
        row = TargetHealingRow(
            target_agent_id=1,
            total_healing=120,
            heal_count=2,
            hps=12.0,
        )
        # ``frozen=True`` raises ``ValidationError`` (Pydantic v2) on
        # mutation via ``__setattr__``; the type checker disallows the
        # line syntactically but the runtime guard fires anyway.
        with pytest.raises(ValidationError):
            row.target_agent_id = 999  # type: ignore[misc]

    def test_name_default_is_none_when_no_map(self) -> None:
        """v0.8.3: strict parallel of :meth:`TargetDpsAggregator`'s
        default. When ``name_map`` is not passed, every row's
        ``name`` is ``None`` (no name invented out of thin air).
        """
        rows = TargetHealingAggregator().aggregate(
            [_healing(target=7, healing=120)],
            duration_s=10.0,
        )
        assert rows[0].name is None

    def test_name_map_resolves_to_player_name(self) -> None:
        """v0.8.3: strict parallel of the DPS counterpart. The
        name_map is denormalised onto each row so the wire
        consumer doesn't need a second lookup.
        """
        rows = TargetHealingAggregator().aggregate(
            [
                _healing(target=7, healing=200),
                _healing(target=9, healing=100),
            ],
            duration_s=10.0,
            name_map={7: "HealBrand", 9: None},
        )
        by_target = {r.target_agent_id: r for r in rows}
        assert by_target[7].name == "HealBrand"
        assert by_target[9].name is None
