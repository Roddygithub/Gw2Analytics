"""v0.10.10 plan 029: _cached_get_events thundering-herd latch.

Pins the latch contract: concurrent calls for the same ``blob_uri``
are SERIALISED through a per-URI ``threading.Lock`` so at most
ONE MinIO GET is in-flight at any time. The latch prevents
SIMULTANEOUS memory pressure (one decompressed blob in flight at
a time, not N); it does NOT prevent the lru_cache from being
missed (each thread still calls the underlying ``get_events``
once because the ``lru_cache`` check happens at the outer layer
and each concurrent caller sees a cache MISS until the first
caller returns).

**Implementation note on the lru_cache+lock interaction**:
``functools.lru_cache`` wraps the function and checks the cache
BEFORE the function body runs. For concurrent callers, all N see
a cache MISS, enter the function body, and contend on the lock.
The lock serialises them, but by the time the 2nd-Nth caller
acquires the lock, the 1st caller has already populated the cache
AND returned. The 2nd-Nth caller's function body still runs
(``with lock: return get_events(uri)``), so it still calls
``get_events``. The lru_cache hit DOES short-circuit the
OUTER call on subsequent (post-completion) calls, but not on
concurrent races.

A true "single-flight" pattern (one fetcher, N waiters, shared
result broadcast) would achieve ``call_count == 1``; the
canonical implementation is the ``singleflight`` library or
``concurrent.futures.Future``-based coordination. That is a
follow-up improvement; this plan's latch gives the
"memory-bounded concurrency" win (only 1 decompressed blob in
RAM at a time) which is the OOM-relevant claim.

**Why a meta-lock around the lock-dict**:
``collections.defaultdict.__missing__`` is NOT thread-safe. 4
threads accessing ``_BLOB_URI_LOCKS[uri]`` on a missing key can
each invoke the factory and each receive a DIFFERENT ``Lock``
object, defeating the latch. The production code uses a
``dict`` + a meta-lock + the ``_get_blob_uri_lock`` helper to
atomically create + insert a single ``Lock`` instance per URI.
The fast path is a single dict lookup; the slow path (first
caller for a new URI) holds the meta-lock long enough to create
+ insert ONE ``Lock`` instance for the process lifetime.
"""

from __future__ import annotations

import concurrent.futures
import gzip
import threading
import time

import pytest
from minio.error import S3Error

from gw2analytics_api.routes.fights import (
    _BLOB_URI_LOCKS,
    _cached_get_events,
    _get_blob_uri_lock,
)


class _FakeS3Error(S3Error):
    """Minimal S3Error subclass that bypasses the ``BaseHTTPResponse`` init requirement.

    ``S3Error.__init__`` requires a real ``urllib3`` ``BaseHTTPResponse`` as
    the first positional arg; constructing one by hand is noisy and
    orthogonal to the contract under test (latch exception-safety, not the
    S3Error->HTTPException translation -- that path is covered by
    ``test_fights_blob_cache.py``). Overriding ``__init__`` to call
    ``Exception.__init__`` directly preserves ``isinstance(..., S3Error)``
    (the latch + the production ``except S3Error`` in ``_load_fight_events``
    both rely on it) without the I/O plumbing.
    """

    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        # Skip S3Error.__init__ (requires BaseHTTPResponse).
        Exception.__init__(self)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cached_get_events.cache_clear()
    _BLOB_URI_LOCKS.clear()
    yield
    _cached_get_events.cache_clear()
    _BLOB_URI_LOCKS.clear()


