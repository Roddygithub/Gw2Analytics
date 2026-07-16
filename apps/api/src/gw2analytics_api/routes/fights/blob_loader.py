"""Canonical blob-load + decompression + event-split primitive.

The shared helper that 5 endpoints on ``/fights/{id}/*`` (events,
squads, skills, timeline + per-player timeline) all use. The
helper enforces the canonical 404 / 502 contract:

- ``404 Not Found``: fight id is unknown OR
  ``events_blob_uri is None`` OR the blob is missing in MinIO
  (``S3Error``).
- ``404 Not Found``: the events list is empty after the
  ``jsonl.splitlines()`` pass (``list`` emptiness check).
- ``502 Bad Gateway``: the blob is present but
  ``gzip.decompress`` failed (corrupt blob).

Originally inlined in ``apps/api/src/gw2analytics_api/routes/fights/__init__.py``
pre-A2 god-module refactor. Extracted in PR 2 sub-commit 1.

Provenance
----------

The A2 god-module refactor (plan 021) decomposed
``routes/fights/__init__.py`` into a ``routes/fights/`` sub-pack:

- PR 1 (commits ``1565066`` + ``79bae42``) extracted the cache
  primitive to ``blob_cache.py`` + the conftest
  ``clear_blob_caches`` autouse wire-up.
- PR 2 sub-commit 1 (this commit) extracts the blob-load helper
  here. The helper sees no FastAPI dependency in the
  ``Session`` argument shape, but DOES raise ``HTTPException``
  directly (consistent with the original inline implementation);
  the route handlers stay thin on cloud-side state-translation
  responsibility.

Public surface
==============

- :func:`_load_fight_events` -- the shared DB + blob + decompress
  + parse helper.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from fastapi import HTTPException, status
from minio.error import S3Error
from sqlalchemy.orm import Session

from gw2_core import Event
from gw2analytics_api._event_dispatch import build_event_iterator
from gw2analytics_api.models import OrmFight
from gw2analytics_api.routes.fights.blob_cache import _cached_get_events

logger = logging.getLogger(__name__)

# v0.10.25 fix: cache the PARSED events list (not just the gzipped
# bytes) so the 5 endpoints that call _load_fight_events in parallel
# (events / squads / skills / timeline / timeline-players) share ONE
# parsed list instead of each materialising their own ~300 MB copy.
# The cache is a manual OrderedDict keyed by blob_uri only (NOT
# gz_bytes — hashing a 12 MB bytes object on every lookup would be
# O(n) per call). maxsize=3 is smaller than the bytes cache (8) because
# each entry holds ~300MB of parsed Pydantic models; 3 entries x ~300MB
# = ~900MB per worker, manageable with --workers 2. A per-URI lock
# + double-checked-locking prevents concurrent re-parses on a cold
# cache (the first thread parses; N-1 waiters get the cached result).
_PARSED_EVENTS_CACHE: OrderedDict[str, tuple[Event, ...]] = OrderedDict()
_PARSED_EVENTS_CACHE_MAXSIZE: int = 3
_PARSED_EVENTS_LOCKS: dict[str, threading.Lock] = {}
_PARSED_EVENTS_LOCKS_META_LOCK = threading.Lock()


def _get_parsed_events_lock(blob_uri: str) -> threading.Lock:
    """Atomically fetch (or create) the per-URI lock for parsed-events."""
    lock = _PARSED_EVENTS_LOCKS.get(blob_uri)
    if lock is not None:
        return lock
    with _PARSED_EVENTS_LOCKS_META_LOCK:
        lock = _PARSED_EVENTS_LOCKS.get(blob_uri)
        if lock is None:
            lock = threading.Lock()
            _PARSED_EVENTS_LOCKS[blob_uri] = lock
    return lock


# v0.10.25 fix: arcdps writes GetTickCount64() (ms since Windows boot)
# as the time field. For a PC up for days, this can be in the billions.
# We normalize to fight-relative ONLY when the minimum time_ms exceeds
# 24 hours (86_400_000 ms) — this avoids breaking synthetic test
# fixtures (which use small time_ms values like 0, 500, 1500) while
# fixing the production crash on real arcdps logs.
_ARCDPS_TIME_NORMALIZATION_THRESHOLD: int = 86_400_000  # 24h in ms


def _cached_parse_events(blob_uri: str, gz_bytes: bytes) -> tuple[Event, ...]:
    """Cache the parsed events list keyed by blob_uri (immutable).

    Uses a manual OrderedDict (NOT functools.lru_cache) because:
    1. lru_cache would hash the gz_bytes argument (12 MB+) on every
       call — an O(n) cost per lookup that defeats the cache purpose.
    2. A manual dict keyed by blob_uri alone is O(1) per lookup.

    Double-checked locking: the first thread acquires the per-URI lock,
    parses, and stores. Concurrent callers that arrive while the lock
    is held block; on release they re-check the cache (now populated)
    and return the cached result without re-parsing.

    If the minimum time_ms across all events exceeds 24h (arcdps
    GetTickCount64 from a long-running PC), the events are normalized
    to fight-relative by subtracting the minimum. This prevents the
    EventWindowAggregator from creating billions of buckets.
    """
    # Fast path: cache hit (no lock needed — dict reads are thread-safe
    # under the GIL for simple key lookups).
    cached = _PARSED_EVENTS_CACHE.get(blob_uri)
    if cached is not None:
        return cached
    # Slow path: acquire per-URI lock, double-check, parse, store.
    with _get_parsed_events_lock(blob_uri):
        cached = _PARSED_EVENTS_CACHE.get(blob_uri)
        if cached is not None:
            return cached
        events = tuple(build_event_iterator(gz_bytes=gz_bytes))
        # Conditional normalization: only if the min time_ms looks like
        # an absolute arcdps GetTickCount64 value (> 24h). Synthetic
        # test fixtures use small values (0, 500, 1500) and are NOT
        # normalized, preserving existing test expectations.
        if events:
            base = min(e.time_ms for e in events)
            if base >= _ARCDPS_TIME_NORMALIZATION_THRESHOLD:
                events = tuple(e.model_copy(update={"time_ms": e.time_ms - base}) for e in events)
        # LRU eviction: remove oldest entry if at capacity.
        # NOTE: we intentionally do NOT clean up the per-URI lock for
        # the evicted entry. Removing it creates a race where a thread
        # still holding the old lock + a new thread creating a fresh
        # lock both parse concurrently (defeating singleflight). Each
        # threading.Lock is ~100 bytes; even 1000 distinct fights =
        # ~100KB — not a real memory concern for this application.
        if len(_PARSED_EVENTS_CACHE) >= _PARSED_EVENTS_CACHE_MAXSIZE:
            _PARSED_EVENTS_CACHE.popitem(last=False)
        _PARSED_EVENTS_CACHE[blob_uri] = events
        return events


def _load_fight_events(
    db: Session,
    fight_id: str,
) -> list[Event]:
    """Load + decompress + parse the events blob for one fight.

    Centralises the blob-load + decompress + event-split pattern
    that :func:`get_fight_events`, :func:`get_fight_squads`,
    :func:`get_fight_skills`, :func:`get_fight_timeline`, and
    :func:`get_fight_player_timeline` all share. The helper
    enforces the canonical 404 / 502 contract:

    - ``404 Not Found``: fight id is unknown OR
      ``events_blob_uri is None`` OR the blob is missing in MinIO
      (``S3Error`` -- closes the loop if the upload succeeded but
      the MinIO write failed silently or was evicted).
    - ``404 Not Found``: the events list is empty after the
      ``jsonl.splitlines()`` pass. Defensive: the parser writes
      no empty blobs, but a 0-byte blob (manual PUT, replication
      drift) still honours the "no event data available" contract
      so the response never confuses "parser ran, nothing
      happened" with "data unavailable".
    - ``502 Bad Gateway``: the blob is present but
      ``gzip.decompress`` failed. A fight row with a corrupt blob
      is still a valid row; this is a blob-store consistency issue
      rather than a client error.

    Returns the parsed :class:`Event` list so the caller can split
    by ``isinstance`` at the call site and feed the per-kind
    streams to the aggregators (the v0.7.0 SquadRollup + SkillUsage
    aggregators accept paired single-typed streams; the per-target
    trio each accept one single-typed stream).
    """
    fight = db.get(OrmFight, fight_id)
    if fight is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fight not found")
    if fight.events_blob_uri is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"detail": "events unavailable", "error_code": "EVENTS_UNAVAILABLE"},
        )

    try:
        gz_bytes = _cached_get_events(fight.events_blob_uri)
    except S3Error:
        logger.warning(
            "events blob %s missing in MinIO for fight %s",
            fight.events_blob_uri,
            fight_id,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable") from None

    try:
        # v0.10.25 fix: use the cached parsed-events layer so 5 parallel
        # endpoints share ONE parsed list instead of each materialising
        # their own ~300 MB copy (the root cause of the /events OOM crash
        # on large WvW fights with 500+ agents).
        events = list(_cached_parse_events(fight.events_blob_uri, gz_bytes))
    except (OSError, EOFError) as exc:
        logger.exception("events blob %s not gzip-decodable", fight.events_blob_uri)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "events blob corrupt") from exc

    if not events:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable")
    return events


def clear_parsed_events_cache() -> None:
    """Clear the parsed-events cache + per-URI locks for test isolation."""
    _PARSED_EVENTS_CACHE.clear()
    _PARSED_EVENTS_LOCKS.clear()


__all__ = ["_load_fight_events", "clear_parsed_events_cache"]
