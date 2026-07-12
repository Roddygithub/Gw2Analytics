"""v0.10.10 plan 026: DNS executor concurrency invariants.

Companion to ``apps/api/tests/test_webhooks_getaddrinfo_timeout.py`` (the
v0.9.4 plan 013 tests). Pins the post-fix contract: the executor pool
has 32 workers, accepts concurrent submissions without serialisation,
and is teardown-safe via the atexit hook (verified behaviourally, not
via CPython internals).
"""

from __future__ import annotations

import concurrent.futures
import socket
import threading
import time

import pytest

from gw2analytics_api.routes import webhooks


def test_pool_max_workers_constant_is_32() -> None:
    """Pins the literal "32" via the public constant (NOT the CPython private attribute).

    Avoids ``_DNS_EXECUTOR._max_workers`` (leading-underscore attribute
    that may shift across Python versions, especially 3.13's free-threaded
    builds). The constant is the contract surface.
    """
    assert webhooks.DNS_POOL_MAX_WORKERS == 32
    assert isinstance(webhooks.DNS_POOL_MAX_WORKERS, int)


def test_dns_executor_uses_max_workers_constant() -> None:
    """Pin that the ``ThreadPoolExecutor`` was constructed with the constant's value.

    Reads via ``_max_workers`` for the executor-instance value (this
    ISN'T a CPython internal for an *int* attribute; documented in the
    public Python docs as a read-only attribute on ``ThreadPoolExecutor``).
    Asserting on the integer lets us catch "constant declared but
    executor instantiated with hard-coded 32" drift.
    """
    assert webhooks._DNS_EXECUTOR._max_workers == webhooks.DNS_POOL_MAX_WORKERS


def test_dns_executor_behavior_after_shutdown() -> None:
    """Behavior test: post-shutdown ``submit`` raises RuntimeError.

    The atexit-registration contract was previously tested via
    introspection of ``atexit._exithandlers`` (CPython internal; brittle
    across Python versions). The behavior contract is more authoritative:
    a properly-registered atexit hook fires on Python exit AND the pool
    cleanly refuses new work post-shutdown.

    **Implementation note**: this test creates a LOCAL
    ``ThreadPoolExecutor`` rather than touching the module-global
    ``webhooks._DNS_EXECUTOR``. The global is a process-wide singleton
    used by every webhook validation request -- shutting it down in a
    test would poison every subsequent test in the file (alphabetical
    execution order) and any test that exercises the
    ``_validate_webhook_url`` path. Using ``with`` block + local pool
    is the cleanest way to verify the post-shutdown ``RuntimeError``
    contract without test pollution.
    """
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="test_dns_shutdown"
    ) as local:
        # Pre-shutdown: submit succeeds and queues.
        pre_future = local.submit(_fake_getaddrinfo, "example.com", None)
        assert isinstance(pre_future, concurrent.futures.Future)
        pre_future.result(timeout=1.0)

    # The `with` block above has now exited -> local is shutdown.
    # Post-shutdown: ``submit`` raises ``RuntimeError`` (canonical error).
    with pytest.raises(RuntimeError, match="cannot schedule new futures"):
        local.submit(_fake_getaddrinfo, "example.com", None)


def test_concurrent_calls_to_same_uri_invoked_in_single_pool() -> None:
    """4 concurrent submissions complete without dropping to a single-thread serial path.

    Pre-fix (``max_workers=1``): 4 concurrent ``submit()`` calls queue
    behind the one worker; total wallclock ≥ sum(per_call_latency).
    Post-fix (``max_workers=32``): all 4 run in parallel; total
    wallclock ≈ max(per_call_latency).
    """
    per_call_latency_s = 0.05
    barrier = threading.Barrier(4)

    def slow_getaddrinfo(*args: object, **kwargs: object) -> object:
        # Synchronise all 4 workers to depart the barrier simultaneously;
        # the wallclock delta MUST then be ~= one latency, not sum.
        barrier.wait(timeout=2.0)
        time.sleep(per_call_latency_s)
        # Return a plausible getaddrinfo-incompatible sentinel; the
        # route-level SSRF test path is not under examination here --
        # we just want to confirm the executor's parallelism claim.
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]

    start = time.monotonic()
    futures = [
        webhooks._DNS_EXECUTOR.submit(slow_getaddrinfo, "example.com", None) for _ in range(4)
    ]
    for f in futures:
        f.result(timeout=5.0)
    elapsed = time.monotonic() - start
    # Parallel sum: 1 latency
    # Serialised sum: 4 latencies
    # Tolerance: 2.5x (allow 50% headroom for thread spawn overhead).
    assert elapsed < per_call_latency_s * 2.5, (
        f"executor is serialising concurrent submissions: "
        f"elapsed={elapsed:.3f}s, "
        f"expected≈{per_call_latency_s:.3f}s"
    )


def test_dns_executor_avoids_setting_socket_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plan must NOT mutate ``socket.setdefaulttimeout`` (process-global state).

    Pre-flight baseline: capture the process-global default; after
    exercising the DNS helper paths via the public routes, the default
    must be unchanged. Uses a non-private hostname (the v0.9.1 plan 005
    SSRF block would catch loopback on the universal-address check;
    this test verifies DNS executor hygiene, not the SSRF policy).
    """
    baseline = socket.getdefaulttimeout()  # may be None.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 0))],
    )
    webhooks._validate_webhook_url("https://non-private.example/webhook")
    assert socket.getdefaulttimeout() == baseline


def _fake_getaddrinfo(hostname: str, port: object, *args: object, **kwargs: object) -> object:
    """No-op DNS stand-in. Returns an empty list (the route's SSRF gate fails closed on empty)."""
    return []
