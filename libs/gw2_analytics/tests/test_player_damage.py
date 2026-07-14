"""Wave 3 / Tour 5 tests for :class:`PlayerDamageAggregator`.

Strict parallel of :mod:`test_target_dps` with the grouping axis
flipped from ``target_agent_id`` to ``source_agent_id``. The
per-player Damage aggregator is part of the Combat readout trio
(Damage + Heal + Boons).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.player_damage import PlayerDamageAggregator, PlayerDamageRow
from gw2_core import DamageEvent


def _damage(
    source: int,
    damage: int,
    time_ms: int = 0,
    target: int = 1,
) -> DamageEvent:
    """Convenience factory for a damage event dealt by ``source``."""
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=42,
        damage=damage,
    )


class TestPlayerDamageAggregator:
    """Combat readout Damage contract for :class:`PlayerDamageAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = PlayerDamageAggregator().aggregate([], duration_s=10.0)
        assert rows == []

    def test_single_event_yields_one_row(self) -> None:
        rows = PlayerDamageAggregator().aggregate(
            [_damage(source=7, damage=100)],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].source_agent_id == 7
        assert rows[0].total_damage == 100
        assert rows[0].attack_count == 1
        assert rows[0].dps == 10.0
        # SCAFFOLD split: pre-Phase-6-v2 streams return dps_power=0.0, dps_condi=0.0
        # (wire-shape-fidelity default: both columns stay at 0 until Phase 6 v2).
        assert rows[0].dps_power == 0.0
        assert rows[0].dps_condi == 0.0

    def test_zero_and_negative_duration(self) -> None:
        rows = PlayerDamageAggregator().aggregate(
            [_damage(source=7, damage=100)],
            duration_s=0.0,
        )
        assert rows[0].dps == 0.0
        assert rows[0].total_damage == 100

        with pytest.raises(ValueError, match="duration_s must be >= 0"):
            PlayerDamageAggregator().aggregate(
                [_damage(source=7, damage=100)],
                duration_s=-1.0,
            )

    def test_deterministic_ordering_damage_desc_source_asc(self) -> None:
        rows = PlayerDamageAggregator().aggregate(
            [
                _damage(source=5, damage=200),
                _damage(source=3, damage=200),
                _damage(source=8, damage=100),
            ],
            duration_s=10.0,
        )
        assert [r.source_agent_id for r in rows] == [3, 5, 8]
        assert [r.total_damage for r in rows] == [200, 200, 100]

    def test_cross_field_sum_invariant(self) -> None:
        rows = PlayerDamageAggregator().aggregate(
            [
                _damage(source=1, damage=50),
                _damage(source=2, damage=200),
                _damage(source=1, damage=150),
            ],
            duration_s=5.0,
        )
        assert sum(r.total_damage for r in rows) == 400
        assert rows[0].source_agent_id == 1
        assert rows[0].total_damage == 200
        assert rows[0].attack_count == 2
        assert rows[0].dps == 40.0
        assert rows[1].source_agent_id == 2
        assert rows[1].total_damage == 200
        assert rows[1].attack_count == 1
        assert rows[1].dps == 40.0

    def test_name_map_resolves_to_player_name(self) -> None:
        rows = PlayerDamageAggregator().aggregate(
            [
                _damage(source=7, damage=200),
                _damage(source=9, damage=100),
            ],
            duration_s=10.0,
            name_map={7: "DPSer", 9: None},
        )
        by_source = {r.source_agent_id: r for r in rows}
        assert by_source[7].name == "DPSer"
        assert by_source[9].name is None

    def test_model_is_frozen_pydantic(self) -> None:
        row = PlayerDamageRow(
            source_agent_id=1,
            total_damage=100,
            attack_count=2,
            dps=10.0,
        )
        with pytest.raises(ValidationError):
            row.source_agent_id = 999  # type: ignore[misc]

    def test_check_invariants_raises_on_sum_mismatch(self) -> None:
        rows = [
            PlayerDamageRow.model_construct(
                source_agent_id=1, total_damage=100, attack_count=1, dps=10.0
            ),
        ]
        with pytest.raises(ValueError, match=r"sum of row\.total_damage"):
            PlayerDamageAggregator._check_invariants(rows, expected_sum=200, duration_s=10.0)

    def test_check_invariants_raises_on_attack_count_below_one(self) -> None:
        rows = [
            PlayerDamageRow.model_construct(
                source_agent_id=1, total_damage=100, attack_count=0, dps=10.0
            ),
        ]
        with pytest.raises(ValueError, match=r"attack_count.*must be >= 1"):
            PlayerDamageAggregator._check_invariants(rows, expected_sum=100, duration_s=10.0)

    def test_check_invariants_raises_on_wrong_ordering(self) -> None:
        rows = [
            PlayerDamageRow.model_construct(
                source_agent_id=1, total_damage=100, attack_count=1, dps=10.0
            ),
            PlayerDamageRow.model_construct(
                source_agent_id=2, total_damage=200, attack_count=1, dps=20.0
            ),
        ]
        with pytest.raises(ValueError, match=r"not ordered by"):
            PlayerDamageAggregator._check_invariants(rows, expected_sum=300, duration_s=10.0)

    def test_check_invariants_raises_on_tie_not_broken(self) -> None:
        rows = [
            PlayerDamageRow.model_construct(
                source_agent_id=2, total_damage=100, attack_count=1, dps=10.0
            ),
            PlayerDamageRow.model_construct(
                source_agent_id=1, total_damage=100, attack_count=1, dps=10.0
            ),
        ]
        with pytest.raises(ValueError, match=r"tie on total_damage"):
            PlayerDamageAggregator._check_invariants(rows, expected_sum=200, duration_s=10.0)