def test_get_blob_uri_lock_is_atomic_under_concurrent_first_access() -> None:
    """Double-checked locking closes the ``defaultdict`` race on first access.

    Pre-fix (``defaultdict(threading.Lock)``): 4 threads access
    ``_BLOB_URI_LOCKS[new_uri]`` simultaneously; each sees a missing
    key; each invokes ``threading.Lock()``; each gets a DIFFERENT
    lock object; the latch is defeated (each thread holds its own
    lock, all run in parallel).

    Post-fix (meta-lock + helper): 4 threads call
    ``_get_blob_uri_lock(new_uri)`` simultaneously; the fast-path
    dict lookup returns ``None`` for all 4; only the thread that
    wins the meta-lock creates + inserts a ``Lock`` instance; the
    other 3 see the inserted value on their second look-up under
    the meta-lock. All 4 threads receive the SAME ``Lock`` object.

    This test pins the meta-lock's actual contract: the same
    ``Lock`` instance is shared across concurrent first-access
    callers.
    """
    # Use a URI the test fixture has not touched yet.
    new_uri = "s3://bucket/events/NEW_URI.jsonl.gz"
    barrier = threading.Barrier(4)

    def acquire() -> threading.Lock:
        barrier.wait(timeout=2.0)
        return _get_blob_uri_lock(new_uri)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        locks = list(pool.map(lambda _: acquire(), range(4)))

    # All 4 threads must share the SAME lock instance (identity check).
    first = locks[0]
    assert all(lock is first for lock in locks), (
        f"Meta-lock race: 4 threads received {len({id(lock) for lock in locks})} "
        f"distinct lock objects (expected 1)"
    )
    assert isinstance(first, type(threading.Lock()))


def test_concurrent_calls_to_same_uri_are_serialised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-URI lock serialises concurrent get_events calls (max-in-flight = 1).

    The latch bounds the memory footprint of concurrent reads to
    ONE decompressed blob in RAM at a time. Without the latch, 4
    parallel callers would each independently fetch + decompress
    the same 200 MB blob (the pre-fix OOM risk). With the latch,
    callers wait their turn.

    This test asserts the latch's actual contract: max concurrent
    in-flight ``get_events`` calls == 1. ``call_count`` is also
    4 (the lru_cache layer doesn't deduplicate concurrent misses;
    see module docstring), but the per-call concurrency is bounded.
    """
    in_flight = 0
    max_in_flight = 0
    in_flight_lock = threading.Lock()

    def fake_get_events(uri: str) -> bytes:
        nonlocal in_flight, max_in_flight
        with in_flight_lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)  # ensure the latch has time to serialise
        with in_flight_lock:
            in_flight -= 1
        return gzip.compress(b"event")

    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events", fake_get_events
    )

    # 4 concurrent calls on the same URI. Barrier releases them simultaneously.
    barrier = threading.Barrier(4)

    def call() -> bytes:
        barrier.wait(timeout=2.0)
        return _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: call(), range(4)))

    # All 4 callers received gzip bytes that DECOMPRESS to the same payload.
    # The raw bytes differ because each ``gzip.compress`` writes a fresh
    # timestamp into the gzip header; the latch serialises the calls
    # (``max_in_flight == 1``) but the lru_cache does NOT deduplicate
    # concurrent misses (see module docstring). Asserting on the
    # decompressed payload is the precise-but-stable contract: pytest's
    # prior flaky 1/3 behaviour stemmed from asserting raw ``results[0]``
    # equality, which passes when all 4 ``gzip.compress`` calls fall
    # within the same wallclock second (~2/3 of runs) and fails when
    # they straddle a second boundary (~1/3 of runs -- the observed
    # F1-style flake).
    assert all(gzip.decompress(r) == b"event" for r in results), (
        "At least one caller received bytes that do not decompress to "
        "the shared ``b'event'`` payload (latch breached the per-call "
        "serialisation contract)."
    )
    # The latch's actual contract: max-in-flight == 1.
    assert max_in_flight == 1, (
        f"Per-URI lock did not serialise concurrent calls: "
        f"max_in_flight={max_in_flight}, expected 1"
    )


def test_concurrent_calls_to_distinct_uris_run_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4 parallel calls to 4 distinct URIs run in parallel (no cross-URI blocking)."""
    per_call_latency_s = 0.05

    def fake_get_events(uri: str) -> bytes:
        time.sleep(per_call_latency_s)
        return gzip.compress(b"event")

    monkeypatch.setattr("gw2analytics_api.routes.fights.get_events", fake_get_events)

    barrier = threading.Barrier(4)
    uris = [f"s3://bucket/events/FIGHT{i}.jsonl.gz" for i in range(4)]

    def call(uri: str) -> bytes:
        barrier.wait(timeout=2.0)
        return _cached_get_events(uri)

    start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(call, uris))
    elapsed = time.monotonic() - start

    # Parallel wallclock: ~per_call_latency. Serial would be ~4x that.
    assert elapsed < per_call_latency_s * 2.0, (
        f"Concurrent calls to distinct URIs are serialising: "
        f"elapsed={elapsed:.3f}s, expected≈{per_call_latency_s:.3f}s"
    )


