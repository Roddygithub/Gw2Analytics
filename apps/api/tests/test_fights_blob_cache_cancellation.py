"""v0.10.13 plan 029: singleflight cleanup on CancelledError/KeyboardInterrupt.

Pins the ``BaseException``-broadcast contract added in plan 029:
the fetcher's ``except`` clause was broadened from ``Exception``
to ``BaseException`` so ``asyncio.CancelledError`` /
``KeyboardInterrupt`` / ``SystemExit`` (Python 3.9+:
``BaseException``-derived) propagate to the N waiters via
``future.set_exception`` instead of leaving them stuck on an
unresolved ``future.result()``.

Pre-plan-144 narrowing to ``Exception`` was defensible because
the pre-singleflight (latch-only) implementation had no shared
``Future`` -- waiters were on independent lock acquisitions.
Post-plan-144 (singleflight adds a shared Future), the narrowing
is INCORRECT: the N waiters block on ``future.result()`` of the
shared ``Future``, and if the fetcher raises ``BaseException``
WITHOUT broadcasting, the waiters hang forever.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import gzip
import threading
import time

import pytest

from gw2analytics_api.routes.fights.blob_cache import (
    _IN_FLIGHT_FUTURES,
    _cached_get_events,
    clear_blob_caches,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    """Ensure a clean singleflight state for every test (no leaked Futures).

    The ``apps/api/tests/conftest.py`` autouse chain should already
    call :func:`clear_blob_caches` between tests; the local mirror
    here is defensive (independent of conftest wiring).

    No return annotation: this is a generator fixture (uses ``yield``)
    and mypy requires ``Generator[...]`` to annotate it. Leaving the
    return type implicit is the simplest expression of the contract.
    """
    clear_blob_caches()
    yield
    clear_blob_caches()


def test_cancelled_error_in_fetcher_broadcasts_to_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CancelledError raised in get_events is set on the Future + propagates to waiters.

    Pre-plan-029: ``except Exception as exc:`` did NOT catch
    ``BaseException``-derived ``asyncio.CancelledError``. The
    fetcher's exception propagated WITHOUT calling
    ``future.set_exception``, so the N waiters blocked on
    ``future.result()`` forever -- silent hang.

    Post-plan-029: ``except BaseException as exc:`` catches
    ``CancelledError``, calls ``future.set_exception(exc)``, all N
    waiters see the same ``CancelledError`` via ``future.result()``
    re-raise, and the ``finally`` block clears the in-flight Future
    from the dict so a retry starts fresh.
    """
    fired = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        fired["n"] += 1
        # ``time.sleep`` BEFORE the raise so the N-1 waiter threads
        # have time to enter ``_get_or_create_inflight_future`` and
        # register as waiters via the shared ``Future``. Without the
        # sleep the fetcher's exception+finally cycle completes
        # BEFORE the other 3 threads even read the dict, so each
        # becomes its own separate fetcher and ``fired["n"]`` ends
        # at 4 (not 1). The pre-existing
        # ``test_singleflight_collapses_to_single_fetcher`` test uses
        # the same ``sleep(0.05)`` for the same reason -- the sleep
        # is the latch + singleflight's serialisation window.
        time.sleep(0.05)
        # Simulate an asyncio task cancellation that propagated into
        # a sync ``future.result()`` call inside the underlying minio
        # client (the cancellation links back to a parent asyncio
        # future that was cancelled mid-fetch).
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.blob_cache.get_events",
        fake_get_events,
    )

    barrier = threading.Barrier(4)
    capture: list[tuple[bytes | None, BaseException | None]] = [
        (None, None)
    ] * 4

    def call(idx: int) -> None:
        barrier.wait(timeout=2.0)
        try:
            bytes_result = _cached_get_events("s3://bucket/events/CANCELLED.jsonl.gz")
            capture[idx] = (bytes_result, None)
        except BaseException as exc:
            capture[idx] = (None, exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(call, range(4)))

    # Exactly 1 fetcher ran (singleflight collapsed 4 concurrent
    # callers to 1 underlying fetch); the 3 waiters blocked on
    # ``future.result()``.
    assert fired["n"] == 1, (
        f"Singleflight failed to dedupe 4 concurrent callers: "
        f"get_events fired {fired['n']} times (expected 1)"
    )

    # All 4 callers see the CancelledError via the future broadcast.
    exceptions = [exc for _, exc in capture if exc is not None]
    successes = [res for res, _ in capture if res is not None]
    assert len(exceptions) == 4, (
        f"Broadcast missed: only {len(exceptions)} of 4 callers saw "
        f"the CancelledError; {len(successes)} caller(s) got stale data"
    )
    for exc in exceptions:
        assert isinstance(exc, asyncio.CancelledError), (
            f"Expected CancelledError, got {type(exc).__name__}: {exc!r}"
        )

    # The in-flight Future was cleared by the ``finally`` block.
    assert "s3://bucket/events/CANCELLED.jsonl.gz" not in _IN_FLIGHT_FUTURES, (
        f"In-flight Future leaked after CancelledError broadcast: "
        f"keys={list(_IN_FLIGHT_FUTURES.keys())}"
    )


