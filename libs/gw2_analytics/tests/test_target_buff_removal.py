"""Phase 8 tests for :class:`TargetBuffRemovalAggregator`.

Six tests locking the Phase 8 contract mirror-for-mirror with
:class:`TargetDpsAggregator` and :class:`TargetHealingAggregator`:
empty input, single-row shape, zero / negative duration edge,
deterministic ordering (buff_removal desc + target id asc on tie),
cross-field invariant (sum preservation), and the frozen-Pydantic
schema guarantee. The three suites MUST stay parallel in shape --
the schema parity between :class:`TargetDpsRow` /
:class:`TargetHealingRow` / :class:`TargetBuffRemovalRow` is the
documented invariant of Phase 7 v1 / Phase 8.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.target_buff_removal import (
    TargetBuffRemovalAggregator,
    TargetBuffRemovalRow,
)
from gw2_core import BuffRemovalEvent


def _strip(
    target: int,
    buff_removal: int,
    time_ms: int = 0,
    source: int = 1,
) -> BuffRemovalEvent:
    """Convenience factory for a buff-removal event targeting ``target``."""
    return BuffRemovalEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=43,
        buff_removal=buff_removal,
    )


class TestTargetBuffRemovalAggregator:
    """Phase 8 contract matrix for :class:`TargetBuffRemovalAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = TargetBuffRemovalAggregator().aggregate([], duration_s=10.0)
        assert rows == []

    def test_single_event_yields_one_row(self) -> None:
        rows = TargetBuffRemovalAggregator().aggregate(
            [_strip(target=7, buff_removal=120)],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].target_agent_id == 7
        assert rows[0].total_buff_removal == 120
        assert rows[0].strip_count == 1
        assert rows[0].bps == 12.0

    def test_zero_and_negative_duration_yields_zero_bps(self) -> None:
        # Zero duration collapses to bps=0.0 (sentinel).
        rows = TargetBuffRemovalAggregator().aggregate(
            [_strip(target=7, buff_removal=120)],
            duration_s=0.0,
        )
        assert rows[0].bps == 0.0
        assert rows[0].total_buff_removal == 120

        # Negative duration is a hard error -- unbounded negative
        # would produce negative BPS rows, which is meaningless.
        with pytest.raises(ValueError, match="duration_s must be >= 0"):
            TargetBuffRemovalAggregator().aggregate(
                [_strip(target=7, buff_removal=120)],
                duration_s=-1.0,
            )

    def test_deterministic_ordering_buff_removal_desc_target_asc(self) -> None:
        rows = TargetBuffRemovalAggregator().aggregate(
            [
                _strip(target=5, buff_removal=300),  # tied highest
                _strip(target=3, buff_removal=300),  # tied -> lower id first
                _strip(target=8, buff_removal=150),  # lowest
            ],
            duration_s=10.0,
        )
        assert [r.target_agent_id for r in rows] == [3, 5, 8]
        assert [r.total_buff_removal for r in rows] == [300, 300, 150]

    def test_cross_field_sum_invariant(self) -> None:
        rows = TargetBuffRemovalAggregator().aggregate(
            [
                _strip(target=1, buff_removal=75),
                _strip(target=2, buff_removal=250),
                _strip(target=1, buff_removal=175),
            ],
            duration_s=5.0,
        )
        # Sum preservation: 75 + 250 + 175 == 500
        assert sum(r.total_buff_removal for r in rows) == 500
        # Per-target roll-ups. BPS at duration=5.0: 250/5 = 50.0 for both.
        assert rows[0].target_agent_id == 1  # tie on buff_removal -> lower id first
        assert rows[0].total_buff_removal == 250
        assert rows[0].strip_count == 2
        assert rows[0].bps == 50.0
        assert rows[1].target_agent_id == 2
        assert rows[1].total_buff_removal == 250
        assert rows[1].strip_count == 1
        assert rows[1].bps == 50.0

    def test_model_is_frozen_pydantic(self) -> None:
        row = TargetBuffRemovalRow(
            target_agent_id=1,
            total_buff_removal=120,
            strip_count=2,
            bps=12.0,
        )
        # ``frozen=True`` raises ``ValidationError`` (Pydantic v2) on
        # mutation via ``__setattr__``; the type checker disallows the
        # line syntactically but the runtime guard fires anyway.
        with pytest.raises(ValidationError):
            row.target_agent_id = 999  # type: ignore[misc]

    def test_name_default_is_none_when_no_map(self) -> None:
        """v0.8.3: strict parallel of the DPS + Healing aggregators.
        When ``name_map`` is not passed, every row's ``name`` is
        ``None`` (no name invented out of thin air).
        """
        rows = TargetBuffRemovalAggregator().aggregate(
            [_strip(target=7, buff_removal=120)],
            duration_s=10.0,
        )
        assert rows[0].name is None

    def test_name_map_resolves_to_player_name(self) -> None:
        """v0.8.3: strict parallel of the DPS + Healing counterparts.
        The name_map is denormalised onto each row so the wire
        consumer doesn't need a second lookup.
        """
        rows = TargetBuffRemovalAggregator().aggregate(
            [
                _strip(target=7, buff_removal=200),
                _strip(target=9, buff_removal=100),
            ],
            duration_s=10.0,
            name_map={7: "HealBrand", 9: None},
        )
        by_target = {r.target_agent_id: r for r in rows}
        assert by_target[7].name == "HealBrand"
        assert by_target[9].name is None

