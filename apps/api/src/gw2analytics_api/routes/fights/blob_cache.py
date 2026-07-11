"""Canonical blob-cache primitive for ``apps/api``.

The three-cooperative-layer cache that backs
:func:`_cached_get_events` lives here as a dedicated module so
the cache concern is independently-testable from the FastAPI
HTTP surface. Composition:

1. ``functools.lru_cache(maxsize=8)`` -- the POST-COMPLETION
   cache (plan 014; ``apps/api/src/gw2analytics_api/routes/fights.py``
   was the original home, but the cache primitive sees no
   FastAPI dependency so it is now lifted into this sub-pack).
2. The per-URI ``_BLOB_URI_LOCKS`` ``threading.Lock`` registry
   -- the IN-FLIGHT serialiser (plan 029). Belt-and-suspenders:
   the singleflight (layer 3) collapses the underlying fetches
   on a cold cache, but the latch bounds the in-flight Future
   peak to ``maxsize=8`` AND bridges the nanosecond race window
   between ``_IN_FLIGHT_FUTURES.pop()`` in the ``finally`` block
   and the ``lru_cache`` decorator's atomic cache-write at
   function return.
3. The ``_IN_FLIGHT_FUTURES`` ``concurrent.futures.Future`` registry
   -- the SINGLEFLIGHT (plan 144). Collapses N concurrent
   cold-cache callers to 1 fetcher + N-1 ``future.result()``
   waiters + 0 redundant MinIO GETs.

Provenance
----------

Originally inlined in ``apps/api/src/gw2analytics_api/routes/fights.py``
(~640 LoC pre-A2). The A2 god-module refactor (plan 021) extracted
it here so the cache concern sits in a dedicated, independently-testable
primitive module with no FastAPI dependency -- the cache layer is a
generic \"singleflight-on-top-of-lru-on-top-of-per-URI-latch\" pattern
that does not depend on the gateway's HTTP surface.

Public surface
==============

- :func:`_cached_get_events` -- the three-layer cache wrapper.
- :func:`clear_blob_caches` -- test-isolation helper that clears
  the lru_cache layer AND drops the per-URI locks + in-flight
  Futures. Wired into ``apps/api/tests/conftest.py``'s autouse
  fixture chain in A2 PR 1.1 (post commit 1565066).
- :data:`_BLOB_URI_LOCKS` + :data:`_BLOB_URI_LOCKS_META_LOCK` --
  the per-URI latch state (consumed directly by the cache tests
  for invariant pinning).
- :data:`_IN_FLIGHT_FUTURES` + :data:`_IN_FLIGHT_FUTURES_META_LOCK` --
  the singleflight state.
- :func:`_get_blob_uri_lock` + :func:`_get_or_create_inflight_future`
  -- the atomic helpers used by :func:`_cached_get_events`.

Test monkeypatch contract (READ BEFORE PATCHING)
================================================

The cache primitive's :func:`_cached_get_events` resolves
:func:`get_events` via THIS module's namespace (NOT via
:mod:`apps.api.routes.fights`'s). Tests MUST hit the monkeypatch
target ``gw2analytics_api.routes.fights.blob_cache.get_events``;
patching ``gw2analytics_api.routes.fights.get_events`` is a NO-OP
post the A2 god-module refactor (commit 1565066) because the call
site reads from the submodule's globals. The 2 cache test files
(``test_fights_blob_cache_thundering_herd.py`` +
``test_fights_blob_cache.py``) already retarget their 9 monkeypatch
sites accordingly.
"""

from __future__ import annotations

import concurrent.futures
import functools
import threading

from gw2analytics_api.storage import get_events

