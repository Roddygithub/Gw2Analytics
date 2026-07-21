"""Wave 3 / Tour 5 tests for :class:`PlayerHealAggregator`.

Strict parallel of :mod:`test_target_healing` with the grouping axis
flipped from ``target_agent_id`` to ``source_agent_id``. The
per-player Heal aggregator is part of the Combat readout trio
(Damage + Heal + Boons).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.player_heal import PlayerHealAggregator, PlayerHealRow
from gw2_core import HealingEvent


def _healing(
    source: int,
    healing: int,
    time_ms: int = 0,
    target: int = 1,
) -> HealingEvent:
    """Convenience factory for a healing event dealt by ``source``."""
    return HealingEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=43,
        healing=healing,
    )


class TestPlayerHealAggregator:
    """Combat readout Heal contract for :class:`PlayerHealAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = PlayerHealAggregator().aggregate([], duration_s=10.0)
        assert rows == []

    def test_single_event_yields_one_row(self) -> None:
        rows = PlayerHealAggregator().aggregate(
            [_healing(source=7, healing=120)],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].source_agent_id == 7
        assert rows[0].total_healing == 120
        assert rows[0].heal_count == 1
        assert rows[0].hps == 12.0
        # Legacy (pre-v0.12.x) streams return barrier_total=0, barrier_ps=0.0.
        assert rows[0].barrier_total == 0
        assert rows[0].barrier_ps == 0.0

    def test_zero_and_negative_duration(self) -> None:
        rows = PlayerHealAggregator().aggregate(
            [_healing(source=7, healing=120)],
            duration_s=0.0,
        )
        assert rows[0].hps == 0.0
        assert rows[0].total_healing == 120

        with pytest.raises(ValueError, match="duration_s must be >= 0"):
            PlayerHealAggregator().aggregate(
                [_healing(source=7, healing=120)],
                duration_s=-1.0,
            )

    def test_deterministic_ordering_healing_desc_source_asc(self) -> None:
        rows = PlayerHealAggregator().aggregate(
            [
                _healing(source=5, healing=300),
                _healing(source=3, healing=300),
                _healing(source=8, healing=150),
            ],
            duration_s=10.0,
        )
        assert [r.source_agent_id for r in rows] == [3, 5, 8]
        assert [r.total_healing for r in rows] == [300, 300, 150]

    def test_cross_field_sum_invariant(self) -> None:
        rows = PlayerHealAggregator().aggregate(
            [
                _healing(source=1, healing=75),
                _healing(source=2, healing=250),
                _healing(source=1, healing=175),
            ],
            duration_s=5.0,
        )
        assert sum(r.total_healing for r in rows) == 500
        assert rows[0].source_agent_id == 1
        assert rows[0].total_healing == 250
        assert rows[0].heal_count == 2
        assert rows[0].hps == 50.0
        assert rows[1].source_agent_id == 2
        assert rows[1].total_healing == 250
        assert rows[1].heal_count == 1
        assert rows[1].hps == 50.0

    def test_name_map_resolves_to_player_name(self) -> None:
        rows = PlayerHealAggregator().aggregate(
            [
                _healing(source=7, healing=200),
                _healing(source=9, healing=100),
            ],
            duration_s=10.0,
            name_map={7: "HealBrand", 9: None},
        )
        by_source = {r.source_agent_id: r for r in rows}
        assert by_source[7].name == "HealBrand"
        assert by_source[9].name is None

    def test_model_is_frozen_pydantic(self) -> None:
        row = PlayerHealRow(
            source_agent_id=1,
            total_healing=120,
            heal_count=2,
            hps=12.0,
        )
        with pytest.raises(ValidationError):
            row.source_agent_id = 999  # type: ignore[misc]

    def test_check_invariants_raises_on_sum_mismatch(self) -> None:
        rows = [
            PlayerHealRow.model_construct(
                source_agent_id=1, total_healing=100, heal_count=1, hps=10.0
            ),
        ]
        with pytest.raises(ValueError, match=r"sum of row\.total_healing"):
            PlayerHealAggregator._check_invariants(
                rows, expected_sum=200, duration_s=10.0, expected_stun_break_total=0
            )

    def test_check_invariants_raises_on_heal_count_below_one(self) -> None:
        rows = [
            PlayerHealRow.model_construct(
                source_agent_id=1, total_healing=100, heal_count=0, hps=10.0
            ),
        ]
        with pytest.raises(ValueError, match=r"heal_count.*must be >= 1"):
            PlayerHealAggregator._check_invariants(
                rows, expected_sum=100, duration_s=10.0, expected_stun_break_total=0
            )

    def test_check_invariants_raises_on_wrong_ordering(self) -> None:
        rows = [
            PlayerHealRow.model_construct(
                source_agent_id=1, total_healing=100, heal_count=1, hps=10.0
            ),
            PlayerHealRow.model_construct(
                source_agent_id=2, total_healing=200, heal_count=1, hps=20.0
            ),
        ]
        with pytest.raises(ValueError, match=r"not ordered by"):
            PlayerHealAggregator._check_invariants(
                rows, expected_sum=300, duration_s=10.0, expected_stun_break_total=0
            )

    def test_check_invariants_raises_on_tie_not_broken(self) -> None:
        rows = [
            PlayerHealRow.model_construct(
                source_agent_id=2, total_healing=100, heal_count=1, hps=10.0
            ),
            PlayerHealRow.model_construct(
                source_agent_id=1, total_healing=100, heal_count=1, hps=10.0
            ),
        ]
        with pytest.raises(ValueError, match=r"tie on total_healing"):
            PlayerHealAggregator._check_invariants(
                rows, expected_sum=200, duration_s=10.0, expected_stun_break_total=0
            )

    def test_custom_barrier_portion_getter(self) -> None:
        """Phase 6 v2 hook: a custom barrier getter carves barrier from heals."""

        def barrier(event: HealingEvent) -> int:
            return event.healing // 4

        rows = PlayerHealAggregator().aggregate(
            [_healing(source=7, healing=120)],
            duration_s=10.0,
            barrier_portion_getter=barrier,
        )
        assert rows[0].hps == 12.0
        assert rows[0].barrier_total == 30
        assert rows[0].barrier_ps == 3.0
