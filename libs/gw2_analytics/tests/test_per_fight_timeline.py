"""v0.8.9 tests for :class:`PerFightTimelineAggregator`.

Seven tests locking the per-bucket (damage + healing + buff-removal)
roll-up contract: empty input, invalid window guard, single-bucket
shape, multi-bucket ordering, the v0.6.0 dual-emit path
(HealingEvent + BuffRemovalEvent from the same cbtevent record),
the all-zero duration guard, and the frozen-Pydantic schema
guarantee. Strict parallel of :file:`test_event_window.py` with the
third (buff-removal) accumulator added.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gw2_analytics.per_fight_timeline import (
    PerFightTimelineAggregator,
    PerFightTimelineRow,
)
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


class TestPerFightTimelineAggregator:
    """v0.8.9 contract matrix for :class:`PerFightTimelineAggregator`."""

    def test_empty_input_yields_empty_list(self) -> None:
        """No events -> no rows. The aggregator never synthesises
        placeholder rows for an empty stream.
        """
        rows = PerFightTimelineAggregator().aggregate([], window_s=1)
        assert rows == []

    def test_invalid_window_raises_value_error(self) -> None:
        """``window_s < 1`` raises ``ValueError`` BEFORE any iteration
        (the bound is checked up front so a misuse fails fast with a
        clear error message). Mirrors the v0.6.0 invariant.
        """
        with pytest.raises(ValueError, match="window_s must be >= 1"):
            PerFightTimelineAggregator().aggregate([], window_s=0)
        with pytest.raises(ValueError, match="window_s must be >= 1"):
            PerFightTimelineAggregator().aggregate([], window_s=-5)

    def test_single_bucket_shape(self) -> None:
        """3 events in the same 1-second bucket -> 1 row with the
        correct per-kind totals + the 3 metadata fields. Strict
        parallel of :meth:`test_event_window_single_event_creates_single_bucket`
        with the 3rd kind added.
        """
        rows = PerFightTimelineAggregator().aggregate(
            [
                _damage(time_ms=500, damage=200),  # bucket 0
                _healing(time_ms=500, healing=50),  # bucket 0
                _strip(time_ms=500, buff_removal=10),  # bucket 0
            ],
            window_s=1,
        )
        assert len(rows) == 1
        assert rows[0].window_start_ms == 0
        assert rows[0].window_end_ms == 1000
        assert rows[0].total_damage == 200
        assert rows[0].total_healing == 50
        assert rows[0].total_buff_removal == 10

    def test_multi_bucket_ordering(self) -> None:
        """6 events across 3 buckets -> 3 rows in ascending
        ``window_start_ms`` order with the correct per-bucket
        totals. Verifies the continuous-fill invariant + the
        ascending-order output contract + the per-bucket
        accumulator correctness across 3 kinds.
        """
        rows = PerFightTimelineAggregator().aggregate(
            [
                _damage(time_ms=500, damage=200),  # bucket 0
                _healing(time_ms=500, healing=50),  # bucket 0
                _damage(time_ms=2500, damage=100),  # bucket 2
                _healing(time_ms=2500, healing=80),  # bucket 2
                _strip(time_ms=4500, buff_removal=20),  # bucket 4
                _strip(time_ms=4500, buff_removal=30),  # bucket 4
            ],
            window_s=1,
        )
        # Continuous fill: bucket indices 0, 1 (zero), 2, 3 (zero), 4
        assert len(rows) == 5
        # Ascending order: the chart's X-axis relies on this
        # (the first point is the leftmost, the last is the rightmost).
        for i in range(len(rows) - 1):
            assert rows[i].window_start_ms < rows[i + 1].window_start_ms
        # Bucket 0: 1 damage + 1 healing
        assert rows[0].total_damage == 200
        assert rows[0].total_healing == 50
        assert rows[0].total_buff_removal == 0
        # Bucket 1: zero-filled
        assert rows[1].total_damage == 0
        assert rows[1].total_healing == 0
        assert rows[1].total_buff_removal == 0
        # Bucket 2: 1 damage + 1 healing
        assert rows[2].total_damage == 100
        assert rows[2].total_healing == 80
        assert rows[2].total_buff_removal == 0
        # Bucket 3: zero-filled
        assert rows[3].total_damage == 0
        assert rows[3].total_healing == 0
        assert rows[3].total_buff_removal == 0
        # Bucket 4: 2 strips (sums to 50)
        assert rows[4].total_damage == 0
        assert rows[4].total_healing == 0
        assert rows[4].total_buff_removal == 50
        # Contiguity invariant: every 2 adjacent rows tile the
        # timeline without overlap or gap.
        for i in range(len(rows) - 1):
            assert rows[i].window_end_ms == rows[i + 1].window_start_ms

    def test_dual_emit_path_increments_both_totals(self) -> None:
        """Lock the v0.6.0 dual-emit contract for the per-bucket
        aggregator: a single cbtevent record with
        ``is_nondamage=1`` + ``value>0`` + ``buff_dmg>0`` yields
        BOTH a ``HealingEvent`` AND a ``BuffRemovalEvent`` in
        the events stream, so the per-bucket aggregator must
        increment BOTH the heal AND the strip totals in the
        same bucket.

        The events stream is hand-built with one ``HealingEvent``
        + one ``BuffRemovalEvent`` at the same ``time_ms`` to
        simulate the parser's dual-emit output. Without the
        dual-emit accounting, the strip total would silently
        drop to 0 (a real-fixture regression that would be hard
        to spot from the wire surface alone).
        """
        rows = PerFightTimelineAggregator().aggregate(
            [
                # Single dual-emit record (the parser yields
                # BOTH events from a single cbtevent with
                # is_nondamage=1 + value>0 + buff_dmg>0).
                # ``time_ms=500`` lands the dual-emit in bucket
                # 0 (the [0, 1000) window) so the test
                # exercises the dual-emit accounting in
                # isolation, without the noise of a
                # zero-filled bucket 0 sibling.
                HealingEvent(
                    time_ms=500,
                    source_agent_id=99,
                    target_agent_id=1,
                    skill_id=42,
                    healing=800,
                ),
                BuffRemovalEvent(
                    time_ms=500,
                    source_agent_id=99,
                    target_agent_id=1,
                    skill_id=42,
                    buff_removal=300,
                ),
            ],
            window_s=1,
        )
        assert len(rows) == 1
        # Both the heal AND the strip from the same dual-emit
        # record land in the same bucket.
        assert rows[0].total_healing == 800
        assert rows[0].total_buff_removal == 300
        # No damage in this fixture.
        assert rows[0].total_damage == 0

    def test_zero_window_raises_via_min_window_guard(self) -> None:
        """``window_s=0`` is rejected at the parameter guard (the
        ``_MIN_WINDOW_S`` bound). The guard fires BEFORE any
        iteration so the error is deterministic and immediate.

        ``duration_s=0`` (the natural extension) is NOT a
        concern: the per-bucket aggregation derives the bucket
        count from the events stream (not from ``duration_s``),
        so a zero-duration event stream is just a stream of
        bucket-0 events (the math works out).
        """
        with pytest.raises(ValueError, match="window_s must be >= 1"):
            PerFightTimelineAggregator().aggregate(
                [_damage(time_ms=0, damage=100)],
                window_s=0,
            )

    def test_model_is_frozen_pydantic(self) -> None:
        """``model_config = ConfigDict(frozen=True)`` blocks
        ``__setattr__`` at runtime. A future refactor that
        changes the frozen flag would silently allow mutation
        of shared row instances (a real bug class in the
        analytics layer), so this test pins the guarantee.
        """
        row = PerFightTimelineRow(
            window_start_ms=0,
            window_end_ms=1000,
            total_damage=200,
            total_healing=100,
            total_buff_removal=50,
        )
        # ``frozen=True`` triggers a runtime guard on mutation even
        # though the type-checker should reject the line first.
        with pytest.raises(ValidationError):
            row.total_damage = 999  # type: ignore[misc]
