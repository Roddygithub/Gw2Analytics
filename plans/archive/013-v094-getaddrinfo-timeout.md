# Plan 013 — v0.9.4: getaddrinfo timeout for webhook URL validation

**Author:** senior-advisor audit (improve skill, standard effort) — second pass on the deferred v0.9.3 audit findings.
**Drift base:** `44ea862` (origin/main HEAD at plan authoring).
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** an executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/routes/webhooks.py::_resolved_address_is_blocked` calls `socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)` synchronously with **no timeout**. A malicious or slow DNS resolver can block the FastAPI route thread for as long as the resolver takes (commonly 30 s+; some resolvers never return). Combined with plan 010 (SSRF rebind) which RE-runs `_resolved_address_is_blocked` on every dispatch, a single slow DNS hostnames wedges the create + dispatch validation paths for ~60 s per attacker probe.

The naive fix (`socket.setdefaulttimeout(2.0)`) is **incorrect** — `setdefaulttimeout` mutates process-global state, and a concurrent request in the FastAPI threadpool inherits the timeout, randomly sabotaging DB connections + MinIO clients + every other socket call until the next `setdefaulttimeout(None)` reset. The canonical pattern is to offload the blocking call to a bounded `concurrent.futures.ThreadPoolExecutor` and bound the future with `.result(timeout=N)`.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/routes/webhooks.py` (`_resolved_address_is_blocked`, `_validate_webhook_url`).
- `apps/api/tests/test_webhooks_url_resolve_timeout.py` — **NEW**.

## Files NOT in scope

