"""
v0.8.9: per-bucket (damage + healing + buff-removal) roll-up for a single
fight's events stream.

Powers the new ``GET /api/v1/fights/{id}/timeline?window_s=5`` route
+ the new :class:`PerFightTimelineChart` on ``/fights/[id]``. The
output is a list of :class:`PerFightTimelineRow` whose
``window_start_ms`` / ``window_end_ms`` straddle ``[start, end)`` and
whose 3 totals are the SUM of the bucket's events.

Why a SEPARATE aggregator from :class:`EventWindowAggregator`
=============================================================

The existing :class:`EventWindowAggregator` (v0.6.0) accumulates
``damage_total + healing_total + event_count`` per bucket. The new
chart needs ``buff_removal_total`` too (the per-bucket strip
contribution is the third sibling of the 3 line series). Extending
:class:`EventBucket` with a ``buff_removal_total`` field would
also surface the field on the existing
``/api/v1/fights/{id}/events`` response (whose
``FightEventsSummaryOut.event_windows`` mirrors ``EventBucket``),
breaking the Phase 8 contract that locked the per-bucket window
shape:

> "Phase 8 deliberately does NOT extend ``EventBucketOut`` with a
> ``buff_removal_total`` field -- the per-bucket window contract
> is locked."

So the new aggregator duplicates the per-bucket skeleton
(``time_ms // window_ms`` integer division + continuous zero-fill
from index 0 to ``max(bucket_index)``) and adds the third
accumulator. ~30 lines of duplication; a v0.9.0 refactor could
extract a shared ``_bucket_by_window_ms`` helper for both
aggregators.

Conventions
===========

- **Window = ``[start_ms, end_ms)`` (half-open)** so consecutive
  buckets tile the timeline without overlap. Mirrors
  :class:`EventWindowAggregator`.
- **Continuous fill.** Gaps between events are zero-filled so the
  visualisation has no holes. The end of the roll-up mirrors
  ``max(time_ms) // window_ms + 1`` regardless of how many events
  land in that final bucket.
- **Empty input -> empty list.** We never synthesise placeholder
  buckets -- an empty fight has no timeline.
- **``window_s`` must be > 0.** Smaller / equal-zero is rejected so
  callers can't accidentally produce infinite-resolution buckets.
  Mirrors :class:`EventWindowAggregator`.

Damage + healing + buff-removal accounting
==========================================

Each event in the input stream is interrogated for its concrete type
via :func:`isinstance`:

- :class:`~gw2_core.DamageEvent`: ``damage_total += event.damage``
- :class:`~gw2_core.HealingEvent`: ``healing_total += event.healing``
- :class:`~gw2_core.BuffRemovalEvent`: ``buff_removal_total += event.buff_removal``

The v0.6.0 dual-emit case (a single cbtevent with
``is_nondamage=1`` + ``value>0`` + ``buff_dmg>0``) yields BOTH a
``HealingEvent`` AND a ``BuffRemovalEvent`` from the same record;
both land in the same bucket and both totals are incremented.
The pure-strip case (``value=0`` + ``buff_dmg>0``) yields ONLY a
``BuffRemovalEvent``; only ``buff_removal_total`` is incremented.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- ``sum(row.damage_total) == sum(event.damage for event in events
  if isinstance(event, DamageEvent))`` (no damage events dropped).
- ``sum(row.healing_total) == sum(event.healing for event in events
  if isinstance(event, HealingEvent))`` (no healing events dropped).
- ``sum(row.buff_removal_total) == sum(event.buff_removal for event
  in events if isinstance(event, BuffRemovalEvent))`` (no strip
  events dropped).
- Every two adjacent rows are contiguous:
  ``rows[i].window_end_ms == rows[i+1].window_start_ms``.

Forward compat
==============

A future v0.9.0 :class:`EventWindowAggregator` extension (e.g.
shared ``_bucket_by_window_ms`` helper extracted to a module-level
private function) would DRY the duplicated skeleton. The new
aggregator's public surface (signature + ``PerFightTimelineRow``
schema) stays unchanged across the refactor.

The ``agents`` + ``duration_s`` parameters are accepted for
signature parity with the per-target trio + the squad / skill
roll-ups (the route layer passes them uniformly). They are NOT
used by this aggregator -- the per-bucket aggregation is
target-agnostic and the bucket count is derived from the events
stream directly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent

# Lower bound enforced on ``window_s``. Smaller windows are not
# meaningful (would be millisecond-resolution buckets; arcdps default
# event write rate is ~30Hz so 1s is a reasonable minimum). Strict
# parallel of :class:`EventWindowAggregator`'s bound.
_MIN_WINDOW_S: Final[int] = 1


@dataclass(slots=True)
class _BucketStats:
    """Mutable per-bucket accumulator for damage, healing, and buff-removal."""

    damage: int = 0
    healing: int = 0
    buff_removal: int = 0


class PerFightTimelineRow(BaseModel):
    """One time-bucketed (damage + healing + buff-removal) roll-up window.

    Spans ``[window_start_ms, window_end_ms)`` (half-open, like
    :class:`EventBucket`). All 3 totals are non-negative
    (Pydantic ``ge=0`` validated). Frozen Pydantic semantics
    (the route-layer transformation to the wire schema uses
    ``model_dump()`` which is safe on a frozen model).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start_ms: int = Field(..., ge=0)
    window_end_ms: int = Field(..., ge=0)
    total_damage: int = Field(default=0, ge=0)
    total_healing: int = Field(default=0, ge=0)
    total_buff_removal: int = Field(default=0, ge=0)


