"""Phase 6 tests for :class:`TargetDpsAggregator`.

Six tests locking the Phase 6 v1 contract: empty input, single-row
shape, zero / negative duration edge, deterministic ordering (damage
desc + target id asc on tie), cross-field invariant (sum
preservation), and the frozen-Pydantic schema guarantee.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.target_dps import TargetDpsAggregator, TargetDpsRow
from gw2_core import DamageEvent


def _damage(
    target: int,
    damage: int,
    time_ms: int = 0,
    source: int = 1,
) -> DamageEvent:
    """Convenience factory for a damage event against ``target``."""
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=42,
        damage=damage,
    )


class TestTargetDpsAggregator:
    """Phase 6 v1 contract matrix for :class:`TargetDpsAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = TargetDpsAggregator().aggregate([], duration_s=10.0)
        assert rows == []

    def test_single_event_yields_one_row(self) -> None:
        rows = TargetDpsAggregator().aggregate(
            [_damage(target=7, damage=100)],
            duration_s=10.0,
        )
        assert len(rows) == 1
        assert rows[0].target_agent_id == 7
        assert rows[0].total_damage == 100
        assert rows[0].attack_count == 1
        assert rows[0].dps == 10.0

    def test_zero_and_negative_duration_yields_zero_dps(self) -> None:
        # Zero duration collapses to dps=0.0 (sentinel).
        rows = TargetDpsAggregator().aggregate(
            [_damage(target=7, damage=100)],
            duration_s=0.0,
        )
        assert rows[0].dps == 0.0
        assert rows[0].total_damage == 100

        # Negative duration is a hard error -- unbounded negative
        # would produce negative DPS rows, which is meaningless.
        with pytest.raises(ValueError, match="duration_s must be >= 0"):
            TargetDpsAggregator().aggregate(
                [_damage(target=7, damage=100)],
                duration_s=-1.0,
            )

    def test_deterministic_ordering_damage_desc_target_asc(self) -> None:
        rows = TargetDpsAggregator().aggregate(
            [
                _damage(target=5, damage=200),  # tied highest
                _damage(target=3, damage=200),  # tied -> lower id first
                _damage(target=8, damage=100),  # lowest
            ],
            duration_s=10.0,
        )
        assert [r.target_agent_id for r in rows] == [3, 5, 8]
        assert [r.total_damage for r in rows] == [200, 200, 100]

    def test_cross_field_sum_invariant(self) -> None:
        rows = TargetDpsAggregator().aggregate(
            [
                _damage(target=1, damage=50),
                _damage(target=2, damage=200),
                _damage(target=1, damage=150),
            ],
            duration_s=5.0,
        )
        # Sum preservation: 50 + 200 + 150 == 400
        assert sum(r.total_damage for r in rows) == 400
        # Per-target roll-ups. DPS at duration=5.0: 200/5 = 40.0 for both.
        assert rows[0].target_agent_id == 1  # tie on damage -> lower id first
        assert rows[0].total_damage == 200
        assert rows[0].attack_count == 2
        assert rows[0].dps == 40.0
        assert rows[1].target_agent_id == 2
        assert rows[1].total_damage == 200
        assert rows[1].attack_count == 1
        assert rows[1].dps == 40.0

    def test_model_is_frozen_pydantic(self) -> None:
        row = TargetDpsRow(
            target_agent_id=1,
            total_damage=100,
            attack_count=2,
            dps=10.0,
        )
        # ``frozen=True`` raises ``ValidationError`` (Pydantic v2) on
        # mutation via ``__setattr__``; the type checker disallows the
        # line syntactically but the runtime guard fires anyway.
        with pytest.raises(ValidationError):
            row.target_agent_id = 999  # type: ignore[misc]

    def test_name_default_is_none_when_no_map(self) -> None:
        """v0.8.3: when ``name_map`` is not passed (the canonical
        backward-compat case), every row's ``name`` field is ``None`` --
        the aggregator never invents a name out of thin air.
        """
        rows = TargetDpsAggregator().aggregate(
            [_damage(target=7, damage=100)],
            duration_s=10.0,
        )
        assert rows[0].name is None

    def test_name_map_resolves_to_player_name(self) -> None:
        """v0.8.3: when ``name_map`` is passed, every row's ``name``
        field carries the resolved player name (or ``None`` for
        unresolved ids -- NPCs / missing keys). The map is
        denormalised onto each row so the wire consumer doesn't
        need a second lookup.
        """
        rows = TargetDpsAggregator().aggregate(
            [
                _damage(target=7, damage=200),
                _damage(target=9, damage=100),
            ],
            duration_s=10.0,
            name_map={7: "HealBrand", 9: None},  # 9 is an NPC (explicit None)
        )
        by_target = {r.target_agent_id: r for r in rows}
        assert by_target[7].name == "HealBrand"
        assert by_target[9].name is None  # explicit None -> unresolved sentinel

    def test_name_map_missing_key_yields_none(self) -> None:
        """v0.8.3: an agent id not present in the map surfaces as
        ``name=None`` (same as explicit ``None`` -- the
        ``dict.get`` semantic collapses the two cases). The wire
        consumer cannot distinguish "NPC" from "missing key" but
        the analyst-facing fallback is the same: bare
        ``target_agent_id``.
        """
        rows = TargetDpsAggregator().aggregate(
            [_damage(target=42, damage=100)],
            duration_s=10.0,
            name_map={7: "HealBrand"},  # 42 not in the map
        )
        assert rows[0].name is None