# v0.9.4 plan 014: cache the gzipped events blob bytes across
# requests. The 4 endpoints on ``/fights/{id}`` (events, squads,
# skills, timeline) are fetched in parallel by the frontend and all
# read the same blob. Caching the gzipped bytes (not the parsed
# events) keeps memory bounded while avoiding 4x MinIO GETs.
# maxsize=8 caps the cache at ~8x typical blob size.
#
# v0.10.10 plan 029: per-URI ``threading.Lock`` prevents the
# thundering-herd stampede when the frontend's ``Promise.allSettled``
# fires N parallel ``/fights/{id}/*`` requests against the same
# ``blob_uri`` on a cold cache. ``functools.lru_cache`` has NO
# internal lock shared with the wrapped function body; concurrent
# callers on a cold cache would all execute the wrapped function
# (N MinIO GETs in parallel, defeating the cache). A per-URI lock
# serialises the wrapped function calls, capping memory peak at
# one decompressed blob in flight at a time.
#
# v0.10.11+ plan 144: the per-URI lock is
# AUGMENTED with a true singleflight on the cold-cache miss path.
# The singleflight collapses N concurrent callers on a cold cache
# to 1 fetcher + N-1 waiters + 0 redundant MinIO GETs (the prior
# latch collapsed to N MinIO GETs + N decompressed blobs in RAM,
# sequentialised). The per-URI latch stays as defence-in-depth:
# the future dict + the lock are both bounded, and the lock further
# caps the in-flight ``_IN_FLIGHT_FUTURES`` peak to ``maxsize=8``.
#
# Why a regular dict + meta-lock instead of ``defaultdict``:
# ``collections.defaultdict.__missing__`` is NOT thread-safe --
# 4 threads can each see a missing key, each invoke the factory,
# and each get a DIFFERENT ``Lock`` object, defeating the latch.
# Double-checked locking with a process-wide
# ``_BLOB_URI_LOCKS_META_LOCK`` closes the race by serialising
# the dict-mutation step. The fast path (lock already in dict)
# is uncontended; the slow path (lock creation) is held under
# the meta-lock exactly once per URI for the process lifetime.
#
# Note: the cache is keyed by ``blob_uri`` and never invalidated.
# A fight's events blob is immutable after parsing, so this is
# safe in practice; if a blob were ever overwritten in-place under
# the same URI, the cache would serve stale bytes until the worker
# restarts or the LRU entry is evicted.
_BLOB_URI_LOCKS: dict[str, threading.Lock] = {}
_BLOB_URI_LOCKS_META_LOCK = threading.Lock()


# v0.10.11+ plan 144: singleflight state for ``_cached_get_events``.
# Tracking a per-URI ``concurrent.futures.Future`` in a dict lets N
# concurrent cold-cache callers share ONE MinIO GET (1 fetcher + N-1
# ``future.result()`` waiters). The fut-dict is bounded by the latch
# above -- the latch's max-in-flight = 1 means at most one ``Future``
# can be in flight per URI at any time. Same double-checked-locking
# pattern as ``_BLOB_URI_LOCKS``: ``defaultdict.__missing__`` is NOT
# thread-safe, so we use a plain ``dict`` + meta-lock + atomic helper.
_IN_FLIGHT_FUTURES: dict[str, concurrent.futures.Future[bytes]] = {}
_IN_FLIGHT_FUTURES_META_LOCK = threading.Lock()


def _get_blob_uri_lock(blob_uri: str) -> threading.Lock:
    """Atomically fetch (or create) the per-URI latch.

    See the ``_BLOB_URI_LOCKS`` block comment for the ``defaultdict``
    race rationale. The fast path is a single dict lookup; the slow
    path (first caller for a new URI) holds the meta-lock long
    enough to create + insert a single ``Lock`` instance.
    """
    lock = _BLOB_URI_LOCKS.get(blob_uri)
    if lock is not None:
        return lock
    with _BLOB_URI_LOCKS_META_LOCK:
        lock = _BLOB_URI_LOCKS.get(blob_uri)
        if lock is None:
            lock = threading.Lock()
            _BLOB_URI_LOCKS[blob_uri] = lock
    return lock


def _get_or_create_inflight_future(
    blob_uri: str,
) -> tuple[concurrent.futures.Future[bytes], bool]:
    """Atomically fetch (or create) the singleflight ``Future`` for one URI.

    Returns ``(future, is_fetcher)`` where ``is_fetcher True`` means
    THIS thread must run the underlying ``get_events`` and call
    ``future.set_result`` (or ``set_exception``); ``is_fetcher False``
    means another thread is the fetcher -- this thread should block
    on ``future.result()``.

    Uses the same double-checked-locking pattern as
    :func:`_get_blob_uri_lock`: the fast path is a lock-free dict
    lookup; the slow path (first caller for a new URI) re-checks
    under the meta-lock before creating + inserting a ``Future``.
    The double-check is the defaultdict-race defence: the first
    reader to win the meta-lock inserts the Future; subsequent
    readers see the inserted value on the lock-free fast path.
    """
    fut = _IN_FLIGHT_FUTURES.get(blob_uri)
    if fut is not None:
        return fut, False
    with _IN_FLIGHT_FUTURES_META_LOCK:
        fut = _IN_FLIGHT_FUTURES.get(blob_uri)
        if fut is None:
            fut = concurrent.futures.Future()
            _IN_FLIGHT_FUTURES[blob_uri] = fut
    return fut, True