- `apps/api/src/gw2analytics_api/workers/*` (no DNS calls in the worker layer).
- `apps/api/src/gw2analytics_api/storage.py` (no DNS calls in the storage layer).
- `_webhook_security.py` (the module from plan 010; the resolve helper stays in `routes/webhooks.py` for this plan since it's a refinement of the existing helper, not a separate concern).

---

## Current code (read from `44ea862`)

### `routes/webhooks.py::_resolved_address_is_blocked` (around line 103-128)

```python
def _resolved_address_is_blocked(hostname: str) -> bool:
    if not hostname:
        return True
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        addr = None
    if addr is not None:
        return _ip_is_blocked(addr)
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, TimeoutError):
        return True
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _ip_is_blocked(addr):
            return True
    return False
```

---

## Step-by-step

### Step 1 — Add a module-level bounded executor

In `routes/webhooks.py`, near the top (after the imports, before `_utcnow`):

```python
import concurrent.futures

# v0.9.4 plan 013: bound the getaddrinfo call so a slow DNS resolver
# cannot starve the FastAPI threadpool. ``_dns_executor`` is a
# process-global singleton (created lazily, reused for all calls).
# 4 workers covers the realistic concurrent-validation budget
# (the create + dispatch paths each need at most 1 DNS lookup per
# webhook; 4 covers a flash burst of 4 simultaneous validations).
_DNS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="gw2a-dns-resolve",
)
_DNS_RESOLVE_TIMEOUT_S = 2.0
```

### Step 2 — Offload `getaddrinfo` to the bounded executor

REPLACE the `try: infos = socket.getaddrinfo(...)` block in `_resolved_address_is_blocked` with:

```python
    try:
        # Offload the blocking getaddrinfo to the bounded
        # executor with a .result(timeout=...) cap. The
        # ``concurrent.futures.TimeoutError`` is a subclass of
        # ``TimeoutError``, so the existing exception handler
        # below already covers it (fail-closed as blocked).
        infos = _DNS_EXECUTOR.submit(
            socket.getaddrinfo, hostname, None, socket.SOCK_STREAM
        ).result(timeout=_DNS_RESOLVE_TIMEOUT_S)
    except (socket.gaierror, TimeoutError):
        return True
```

(DO NOT touch `socket.setdefaulttimeout` — global state mutation will break concurrent requests.)

### Step 3 — Update `_validate_webhook_url` for a clearer error on timeout

The current handler maps both DNS failure and timeout to a generic "resolves to a private/loopback/link-local/multicast address" 422. After plan 013, distinguish the two cases for the operator's debugging:

```python
def _validate_webhook_url(url: str) -> None:
    # ... existing checks (whitespace, scheme, hostname, http-scheme loopback) ...
    if not os.environ.get("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS"):
        # v0.9.4 plan 013: distinguish DNS timeout from
        # resolved-blocked. Both still 422 (fail-closed), but the
        # detail message names which one so an operator can debug
        # "why did my webhook URL get rejected" without a debugger.
        from gw2analytics_api._webhook_security import (  # ← import from plan 010's module
            WebhookUrlBlockedError,
            assert_url_safe_for_dispatch,
        )
        # The create-time check uses the shared helper too (single
        # source of truth). On DNS timeout the helper raises
        # WebhookUrlBlockedError with kind="dns_failure".
        try:
            assert_url_safe_for_dispatch(url)
        except WebhookUrlBlockedError as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"webhook url {url!r} {exc}"
                ),
            ) from exc
```

(Plan 013 is a refinement of the existing helper. Plan 010's `_webhook_security.py::assert_url_safe_for_dispatch` already uses `_resolved_address_kind` which is the bounded-executor version after this plan. So Step 3 is the integration point: route-level error message uses the same helper. The executor itself lives in `routes/webhooks.py` (not `_webhook_security.py`) because the existing helper is in `routes/webhooks.py` and the route already imports it.)

### Step 4 — Add regression tests

`apps/api/tests/test_webhooks_url_resolve_timeout.py` (NEW):

```python
"""v0.9.4 plan 013: DNS resolution timeout in webhook URL validation."""
from __future__ import annotations

import socket
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from gw2analytics_api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dns_resolve_timeout_does_not_starve_route(client, monkeypatch):
    """A slow DNS resolver must be capped to ~2 s, not block indefinitely."""
    def slow_getaddrinfo(*args, **kwargs):
        time.sleep(5)
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("1.2.3.4", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)
    start = time.perf_counter()
    resp = client.post(
        "/api/v1/webhooks",
        json={"url": "https://slow.attacker.example/hook", "filter": {"kind": "upload_completed"}},
    )
    elapsed = time.perf_counter() - start
    assert resp.status_code == 422
    assert elapsed < 0.5, f"route took {elapsed:.2f}s, <0.5s expected after timeout"


def test_socket_default_timeout_unchanged(client, monkeypatch):
    """``socket.setdefaulttimeout`` MUST NOT be touched (global state hazard)."""
    before = socket.getdefaulttimeout()
    def slow_getaddrinfo(*args, **kwargs):
        time.sleep(5)
        return []
    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)
    client.post(
        "/api/v1/webhooks",
        json={"url": "https://slow.attacker.example/hook", "filter": {"kind": "upload_completed"}},
    )
    assert socket.getdefaulttimeout() == before


def test_dns_resolve_happy_path_unchanged(client, monkeypatch):
    """Normal DNS resolution still works; < 100 ms in jsdom."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))],
    )
    resp = client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/hook", "filter": {"kind": "upload_completed"}},
    )
    assert resp.status_code == 201
```

---

## Verification commands

```bash
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy --no-incremental libs apps
uv run pytest apps/api/tests/test_webhooks_url_resolve_timeout.py -v
uv run pytest apps/api/tests/test_webhooks_e2e.py apps/api/tests/test_webhooks_e2e_scheduler.py -v
uv run pytest apps/api/tests/ -v
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/routes/webhooks.py` (add `_DNS_EXECUTOR` + `_DNS_RESOLVE_TIMEOUT_S`; replace the getaddrinfo call; update `_validate_webhook_url` to use the shared helper).
- `apps/api/tests/test_webhooks_url_resolve_timeout.py` (NEW, 3 tests).
- `CONTRIBUTING.md` (1 short subsection on the DNS timeout).

---

## Maintenance note

- The `_DNS_EXECUTOR` is a process-global singleton. FastAPI workers (when the project migrates to a multi-worker gunicorn deployment) will each have their own executor instance — 4 workers per FastAPI process × N processes = 4N concurrent DNS lookups. The 2 s cap is well below the typical httpx dispatcher timeout (10 s) so the DNS path never becomes the dispatch bottleneck.
- DNS timeout is fail-closed (treated as a blocked address). An operator who accidentally subscribes a URL whose DNS takes > 2 s to resolve would see 422 on creation. The remediation is to either (a) move the URL to a faster-resolving hostname, or (b) set `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1` (NOT recommended in prod; dev-only escape hatch).
- The executor does NOT need graceful shutdown because it lives for the lifetime of the FastAPI process. On process restart, the executor is discarded (Python's atexit handles thread pool cleanup on interpreter exit; FastAPI's `lifespan` is irrelevant for this singleton).

## Escape hatches

- If a future plan migrates the route to `async def`, the canonical pattern is `asyncio.wait_for(loop.getaddrinfo(...), timeout=2.0)` instead of the executor offload. Out of scope here; document as a "when async migration lands" trigger.
- If a longer DNS timeout is needed (e.g. for a low-TTL internal hostname), lift `_DNS_RESOLVE_TIMEOUT_S` to a config field (e.g. `GW2ANALYTICS_WEBHOOK_DNS_TIMEOUT_S=5.0`).
- If the executor is ever exhausted (4 concurrent slow DNS lookups in a flash burst), new requests will queue on the executor's bounded queue and resolve in order; no request is dropped. The 2 s `.result(timeout=...)` cap applies to each call independently.
