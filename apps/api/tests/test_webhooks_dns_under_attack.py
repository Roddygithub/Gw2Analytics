"""v0.10.10 plan 026: DNS-under-attack invariants.

Simulates the canonical DoS scenario: a slow DNS resolver blocks the
executor worker. The post-fix contract is that concurrent legitimate
POSTs are NOT starved by a single attacker's POST (i.e. ``max_workers=1``
was the vulnerability; ``max_workers=32`` closes it).

All test URLs use ``https://`` for non-loopback hostnames. The webhooks
validation policy (``routes/webhooks.py``) restricts the ``http`` scheme
to loopback hosts only (localhost / 127.0.0.1 / ::1); an ``http://`` URL
with a non-loopback hostname would fail with 422 BEFORE the DNS
executor even runs. The universal SSRF block (v0.9.1 plan 005) catches
loopback on the resolved-address check, so a literal ``http://localhost``
also fails. The test URLs therefore use ``https://`` with a
monkeypatched ``getaddrinfo`` returning a non-private IP (1.2.3.4) to
exercise the DNS executor path in isolation.
"""

from __future__ import annotations

import concurrent.futures
import socket
import threading
import time
from contextlib import suppress

import pytest
from fastapi import HTTPException

from gw2analytics_api.routes import webhooks
from gw2analytics_api.routes.webhooks import _DNS_RESOLVE_TIMEOUT_S


def _make_getaddrinfo_with_per_hostname_latency(
    tarpit_hostname_substring: str = "tarpit",
    tarpit_sleep_s: float = _DNS_RESOLVE_TIMEOUT_S * 1.5,
    fast_sleep_s: float = 0.005,
    resolved_ip: str = "1.2.3.4",
) -> object:
    """Build a fake getaddrinfo that sleeps based on hostname substring.

    Returns a callable suitable for ``monkeypatch.setattr(socket, "getaddrinfo", ...)``.
    Hostnames containing ``tarpit_hostname_substring`` sleep ``tarpit_sleep_s`` and
    return an empty list (causing the SSRF gate to fail-closed). All other
    hostnames sleep ``fast_sleep_s`` and resolve to ``resolved_ip``.
    """

    def fake_getaddrinfo(hostname: str, *args: object, **kwargs: object) -> object:
        if tarpit_hostname_substring in hostname:
            # Tarpit path: sleep past the timeout, then raise
            # ``gaierror`` so the SSRF gate fails CLOSED (returns True
            # via the ``except (socket.gaierror, ...)`` clause in
            # ``_resolved_address_is_blocked``). An empty-list return
            # would NOT fail-closed; see the saturation test for the
            # full reasoning.
            time.sleep(tarpit_sleep_s)
            raise socket.gaierror(-2, "Name or service not known (tarpit)")
        time.sleep(fast_sleep_s)
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (resolved_ip, 0))]

    return fake_getaddrinfo


