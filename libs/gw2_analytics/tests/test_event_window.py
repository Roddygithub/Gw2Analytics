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
from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent


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


def _strip(time_ms: int, buff_removal: int) -> BuffRemovalEvent:
    return BuffRemovalEvent(
        time_ms=time_ms,
        source_agent_id=99,
        target_agent_id=1,
        skill_id=44,
        buff_removal=buff_removal,
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

    # --- Phase 8 cascade (plan 083) -------------------------------------
    # The Phase 8 cycle that added ``BuffRemovalEvent`` as the third
    # ``Event`` discriminated-union member cascaded the change to
    # ``target_buff_removal.py`` but NOT to ``event_window.py`` --
    # the per-bucket rollup silently dropped the ``buff_removal_total``
    # per bucket. The chart in
    # ``apps/web/src/app/fights/[id]/page.tsx``'s
    # ``<PerFightTimelineChart>`` could render damage + healing bands
    # but not a buff-strip band. The 5 tests below lock the Phase 8
    # cascade contract: per-bucket ``buff_removal_total`` accumulates
    # correctly across all 3 ``Event`` kinds + across multiple
    # buckets, the cross-field invariant fires, and the Pydantic
    # schema's forward-compat default keeps pre-Phase-8 callers valid.

    def test_damage_event_in_bucket_defaults_buff_removal_total_to_zero(
        self,
    ) -> None:
        # 1 DamageEvent at t=1500ms lands in bucket 1 ([1000, 2000))
        # with window_s=1. The aggregator's continuous-fill contract
        # creates bucket 0 (zero-filled) + bucket 1 (with the event)
        # = 2 buckets total. The ``buff_removal_total`` field must
        # default to 0 (the Phase 8 additive default that keeps
        # pre-Phase-8 callers valid) AND the zero-filled bucket 0
        # must also have ``buff_removal_total == 0``.
        buckets = EventWindowAggregator().aggregate(
            [_damage(time_ms=1500, damage=1234)],
            window_s=1,
        )
        assert len(buckets) == 2
        # Bucket 0: zero-filled (no event in [0, 1000)).
        assert buckets[0].start_ms == 0
        assert buckets[0].end_ms == 1000
        assert buckets[0].damage_total == 0
        assert buckets[0].healing_total == 0
        assert buckets[0].buff_removal_total == 0
        assert buckets[0].event_count == 0
        # Bucket 1: the event.
        assert buckets[1].start_ms == 1000
        assert buckets[1].end_ms == 2000
        assert buckets[1].damage_total == 1234
        assert buckets[1].healing_total == 0
        assert buckets[1].buff_removal_total == 0
        assert buckets[1].event_count == 1

    def test_buff_removal_event_accumulates_in_bucket(self) -> None:
        # 1 BuffRemovalEvent at t=1500ms lands in bucket 1; the
        # ``buff_removal_total`` field accumulates the event's
        # ``buff_removal`` value. The damage + healing accumulators
        # are untouched. 2 buckets total (bucket 0 zero-filled +
        # bucket 1 with the event).
        buckets = EventWindowAggregator().aggregate(
            [_strip(time_ms=1500, buff_removal=300)],
            window_s=1,
        )
        assert len(buckets) == 2
        assert buckets[0].damage_total == 0
        assert buckets[0].healing_total == 0
        assert buckets[0].buff_removal_total == 0
        assert buckets[0].event_count == 0
        assert buckets[1].damage_total == 0
        assert buckets[1].healing_total == 0
        assert buckets[1].buff_removal_total == 300
        assert buckets[1].event_count == 1

    def test_mixed_damage_healing_strip_in_single_bucket(self) -> None:
        # 3 events (Damage + Healing + BuffRemoval) all at t=1500ms
        # land in bucket 1. The 3 independent roll-ups accumulate in
        # parallel; ``event_count`` is the residue of the input
        # stream (3 events regardless of kind). 2 buckets total
        # (bucket 0 zero-filled + bucket 1 with all 3 events).
        buckets = EventWindowAggregator().aggregate(
            [
                _damage(time_ms=1500, damage=200),
                _healing(time_ms=1500, healing=50),
                _strip(time_ms=1500, buff_removal=300),
            ],
            window_s=1,
        )
        assert len(buckets) == 2
        b = buckets[1]
        assert b.damage_total == 200
        assert b.healing_total == 50
        assert b.buff_removal_total == 300
        assert b.event_count == 3
        # Bucket 0 is zero-filled.
        assert buckets[0].event_count == 0
        assert buckets[0].damage_total == 0
        assert buckets[0].healing_total == 0
        assert buckets[0].buff_removal_total == 0

    def test_buff_removal_accumulates_across_multiple_buckets(self) -> None:
        # 2 BuffRemovalEvents at t=1500ms and t=2500ms with
        # window_s=1 land in bucket 1 and bucket 2 respectively.
        # 3 buckets total (bucket 0 zero-filled + bucket 1 with
        # event 1 + bucket 2 with event 2). The per-bucket
        # ``buff_removal_total`` accumulates each event into its
        # own bucket; the total across buckets == sum of
        # event.buff_removal (cross-field invariant).
        buckets = EventWindowAggregator().aggregate(
            [
                _strip(time_ms=1500, buff_removal=300),  # bucket 1
                _strip(time_ms=2500, buff_removal=200),  # bucket 2
            ],
            window_s=1,
        )
        assert len(buckets) == 3
        assert buckets[0].buff_removal_total == 0
        assert buckets[1].buff_removal_total == 300
        assert buckets[2].buff_removal_total == 200
        assert sum(b.buff_removal_total for b in buckets) == 500
        # event_count is the residue of the input stream.
        assert sum(b.event_count for b in buckets) == 2

    def test_buff_removal_total_field_default_and_annotation(self) -> None:
        # Lock the Pydantic schema: ``buff_removal_total`` must
        # default to 0 (so pre-Phase-8 callers that construct
        # ``EventBucket(start_ms, end_ms, damage_total, healing_total)``
        # continue to validate cleanly) and be typed as ``int``
        # (forward-compat with the existing ``damage_total`` /
        # ``healing_total`` fields).
        field = EventBucket.model_fields["buff_removal_total"]
        assert field.default == 0
        assert field.annotation is int
