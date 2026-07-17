"""

Phase 6: time-bucketed event roll-ups from synthetic :class:`Event`
streams.

Phase 6 v1 ships aggregators over IN-MEMORY event lists because the
gw2_evtc_parser does not yet surface the event block. Forward-compat
notes (Phase 6 v2) live in the module docstring.

Conventions
===========

- **Window = ``[start_ms, end_ms)`` (half-open)** so consecutive
  buckets tile the timeline without overlap.
- **Continuous fill.** Gaps between events are zero-filled so the
  visualisation has no holes. The end of the roll-up mirrors
  ``max(time_ms) // window_ms + 1`` regardless of how many events land
  in that final bucket.
- **Empty input -> empty list.** We never synthesise placeholder
  buckets -- an empty fight has no timeline.
- **``window_s`` must be > 0.** Smaller / equal-zero is rejected so
  callers can't accidentally produce infinite-resolution buckets.

Damage + healing + buff-removal accounting
==========================================

Each event in the input stream is interrogated for its concrete type
via :func:`isinstance`:

- :class:`~gw2_core.DamageEvent`: ``damage_total += event.damage``
- :class:`~gw2_core.HealingEvent`: ``healing_total += event.healing``
- :class:`~gw2_core.BuffRemovalEvent`: ``buff_removal_total += event.buff_removal``
  (Phase 8 cascade)
- Other future kinds: not counted in damage / healing / buff-removal
  but still accumulate in ``event_count`` so the per-bucket activity
  signal is forward-compat.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- Sum of ``bucket.event_count`` across all buckets == number of
  input events (no events dropped, no double-counting).
- Every two adjacent buckets are contiguous:
  ``buckets[i].end_ms == buckets[i+1].start_ms``.

Forward compat
==============

Phase 6 v2 will source events from the gw2_evtc_parser event block.
The aggregator signature (``Iterable[Event]`` ->
``list[EventBucket]``) stays unchanged; the parser swap is purely an
upstream change.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent

# Lower bound enforced on ``window_s``. Smaller windows are not
# meaningful (would be millisecond-resolution buckets; arcdps default
# event write rate is ~30Hz so 1s is a reasonable minimum).
_MIN_WINDOW_S: Final[int] = 1


@dataclass(slots=True)
class _BucketStats:
    """Mutable per-bucket accumulator for damage, healing, buff-removal, and count."""

    damage: int = 0
    healing: int = 0
    buff_removal: int = 0
    count: int = 0


class EventBucket(BaseModel):
    """One time-bucketed roll-up window spanning ``[start_ms, end_ms)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    damage_total: int = Field(default=0, ge=0)
    healing_total: int = Field(default=0, ge=0)
    # Phase 8 cascade (plan 083): per-bucket buff-removal total.
    # Mirrors the ``damage_total`` / ``healing_total`` invariants
    # (sum across buckets == sum of ``event.buff_removal`` across
    # input events). ``default=0`` so pre-Phase-8 fixtures without
    # strip events continue to validate cleanly (the existing
    # tests assert ``bucket.damage_total`` + ``bucket.healing_total``
    # only; the new field defaults to 0 in those cases).
    buff_removal_total: int = Field(default=0, ge=0)
    event_count: int = Field(default=0, ge=0)