def test_lock_releases_on_exception_does_not_poison_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_events raises S3Error on first call, succeeds on second: 2 separate attempts.

    The test does not exercise the S3Error->HTTPException translation
    in :func:`_load_fight_events` (that path is covered by the
    pre-existing ``test_fights_blob_cache.py``). It pins the latch's
    exception-safety contract: a raised exception MUST release the
    per-URI lock so a retry can acquire it (the lru_cache also does
    not cache exceptions, so the retry hits the body again).
    """
    attempt = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        attempt["n"] += 1
        if attempt["n"] == 1:
            raise _FakeS3Error()
        return gzip.compress(b"event")

    monkeypatch.setattr("gw2analytics_api.routes.fights.get_events", fake_get_events)

    # First call: S3Error-shaped exception propagates to the caller.
    with pytest.raises(S3Error):
        _cached_get_events("s3://bucket/events/transient.jsonl.gz")

    # Second call: the lock has released + lru_cache didn't cache the
    # exception, so get_events fires again -> success.
    result = _cached_get_events("s3://bucket/events/transient.jsonl.gz")
    assert gzip.decompress(result) == b"event"

    assert attempt["n"] == 2, (
        f"Expected 2 get_events calls (1 exception + 1 success), got {attempt['n']}"
    )


def test_cache_maxsize_unchanged_post_fix() -> None:
    """The lock layer is orthogonal to the LRU semantics (maxsize=8 stays 8)."""
    info = _cached_get_events.cache_info()
    assert info.maxsize == 8


def test_lock_dict_keys_bounded_by_maxsize_plus_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After 9 distinct URI calls, the lock dict has at most 9 keys (one per URI)."""
    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        lambda uri: gzip.compress(b"event"),
    )

    for i in range(9):
        _cached_get_events(f"s3://bucket/events/FIGHT{i}.jsonl.gz")

    info = _cached_get_events.cache_info()
    # LRU evicts 1 entry; locks for the 8 cached URIs + 1 evicted URI
    # remain in the dict (locks are never GC'd in this design).
    assert info.currsize == 8
    assert len(_BLOB_URI_LOCKS) <= 9, (
        f"Lock dict grew beyond expected bound: {len(_BLOB_URI_LOCKS)} "
        f"keys after 9 distinct URI calls (maxsize=8)"
    )


def test_lock_dict_is_a_regular_dict() -> None:
    """Sanity: _BLOB_URI_LOCKS is a ``dict`` (NOT a ``defaultdict``).

    The ``defaultdict`` race that motivated the meta-lock is a
    silent failure (4 threads can each receive a different lock
    without raising); the production code is now a ``dict`` so a
    naive refactor back to ``defaultdict`` would re-introduce the
    race. The test pins the type so a future refactor that
    "simplifies" the helper back to ``defaultdict`` fails this
    contract check. ``defaultdict`` carries a ``default_factory``
    attribute that plain ``dict`` does not -- the absence of that
    attribute is the cheapest, import-free way to discriminate.
    """
    assert isinstance(_BLOB_URI_LOCKS, dict)
    assert not hasattr(_BLOB_URI_LOCKS, "default_factory")


def test_get_blob_uri_lock_helper_returns_same_instance() -> None:
    """``_get_blob_uri_lock`` returns the same instance on repeat calls (idempotent)."""
    a = _get_blob_uri_lock("s3://bucket/events/REPEATED.jsonl.gz")
    b = _get_blob_uri_lock("s3://bucket/events/REPEATED.jsonl.gz")
    assert a is b
    assert hasattr(a, "acquire") and hasattr(a, "release")
