"""Wave 4 / Tour 5 tests for :class:`PlayerDefenseAggregator`.

The Defense aggregator groups damage + CC + death events by the
receiving/dying player. The defense-tracking columns (dodges /
blocks / interrupts / barrier_absorbed / time_downed_ms) are
live since v0.12.0-v0.12.3 and receive real data when their
respective events are present in the stream.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.player_defense import PlayerDefenseAggregator, PlayerDefenseRow
from gw2_core import (
    BlockEvent,
    CCEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    InterruptEvent,
)


def _damage(
    target: int,
    damage: int,
    time_ms: int = 0,
    source: int = 1,
) -> DamageEvent:
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=42,
        damage=damage,
    )


def _cc(
    target: int,
    cc_value: int,
    time_ms: int = 0,
    source: int = 1,
) -> CCEvent:
    return CCEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=44,
        cc_value=cc_value,
    )


def _death(
    source: int,
    time_ms: int = 0,
) -> DeathEvent:
    return DeathEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=0,
        skill_id=0,
    )


def _dodge(
    source: int,
    time_ms: int = 0,
) -> DodgeEvent:
    return DodgeEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=0,
        skill_id=0,
    )


def _block(
    source: int,
    time_ms: int = 0,
) -> BlockEvent:
    return BlockEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=0,
        skill_id=0,
    )


def _interrupt(
    source: int,
    target: int = 0,
    time_ms: int = 0,
) -> InterruptEvent:
    return InterruptEvent(
        time_ms=time_ms,
        source_agent_id=source,
        target_agent_id=target,
        skill_id=44,
    )


class TestPlayerDefenseAggregator:
    """Combat readout Defense contract for :class:`PlayerDefenseAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        rows = PlayerDefenseAggregator().aggregate([], [], [])
        assert rows == []

    def test_damage_only(self) -> None:
        rows = PlayerDefenseAggregator().aggregate(
            [_damage(target=7, damage=100)],
            [],
            [],
        )
        assert len(rows) == 1
        assert rows[0].agent_id == 7
        assert rows[0].damage_taken == 100
        assert rows[0].cc_taken == 0
        assert rows[0].deaths == 0
        # Stub columns stay at 0 in the legacy (no-events) path.
        assert rows[0].dodges == 0
        assert rows[0].blocks == 0
        assert rows[0].interrupts == 0
        assert rows[0].barrier_absorbed == 0
        assert rows[0].time_downed_ms == 0

    def test_cc_and_death_sum(self) -> None:
        rows = PlayerDefenseAggregator().aggregate(
            [_damage(target=7, damage=50)],
            [_cc(target=7, cc_value=3), _cc(target=7, cc_value=4)],
            [_death(source=7)],
        )
        assert len(rows) == 1
        assert rows[0].damage_taken == 50
        assert rows[0].cc_taken == 7
        assert rows[0].deaths == 1

    def test_deterministic_ordering_damage_desc_agent_asc(self) -> None:
        rows = PlayerDefenseAggregator().aggregate(
            [
                _damage(target=5, damage=200),
                _damage(target=3, damage=200),
                _damage(target=8, damage=100),
            ],
            [],
            [],
        )
        assert [r.agent_id for r in rows] == [3, 5, 8]
        assert [r.damage_taken for r in rows] == [200, 200, 100]

    def test_cross_field_sum_invariant(self) -> None:
        rows = PlayerDefenseAggregator().aggregate(
            [
                _damage(target=1, damage=50),
                _damage(target=2, damage=200),
                _damage(target=1, damage=150),
            ],
            [],
            [],
        )
        assert sum(r.damage_taken for r in rows) == 400
        assert rows[0].agent_id == 1
        assert rows[0].damage_taken == 200
        assert rows[1].agent_id == 2
        assert rows[1].damage_taken == 200

    def test_name_map_resolves_to_player_name(self) -> None:
        rows = PlayerDefenseAggregator().aggregate(
            [_damage(target=7, damage=200)],
            [],
            [],
            name_map={7: "Tank", 9: None},
        )
        assert rows[0].name == "Tank"

    def test_model_is_frozen_pydantic(self) -> None:
        row = PlayerDefenseRow(
            agent_id=1,
            damage_taken=100,
            cc_taken=0,
            deaths=0,
        )
        with pytest.raises(ValidationError):
            row.agent_id = 999  # type: ignore[misc]

    def test_check_invariants_raises_on_sum_mismatch(self) -> None:
        rows = [
            PlayerDefenseRow.model_construct(agent_id=1, damage_taken=100, cc_taken=0, deaths=0),
        ]
        with pytest.raises(ValueError, match=r"sum of row\.damage_taken"):
            PlayerDefenseAggregator._check_invariants(
                rows, expected_damage_total=200, expected_barrier_total=0
            )

    def test_check_invariants_raises_on_barrier_exceeds_damage(self) -> None:
        rows = [
            PlayerDefenseRow.model_construct(
                agent_id=1, damage_taken=50, cc_taken=0, deaths=0, barrier_absorbed=100
            ),
        ]
        with pytest.raises(ValueError, match=r"barrier_absorbed.*>.*damage_taken"):
            PlayerDefenseAggregator._check_invariants(
                rows, expected_damage_total=50, expected_barrier_total=100
            )

    def test_check_invariants_raises_on_wrong_ordering(self) -> None:
        rows = [
            PlayerDefenseRow.model_construct(agent_id=1, damage_taken=100, cc_taken=0, deaths=0),
            PlayerDefenseRow.model_construct(agent_id=2, damage_taken=200, cc_taken=0, deaths=0),
        ]
        with pytest.raises(ValueError, match=r"not ordered by"):
            PlayerDefenseAggregator._check_invariants(
                rows, expected_damage_total=300, expected_barrier_total=0
            )

    def test_check_invariants_raises_on_tie_not_broken(self) -> None:
        rows = [
            PlayerDefenseRow.model_construct(agent_id=2, damage_taken=100, cc_taken=0, deaths=0),
            PlayerDefenseRow.model_construct(agent_id=1, damage_taken=100, cc_taken=0, deaths=0),
        ]
        with pytest.raises(ValueError, match=r"tie on damage_taken"):
            PlayerDefenseAggregator._check_invariants(
                rows, expected_damage_total=200, expected_barrier_total=0
            )

    def test_dodge_block_interrupt_events(self) -> None:
        """Wave 5: dodge/block/interrupt events fill their stub columns."""
        rows = PlayerDefenseAggregator().aggregate(
            [],
            [],
            [],
            dodge_events=[_dodge(source=7), _dodge(source=7)],
            block_events=[_block(source=7)],
            interrupt_events=[_interrupt(source=7, target=9)],
        )
        assert len(rows) == 1
        assert rows[0].agent_id == 7
        assert rows[0].dodges == 2
        assert rows[0].blocks == 1
        assert rows[0].interrupts == 1

    def test_barrier_portion_getter(self) -> None:
        """Phase 6 v2 hook: a custom barrier getter fills barrier_absorbed."""

        def barrier(event: DamageEvent) -> int:
            return event.damage // 2

        rows = PlayerDefenseAggregator().aggregate(
            [_damage(target=7, damage=100)],
            [],
            [],
            barrier_portion_getter=barrier,
        )
        assert len(rows) == 1
        assert rows[0].damage_taken == 100
        assert rows[0].barrier_absorbed == 50