def test_legitimate_user_not_blocked_by_attacker_slow_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow ``getaddrinfo`` does NOT chain-block the pool.

    Pre-fix: 1 slow DNS eats the sole worker for 2-3s; the next call
    also blocks on the executor queue; ``future.result(timeout=2.0)``
    raises; ``except TimeoutError: return True`` fail-closes the URL.
    Post-fix: 1 slow DNS uses 1/32 workers; 31 free workers serve
    legitimate concurrent POSTs.
    """
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _make_getaddrinfo_with_per_hostname_latency(
            tarpit_hostname_substring="tarpit.attacker.example",
            tarpit_sleep_s=_DNS_RESOLVE_TIMEOUT_S * 1.5,
        ),
    )

    slow_done = threading.Event()
    fast_done = threading.Event()

    def slow_thread() -> None:
        # The slow hostname blocks on the 3.0s sleep; _resolved_address_is_blocked()
        # eventually returns ``True`` (the tarpit returns empty list -> fail-closed),
        # then the 422 fires.
        with suppress(HTTPException):
            webhooks._validate_webhook_url("https://tarpit.attacker.example/webhook")
        slow_done.set()

    def fast_thread() -> None:
        # The fast hostname resolves in 5ms to 1.2.3.4 (non-private) -- the URL must
        # NOT be blocked. The thread must complete well before the slow thread.
        webhooks._validate_webhook_url("https://fast-allowed.example/webhook")
        fast_done.set()

    t_slow = threading.Thread(target=slow_thread)
    t_fast = threading.Thread(target=fast_thread)
    t_slow.start()
    # Give the slow thread time to enqueue (otherwise it may finish before fast starts).
    time.sleep(0.01)
    t_fast.start()
    t_fast.join(timeout=_DNS_RESOLVE_TIMEOUT_S + 1.0)
    t_slow.join(timeout=_DNS_RESOLVE_TIMEOUT_S + 1.0)

    # The fast thread must have completed (no DoS starvage from the slow attacker).
    # The crucial signal is fast_done (whether the fast thread completed),
    # not wallclock (which would be ~3.0s for the slow thread regardless).
    assert fast_done.is_set(), "Fast URL was blocked by the slow attacker!"
    assert slow_done.is_set(), "Slow thread never completed"


def test_concurrent_burst_does_not_starve_legitimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 slow + 5 fast concurrent POSTs all complete within 4.0 seconds."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _make_getaddrinfo_with_per_hostname_latency(),
    )

    def validate(url: str) -> None:
        with suppress(HTTPException):
            webhooks._validate_webhook_url(url)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    futures = [
        pool.submit(validate, url)
        for url in [f"https://tarpit-{i}.attacker.example/webhook" for i in range(5)]
        + ["https://fast-allowed.example/webhook"] * 5
    ]
    concurrent.futures.wait(futures, timeout=_DNS_RESOLVE_TIMEOUT_S * 2.0)
    pool.shutdown(wait=False)

    # All 10 must complete within 2x the per-caller timeout.
    # With 32 workers + 5 slow @ 3.0s + 5 fast @ 5ms: total wallclock ~3.0s
    # (slows run in parallel + fasts run in parallel); the 4.0s timeout is safe.
    assert all(f.done() for f in futures), (
        "Executor is serialising concurrent submissions: 10 URLs did not complete within 4.0s"
    )


def test_pool_saturation_gracefully_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """100 simultaneous tarpit DNS lookups all resolve to 422 (no partial-success)."""

    # v0.10.10 plan 026 fix: isolate the global ``_DNS_EXECUTOR`` to
    # prevent abandoned futures from polluting subsequent tests.
    # The 100 inner ``getaddrinfo`` calls sleep for 2.0s; with 32
    # workers, 100 tasks take ~6.25s to drain, but the test's outer
    # ``wait`` times out at 5.0s and abandons ~20 futures on the
    # executor queue. Those abandoned futures would otherwise queue
    # on the global ``_DNS_EXECUTOR`` and starve the NEXT test's
    # 2.0s ``future.result(timeout)`` fence (the next test's
    # ``getaddrinfo`` call queues behind 20+ still-pending
    # ``gaierror``-raising tasks, times out, and fails closed
    # with 422). Swapping in a test-scoped ``ThreadPoolExecutor``
    # confines the abandoned futures to this test; the global
    # ``_DNS_EXECUTOR`` is clean for the next test.
    test_dns_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=webhooks.DNS_POOL_MAX_WORKERS,
        thread_name_prefix="test_saturation",
    )
    monkeypatch.setattr(webhooks, "_DNS_EXECUTOR", test_dns_pool)

    def fake_getaddrinfo(hostname: str, *args: object, **kwargs: object) -> object:
        # All hostnames are tarpit: sleep past the timeout, then
        # raise ``gaierror`` so the SSRF gate fails CLOSED. Returning
        # an empty list would NOT fail-closed (``for info in infos``
        # is a no-op on an empty list, so the route returns False =
        # "not blocked" and the URL passes validation -> 200, not
        # 422). Raising ``gaierror`` matches the
        # ``except (socket.gaierror, ...)`` clause in
        # ``_resolved_address_is_blocked`` and routes to ``return True``
        # -> the 422 fires.
        time.sleep(_DNS_RESOLVE_TIMEOUT_S * 1.0)
        raise socket.gaierror(-2, "Name or service not known (tarpit)")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def validate(url: str) -> int:
        try:
            webhooks._validate_webhook_url(url)
        except HTTPException as exc:
            return exc.status_code
        return 200  # unexpected (would mean the SSRF gate did not fire)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=100)
    try:
        futures = [
            pool.submit(validate, f"https://tarpit-{i}.attacker.example/webhook")
            for i in range(100)
        ]
        concurrent.futures.wait(futures, timeout=_DNS_RESOLVE_TIMEOUT_S * 2.5)

        assert all(f.done() for f in futures), (
            "Saturated pool (100 concurrent tarpit DNS) stalled: "
            "not all submissions completed within 5.0s"
        )
        results = {f.result() for f in futures}
        # Each URL must have produced a 422 (fail-closed); no 200 leaks through.
        assert results == {422}, "unexpected status codes: " + repr(results)
    finally:
        pool.shutdown(wait=False)
        # Drain the isolated pool to avoid leaking threads after the
        # monkeypatch is reverted (the next test sees the global
        # ``_DNS_EXECUTOR`` again, but the isolated pool's worker
        # threads are still running in the background). ``wait=False``
        # is consistent with the outer pool's teardown.
        test_dns_pool.shutdown(wait=False)