@functools.lru_cache(maxsize=8)
def _cached_get_events(blob_uri: str) -> bytes:
    """LRU + singleflight-cached MinIO GET for the gzipped events blob.

    Three-cooperative layers protect concurrent cold-cache callers:

    1. ``functools.lru_cache(maxsize=8)`` -- the POST-COMPLETION
       cache (plan 014). Subsequent calls (after the future has
       resolved) hit this layer without entering the function body.
    2. The singleflight ``_IN_FLIGHT_FUTURES`` dict -- the IN-FLIGHT
       cache (plan 144). Concurrent callers on a cold cache share
       the SAME ``Future``; the fetcher runs ``get_events`` on
       its OWN thread (preserves the synchronous API -- no async
       refactor), then N-1 waiters block on ``future.result()``.
       The fetcher clears the dict entry in the ``finally`` block
       so a retry (post-exception or otherwise) starts fresh.
    3. The per-URI ``_BLOB_URI_LOCKS`` latch (plan 029) -- the
       MEMORY-PEAK cap. Belt-and-suspenders: the singleflight
       collapses the underlying fetches (1 GET per cold URI), but
       the latch bridges the nanosecond race-window between
       ``_IN_FLIGHT_FUTURES.pop()`` in the ``finally`` block and
       the lru_cache decorator's atomic cache-write at function
       return -- a 5th concurrent caller could otherwise open a
       redundant ``Future`` during that brief window. The latch
       also bounds the ``_IN_FLIGHT_FUTURES`` peak to ``maxsize=8``
       (the same bound the lru_cache uses).

    Sequential calls (post-completion) hit the ``lru_cache``
    short-circuit without entering the function body. Concurrent
    calls (cold cache) collapse to a single MinIO GET + N-1
    ``future.result()`` waits. Exceptions (e.g. ``S3Error``)
    propagate to all N waiters via ``future.set_exception`` +
    ``future.result()`` re-raise; the dict entry is cleared so a
    retry starts a fresh fetch.
    """
    future, is_fetcher = _get_or_create_inflight_future(blob_uri)
    if not is_fetcher:
        # Concurrent caller: block on the in-flight future. Exceptions
        # propagate via ``future.result()`` re-raise.
        return future.result()
    # First caller on cold cache: run the fetch on THIS thread, set
    # the future + clear the dict entry, return the resolved bytes.
    try:
        with _get_blob_uri_lock(blob_uri):
            result = get_events(blob_uri)
        future.set_result(result)
        return result
    except Exception as exc:
        # Propagate to all N waiters via the future channel. ``Exception``
        # (not ``BaseException``) is the right choice: ``KeyboardInterrupt``
        # + ``SystemExit`` should propagate without enabling the broadcast,
        # so a shutdown signal aborts all N waiters independently of the
        # cache layer's success/failure semantics.
        future.set_exception(exc)
        raise
    finally:
        # Always clear the dict -- the in-flight window is closed
        # regardless of success or failure. A retry starts fresh.
        with _IN_FLIGHT_FUTURES_META_LOCK:
            _IN_FLIGHT_FUTURES.pop(blob_uri, None)


def clear_blob_caches() -> None:
    """Clear all three cache layers for test isolation.

    Equivalent to the existing ``_clear_cache`` autouse fixture
    in ``apps/api/tests/test_fights_blob_cache_thundering_herd.py`` +
    the simpler ``_clear_cache`` pattern in
    ``apps/api/tests/test_fights_blob_cache.py`` -- centralised here
    so a future wire-up into the conftest's autouse chain is a
    single-line addition (``_clear_blob_caches`` autouse on the
    apps/api/tests/ conftest).

    Order matters:

    1. ``_cached_get_events.cache_clear()`` -- drops the LRU layer.
    2. ``_BLOB_URI_LOCKS.clear()`` -- drops the per-URI locks.
       Safe to clear without acquirers -- the meta-lock's
       double-checked-locking pattern re-creates locks on next use.
    3. ``_IN_FLIGHT_FUTURES.clear()`` -- drops any unresolved Futures.
       This SHOULD always be empty (the fetcher's ``finally`` block
       pops on resolution), but a defensive clear catches any leaked
       Futures from an interrupted ``with _get_blob_uri_lock(...)``
       path on test crash.

    No-op cost: O(1) for the ``cache_clear`` + O(N) per layer where
    N is bounded by ``maxsize=8`` + any concurrent in-flight window.
    """
    _cached_get_events.cache_clear()
    _BLOB_URI_LOCKS.clear()
    _IN_FLIGHT_FUTURES.clear()


__all__ = [
    "_BLOB_URI_LOCKS",
    "_BLOB_URI_LOCKS_META_LOCK",
    "_IN_FLIGHT_FUTURES",
    "_IN_FLIGHT_FUTURES_META_LOCK",
    "_cached_get_events",
    "_get_blob_uri_lock",
    "_get_or_create_inflight_future",
    "clear_blob_caches",
]