class EventWindowAggregator:
    """Stateless aggregator: events -> contiguous time-bucketed roll-ups.

    Instantiate once and reuse -- the class holds no state.
    """

    def aggregate(
        self,
        events: Iterable[Event],
        window_s: int,
    ) -> list[EventBucket]:
        """Bucket the input events into ``window_s``-second windows."""
        if window_s < _MIN_WINDOW_S:
            msg = f"window_s must be >= {_MIN_WINDOW_S}, got {window_s!r}"
            raise ValueError(msg)

        window_ms = window_s * 1000
        # Consolidate the per-bucket accumulators into a single
        # dictionary keyed by bucket index. Each value is a slotted
        # dataclass, cutting the hot-loop hash lookups from 4 per
        # event to 1 while keeping the metrics self-documenting.
        stats_by_bucket: dict[int, _BucketStats] = defaultdict(_BucketStats)

        for e in events:
            # ``e.time_ms`` is integers >= 0 (Pydantic-validated upstream),
            # so integer division yields a stable bucket index.
            bucket_index = e.time_ms // window_ms
            stats = stats_by_bucket[bucket_index]
            stats.count += 1
            # Use structural pattern matching (faster than chained
            # ``isinstance`` in tight loops on CPython 3.10+) to
            # dispatch the 3 event kinds. Future ``Event``
            # subclasses fall through silently while still being
            # counted in ``event_count``.
            match e:
                case DamageEvent(damage=d):
                    stats.damage += d
                case HealingEvent(healing=h):
                    stats.healing += h
                case BuffRemovalEvent(buff_removal=b):
                    stats.buff_removal += b

        # Derive the last bucket index and total strip from the
        # accumulated per-bucket stats rather than tracking them
        # inside the hot loop. This saves a ``max()`` call and an
        # integer addition per input event.
        last_bucket_index = max(stats_by_bucket.keys(), default=-1)
        total_strip = sum(stats.buff_removal for stats in stats_by_bucket.values())

        buckets: list[EventBucket] = []
        for idx in range(last_bucket_index + 1):
            bucket_stats = stats_by_bucket.get(idx)
            if bucket_stats is None:
                damage = healing = strip = count = 0
            else:
                damage = bucket_stats.damage
                healing = bucket_stats.healing
                strip = bucket_stats.buff_removal
                count = bucket_stats.count
            buckets.append(
                EventBucket(
                    start_ms=idx * window_ms,
                    end_ms=(idx + 1) * window_ms,
                    damage_total=damage,
                    healing_total=healing,
                    buff_removal_total=strip,
                    event_count=count,
                ),
            )

        total_event_count = sum(stats.count for stats in stats_by_bucket.values())
        # Phase 8 cascade (plan 083): pass ``total_strip`` to
        # ``_check_invariants`` so the per-bucket buff-removal sum
        # is cross-validated against the input stream total.
        self._check_invariants(buckets, total_event_count, total_strip)
        return list(buckets)

    @staticmethod
    def _check_invariants(
        buckets: list[EventBucket],
        expected_total_events: int,
        # Phase 8 cascade (plan 083): expected total ``buff_removal``
        # across the input stream. Validates that
        # ``sum(b.buff_removal_total for b in buckets) ==
        # expected_total_strip`` -- no strip events dropped, no
        # double-counting.
        expected_total_strip: int = 0,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        total = sum(b.event_count for b in buckets)
        if total != expected_total_events:
            msg = f"sum of bucket.event_count ({total}) != len(events) ({expected_total_events})"
            raise ValueError(msg)
        # Phase 8 cascade (plan 083): the buff-removal sum across
        # buckets must equal the expected input-stream total. This
        # invariant catches a future refactor that accidentally
        # drops the per-bucket ``buff_removal_by_bucket[idx] += ...``
        # accumulation (e.g. a copy-paste regression from the
        # Damage / Healing branches above).
        total_strip = sum(b.buff_removal_total for b in buckets)
        if total_strip != expected_total_strip:
            msg = (
                f"sum of bucket.buff_removal_total ({total_strip}) "
                f"!= sum of event.buff_removal ({expected_total_strip})"
            )
            raise ValueError(msg)
        # ``pairwise`` is the canonical idiom for adjacent buckets
        # (ruff RUF007); equivalent to ``zip(buckets, buckets[1:])``.
        for prev, curr in pairwise(buckets):
            if prev.end_ms != curr.start_ms:
                msg = (
                    f"buckets not contiguous: prev.end_ms={prev.end_ms} "
                    f"!= curr.start_ms={curr.start_ms}"
                )
                raise ValueError(msg)


__all__ = ["EventBucket", "EventWindowAggregator"]