def test_keyboard_interrupt_in_fetcher_broadcasts_to_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KeyboardInterrupt raised in get_events is set on the Future + propagates to waiters.

    Same contract as the CancelledError test but with a
    SIGINT-flavoured exception (``KeyboardInterrupt`` is
    ``BaseException``-derived in Python 3.9+, NOT ``Exception``).
    The pre-plan-029 ``except Exception`` narrowing did NOT catch
    ``KeyboardInterrupt``. The plan 029 broadening to
    ``BaseException`` makes the broadcast fire for SIGINT too.
    """
    fired = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        fired["n"] += 1
        # Same serialisation window as the CancelledError test above:
        # sleep so the N-1 waiter threads can register via the shared
        # ``Future`` BEFORE the fetcher's signal fires.
        time.sleep(0.05)
        # Simulate a SIGINT arriving mid-fetch (e.g. operator hits
        # Ctrl-C during an arq worker shutdown but the cache module
        # processes the signal only on the ``finally``-bracketed
        # section).
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.blob_cache.get_events",
        fake_get_events,
    )

    barrier = threading.Barrier(4)
    capture: list[tuple[bytes | None, BaseException | None]] = [
        (None, None)
    ] * 4

    def call(idx: int) -> None:
        barrier.wait(timeout=2.0)
        try:
            bytes_result = _cached_get_events("s3://bucket/events/CTRLC.jsonl.gz")
            capture[idx] = (bytes_result, None)
        except BaseException as exc:
            capture[idx] = (None, exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(call, range(4)))

    assert fired["n"] == 1, (
        f"Singleflight failed to dedupe on KeyboardInterrupt path: "
        f"fired {fired['n']} times (expected 1)"
    )

    exceptions = [exc for _, exc in capture if exc is not None]
    successes = [res for res, _ in capture if res is not None]
    assert len(exceptions) == 4, (
        f"KeyboardInterrupt broadcast missed: only {len(exceptions)} "
        f"of 4 callers saw the exception; {len(successes)} saw stale data"
    )
    for exc in exceptions:
        assert isinstance(exc, KeyboardInterrupt), (
            f"Expected KeyboardInterrupt, got {type(exc).__name__}: {exc!r}"
        )

    assert "s3://bucket/events/CTRLC.jsonl.gz" not in _IN_FLIGHT_FUTURES, (
        f"In-flight Future leaked after KeyboardInterrupt: "
        f"keys={list(_IN_FLIGHT_FUTURES.keys())}"
    )


def test_normal_broadcast_cleans_up_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy-path invariant: N callers share 1 fetch + the dict is empty after success.

    Pins the invariant that the ``finally`` block fires for SUCCESS,
    not only for exceptions. Guards against a future refactor that
    drops the ``finally`` while keeping the ``except BaseException``
    block (which would re-introduce the leak for the SUCCESS path
    on retry).
    """
    fired = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        fired["n"] += 1
        # Visible delay so the singleflight window is observable by
        # the 4 concurrent callers (each caller waits on the barrier
        # before entering the function body).
        time.sleep(0.05)
        return gzip.compress(b"event")

    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.blob_cache.get_events",
        fake_get_events,
    )

    barrier = threading.Barrier(4)

    def call(_: int) -> bytes:
        barrier.wait(timeout=2.0)
        return _cached_get_events("s3://bucket/events/SUCCESS.jsonl.gz")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(call, range(4)))

    # Singleflight collapsed 4 callers to 1 fetch on the SUCCESS path.
    assert fired["n"] == 1, (
        f"Singleflight failed to dedupe on success path: fired "
        f"{fired['n']} times (expected 1)"
    )
    # All 4 callers received the same bytes (the fetcher's output,
    # broadcast via ``future.set_result`` + 3x ``future.result()``).
    # Compare on the DECOMPRESSED payload (NOT raw bytes): gzip.compress
    # stamps a fresh OS-mtime into the gzip header, so raw bytes
    # differ even when the underlying payload is identical.
    assert all(gzip.decompress(r) == b"event" for r in results), (
        f"Success-path broadcast missed: not all callers received "
        f"bytes that decompress to the shared ``b'event'`` payload"
    )

    # The in-flight Future was cleared by the ``finally`` block.
    assert "s3://bucket/events/SUCCESS.jsonl.gz" not in _IN_FLIGHT_FUTURES, (
        f"In-flight Future leaked after SUCCESS: "
        f"keys={list(_IN_FLIGHT_FUTURES.keys())}"
    )
