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

Damage + healing accounting
===========================

Each event in the input stream is interrogated for its concrete type
via :func:`isinstance`:

- :class:`~gw2_core.DamageEvent`: ``damage_total += event.damage``
- :class:`~gw2_core.HealingEvent`: ``healing_total += event.healing``
- Other future kinds: not counted in damage / healing but still
  accumulate in ``event_count`` so the per-bucket activity signal is
  forward-compat.

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
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import DamageEvent, Event, HealingEvent

# Lower bound enforced on ``window_s``. Smaller windows are not
# meaningful (would be millisecond-resolution buckets; arcdps default
# event write rate is ~30Hz so 1s is a reasonable minimum).
_MIN_WINDOW_S: Final[int] = 1


class EventBucket(BaseModel):
    """One time-bucketed roll-up window spanning ``[start_ms, end_ms)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    damage_total: int = Field(default=0, ge=0)
    healing_total: int = Field(default=0, ge=0)
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
        damage_by_bucket: dict[int, int] = defaultdict(int)
        healing_by_bucket: dict[int, int] = defaultdict(int)
        count_by_bucket: dict[int, int] = defaultdict(int)
        last_bucket_index = -1

        for e in events:
            # ``e.time_ms`` is integers >= 0 (Pydantic-validated upstream),
            # so integer division yields a stable bucket index.
            bucket_index = e.time_ms // window_ms
            last_bucket_index = max(last_bucket_index, bucket_index)
            count_by_bucket[bucket_index] += 1
            if isinstance(e, DamageEvent):
                damage_by_bucket[bucket_index] += e.damage
            elif isinstance(e, HealingEvent):
                healing_by_bucket[bucket_index] += e.healing
            # Future EventType subclasses land here -- still
            # counted in ``event_count`` even when no damage /
            # healing attribute exists.

        buckets: list[EventBucket] = []
        for idx in range(last_bucket_index + 1):
            buckets.append(
                EventBucket(
                    start_ms=idx * window_ms,
                    end_ms=(idx + 1) * window_ms,
                    damage_total=damage_by_bucket[idx],
                    healing_total=healing_by_bucket[idx],
                    event_count=count_by_bucket[idx],
                )
            )

        total_event_count = sum(count_by_bucket.values())
        self._check_invariants(buckets, total_event_count)
        return list(buckets)

    @staticmethod
    def _check_invariants(
        buckets: list[EventBucket],
        expected_total_events: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        total = sum(b.event_count for b in buckets)
        if total != expected_total_events:
            msg = f"sum of bucket.event_count ({total}) != len(events) ({expected_total_events})"
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
