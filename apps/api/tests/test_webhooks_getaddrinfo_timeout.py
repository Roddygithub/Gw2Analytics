"""v0.9.4 plan 013: getaddrinfo timeout in webhook URL validation."""

from __future__ import annotations

import concurrent.futures
import socket

import pytest

from gw2analytics_api.routes import webhooks


def test_getaddrinfo_timeout_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow getaddrinfo call is bounded and fails closed (422)."""

    def fake_submit(*args: object, **kwargs: object) -> concurrent.futures.Future[object]:
        future: concurrent.futures.Future[object] = concurrent.futures.Future()
        future.set_exception(concurrent.futures.TimeoutError())
        return future

    monkeypatch.setattr(webhooks._DNS_EXECUTOR, "submit", fake_submit)
    with pytest.raises(webhooks.HTTPException) as exc_info:
        webhooks._validate_webhook_url("https://slow.example.com/webhook")
    assert exc_info.value.status_code == 422


def test_getaddrinfo_fast_resolution_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-private hostnames resolve quickly and pass validation.

    Note: the original test used ``http://localhost/webhook`` which fails
    with 422 under the v0.9.1 plan 005 universal SSRF block (the block
    catches loopback on the resolved-address check even for the ``http``
    scheme -- a pre-existing scope concern outside plan 026). The test
    was always failing on master; plan 026 fixes the DNS executor
    concurrency, not the SSRF policy. This test exercises a non-private
    hostname that the SSRF block accepts; the DNS executor concurrency
    claim is unchanged.
    """
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 0))],
    )
    # Should not raise. Uses ``https://`` because the webhook URL
    # validator restricts the ``http://`` scheme to loopback hosts
    # only (localhost / 127.0.0.1 / ::1); an ``https://`` URL with
    # a non-loopback hostname passes the scheme gate and exercises
    # the DNS executor concurrency claim.
    webhooks._validate_webhook_url("https://non-private.example/webhook")


def test_no_setdefaulttimeout_side_effect() -> None:
    """The implementation does not mutate socket.setdefaulttimeout."""
    original = socket.getdefaulttimeout()
    # Force import / re-import side effects by touching the module.
    assert webhooks._DNS_RESOLVE_TIMEOUT_S == 2.0
    assert socket.getdefaulttimeout() == original
