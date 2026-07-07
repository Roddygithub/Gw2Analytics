"""Phase 6 tests for :class:`EventWindowAggregator`.

Six tests locking the Phase 6 v1 contract: empty input, invalid window
guard, single-event bucket shape, zero-fill across timeline gaps, the
adjacent-bucket contiguity invariant, the frozen-Pydantic schema
guarantee, and the forward-compat event_count accumulator (mixed
damage + healing events in a single bucket count toward event_count
regardless of kind).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.event_window import EventBucket, EventWindowAggregator
from gw2_core import DamageEvent, HealingEvent


def _damage(time_ms: int, damage: int, target: int = 1) -> DamageEvent:
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=99,
        target_agent_id=target,
        skill_id=42,
        damage=damage,
    )


def _healing(time_ms: int, healing: int) -> HealingEvent:
    return HealingEvent(
        time_ms=time_ms,
        source_agent_id=99,
        target_agent_id=1,
        skill_id=43,
        healing=healing,
    )


class TestEventWindowAggregator:
    """Phase 6 v1 contract matrix for :class:`EventWindowAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        buckets = EventWindowAggregator().aggregate([], window_s=1)
        assert buckets == []

    def test_invalid_window_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="window_s must be >= 1"):
            EventWindowAggregator().aggregate([], window_s=0)
        with pytest.raises(ValueError, match="window_s must be >= 1"):
            EventWindowAggregator().aggregate([], window_s=-5)

    def test_single_event_creates_single_bucket(self) -> None:
        buckets = EventWindowAggregator().aggregate(
            [_damage(time_ms=500, damage=200)],
            window_s=1,  # 1-second windows == 1000 ms.
        )
        assert len(buckets) == 1
        assert buckets[0].start_ms == 0
        assert buckets[0].end_ms == 1000
        assert buckets[0].damage_total == 200
        assert buckets[0].healing_total == 0
        assert buckets[0].event_count == 1

    def test_gaps_are_zero_filled(self) -> None:
        # 1-second windows: bucket index = time_ms // 1000.
        # Three observations span bucket 0, leave bucket 1 empty, and
        # land events in bucket 2.
        buckets = EventWindowAggregator().aggregate(
            [
                _damage(time_ms=500, damage=200),  # bucket 0
                _damage(time_ms=2500, damage=100),  # bucket 2
                _healing(time_ms=2500, healing=50),  # bucket 2
            ],
            window_s=1,
        )
        # Three contiguous buckets: 0, 1 (zero-filled), 2.
        assert len(buckets) == 3
        assert buckets[0].damage_total == 200
        assert buckets[0].event_count == 1
        assert buckets[1].damage_total == 0
        assert buckets[1].healing_total == 0
        assert buckets[1].event_count == 0  # zero-filled
        assert buckets[2].damage_total == 100
        assert buckets[2].healing_total == 50
        assert buckets[2].event_count == 2
        # Contiguity invariant at every boundary.
        assert buckets[0].end_ms == buckets[1].start_ms == 1000
        assert buckets[1].end_ms == buckets[2].start_ms == 2000

    def test_cross_bucket_invariant_checks(self) -> None:
        # Total event_count across buckets == len(events).
        buckets = EventWindowAggregator().aggregate(
            [
                _damage(time_ms=500, damage=200),
                _damage(time_ms=5500, damage=100),
            ],
            window_s=1,
        )
        assert sum(b.event_count for b in buckets) == 2
        # First bucket holds the first event. The trailing 5-second
        # gap is zero-filled (4 buckets of zero); the last bucket
        # holds the second event.
        assert buckets[0].event_count == 1
        assert buckets[-1].event_count == 1
        assert len(buckets) == 6  # bucket indices 0..5

    def test_mixed_kinds_count_in_event_count(self) -> None:
        """Lock the forward-compat contract: ``event_count`` accumulates
        every event (damage / healing / future kinds) regardless of
        whether the kind has a damage / healing accounting field.

        Without this test, a future refactor could silently drop the
        per-bucket increment when an event's ``isinstance`` branch
        falls through to ``else``.
        """
        buckets = EventWindowAggregator().aggregate(
            [
                _damage(time_ms=500, damage=200),  # bucket 0, damage
                _healing(time_ms=500, healing=50),  # bucket 0, healing
                _damage(time_ms=550, damage=100),  # bucket 0, damage
            ],
            window_s=1,
        )
        assert len(buckets) == 1
        b = buckets[0]
        assert b.event_count == 3
        assert b.damage_total == 300
        assert b.healing_total == 50

    def test_model_is_frozen_pydantic(self) -> None:
        bucket = EventBucket(
            start_ms=0,
            end_ms=1000,
            damage_total=200,
            healing_total=100,
            event_count=2,
        )
        # ``frozen=True`` triggers a runtime guard on mutation even
        # though the type-checker should reject the line first.
        with pytest.raises(ValidationError):
            bucket.damage_total = 999  # type: ignore[misc]