class PerFightTimelineAggregator:
    """Stateless aggregator: events -> contiguous time-bucketed (DPS + HPS + BPS) roll-ups.

    Instantiate once and reuse -- the class holds no state.

    The signature mirrors the existing per-target trio
    (``aggregate(events, duration_s, ...)``) + the squad / skill
    roll-ups (``aggregate(..., agents, duration_s)``) so the route
    layer can invoke the per-bucket aggregator in the same
    ``Promise.allSettled`` pass. The ``agents`` + ``duration_s``
    parameters are accepted for signature parity but NOT used by
    the per-bucket aggregation (the per-bucket skeleton is
    target-agnostic + duration-agnostic -- the bucket count is
    derived from the events stream directly).
    """

    def aggregate(
        self,
        events: Iterable[Event],
        agents: Iterable[Any] = (),
        duration_s: float = 0.0,
        *,
        window_s: int = 5,
    ) -> list[PerFightTimelineRow]:
        """Bucket the input events into ``window_s``-second windows.

        ``agents`` + ``duration_s`` are accepted for signature
        parity with the per-target + squad + skill aggregators
        and are NOT consumed by this method (the per-bucket
        aggregation is target-agnostic + duration-agnostic).
        """
        if window_s < _MIN_WINDOW_S:
            msg = f"window_s must be >= {_MIN_WINDOW_S}, got {window_s!r}"
            raise ValueError(msg)

        window_ms = window_s * 1000
        # Consolidate the per-bucket accumulators into a single
        # dictionary keyed by bucket index. Each value is a
        # slotted dataclass, cutting the hot-loop hash lookups
        # from 3 per event to 1 while keeping the metrics
        # self-documenting.
        buckets: dict[int, _BucketStats] = defaultdict(_BucketStats)

        # ``_ = (agents, duration_s)`` is the explicit
        # unused-parameter acknowledgment so mypy + ruff don't
        # flag the signature. The route layer passes them
        # uniformly to all the aggregators; this one just
        # doesn't need them.
        _ = (agents, duration_s)

        for e in events:
            # ``e.time_ms`` is integers >= 0 (Pydantic-validated upstream),
            # so integer division yields a stable bucket index. Mirrors
            # the v0.6.0 :class:`EventWindowAggregator` loop exactly.
            bucket_index = e.time_ms // window_ms
            bucket = buckets[bucket_index]
            match e:
                case DamageEvent(damage=d):
                    bucket.damage += d
                case HealingEvent(healing=h):
                    bucket.healing += h
                case BuffRemovalEvent(buff_removal=b):
                    bucket.buff_removal += b

        # Derive the expected totals and the last bucket index
        # from the accumulated buckets rather than tracking them
        # inside the hot loop. This saves one ``max()`` call and
        # three integer additions per input event.
        expected_damage = sum(b.damage for b in buckets.values())
        expected_healing = sum(b.healing for b in buckets.values())
        expected_strip = sum(b.buff_removal for b in buckets.values())
        last_bucket_index = max(buckets.keys(), default=-1)

        rows: list[PerFightTimelineRow] = []
        for idx in range(last_bucket_index + 1):
            stats = buckets.get(idx)
            if stats is None:
                damage = healing = strip = 0
            else:
                damage = stats.damage
                healing = stats.healing
                strip = stats.buff_removal
            rows.append(
                PerFightTimelineRow(
                    window_start_ms=idx * window_ms,
                    window_end_ms=(idx + 1) * window_ms,
                    total_damage=damage,
                    total_healing=healing,
                    total_buff_removal=strip,
                )
            )

        self._check_invariants(rows, expected_damage, expected_healing, expected_strip)
        return list(rows)

    @staticmethod
    def _check_invariants(
        rows: list[PerFightTimelineRow],
        expected_damage: int,
        expected_healing: int,
        expected_strip: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated.

        The invariants validate the 3 sum-preservation contracts
        (no damage / healing / strip events dropped) and the
        contiguous-buckets contract (every 2 adjacent rows tile
        the timeline without overlap or gap). Mirrors
        :meth:`EventWindowAggregator._check_invariants` with the
        3 kind extensions.
        """
        actual_damage = sum(r.total_damage for r in rows)
        actual_healing = sum(r.total_healing for r in rows)
        actual_strip = sum(r.total_buff_removal for r in rows)
        if actual_damage != expected_damage:
            msg = (
                f"sum of row.total_damage ({actual_damage}) != "
                f"sum of event.damage ({expected_damage})"
            )
            raise ValueError(msg)
        if actual_healing != expected_healing:
            msg = (
                f"sum of row.total_healing ({actual_healing}) != "
                f"sum of event.healing ({expected_healing})"
            )
            raise ValueError(msg)
        if actual_strip != expected_strip:
            msg = (
                f"sum of row.total_buff_removal ({actual_strip}) != "
                f"sum of event.buff_removal ({expected_strip})"
            )
            raise ValueError(msg)
        # Contiguous-buckets: every 2 adjacent rows tile the
        # timeline without overlap or gap. ``pairwise`` is the
        # canonical idiom for adjacent-element iteration
        # (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.window_end_ms != curr.window_start_ms:
                msg = (
                    f"rows not contiguous: prev.window_end_ms="
                    f"{prev.window_end_ms} != curr.window_start_ms="
                    f"{curr.window_start_ms}"
                )
                raise ValueError(msg)


__all__ = ["PerFightTimelineAggregator", "PerFightTimelineRow"]
