# Plan 010 — v0.9.3: SSRF DNS rebind on webhook dispatch

**Author:** senior-advisor audit (improve skill, standard effort) — selected by maintainer (top-3 by leverage).
**Drift base:** `44ea862` (origin/main HEAD at plan authoring — `docs(readme): clarify v0.9.x status wording`).
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** an executor model with NO prior context. All file paths, excerpts, and verification commands are absolute.

---

## Why this matters

The current SSRF defense (`_validate_webhook_url` in `routes/webhooks.py:117-186`) is invoked **only** at subscription creation (`POST /api/v1/webhooks`). The dispatch workers (`webhook_dispatch.py::_dispatch_single`, `webhook_scheduler.py::_attempt_retry`) post to `sub.url` without re-evaluating the IP block. Between subscription creation and dispatch — seconds, minutes, or hours later — an attacker can:

1. Register `https://attacker.com/hook` (a public hostname that passes the gate).
2. Update the DNS A record to `10.0.0.1` (RFC1918 private) or `169.254.169.254` (AWS IMDS) before the first dispatch lands.
3. The dispatch worker reads `sub.url` from the DB (which still says `https://attacker.com/hook`), honors `client.post(...)`, and `httpx` re-resolves at the moment of the POST — now landing the request inside the internal network.

This is a **TOCTOU race** between our `_validate_webhook_url` check and the actual `httpx.post`. The plan narrows the window to a single per-dispatch check that re-runs the same `_resolved_address_is_blocked` helper.

This is **defense-in-depth**, not airtight: a malicious DNS resolver that returns a public IP under our check and a private IP 50 ms later (during `httpx.post`'s own resolution) would still bypass. The canonical airtight fix is **network-level egress filtering** — out of scope; operators must deploy egress rules separately. This plan closes the realistic attack vectors (long-rebind, attacker who controls DNS TTL).

---

## Files IN scope

- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` — `_dispatch_single`.
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` — `_attempt_retry`.
- `apps/api/src/gw2analytics_api/routes/webhooks.py` — extract the IP-block helper to a shared module.
- `apps/api/src/gw2analytics_api/_webhook_security.py` — **NEW** (private utility module; the extracted, worker-callable IP block).
- `apps/api/tests/test_webhooks_e2e.py` — add 3 regression tests.
- `CONTRIBUTING.md` — 1-line addition cross-referencing the new module docstring.

## Files NOT in scope (explicit)

- `apps/api/src/gw2analytics_api/main.py` (no FastAPI wiring change).
- `web/` (frontend unaffected).
- The create-time check in `routes/webhooks.py::_validate_webhook_url` itself — this plan only ADDS the dispatch-time check; the create-time check stays.
- Any Alembic migration (no schema change).
- Network egress rules / OS-level firewall (operator responsibility; out of scope for this repo).

---

## Current code (read from `44ea862`)

### `routes/webhooks.py:117-186` — the create-time check

```python
def _validate_webhook_url(url: str) -> None:
    """HTTPS-or-localhost policy per design doc §7.3 + v0.9.1 plan 005
    universal SSRF block on resolved addresses.
    ...
    """
    if any(ch.isspace() for ch in url):
        raise HTTPException(status_code=422, detail="webhook url must not contain whitespace")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(...)
    if not parsed.hostname:
        raise HTTPException(...)
    if parsed.scheme == "http":
        hostname = (parsed.hostname or "").lower()
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(...)
    if not os.environ.get("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS") and \
        _resolved_address_is_blocked(parsed.hostname):
        raise HTTPException(...)
```

### `routes/webhooks.py:103-150` — the blocking helpers (also kept by `_resolved_address_is_blocked` + `_ip_is_blocked`)

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


def _ip_is_blocked(addr):
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast)
```

### `webhook_dispatch.py::_dispatch_single` — the vulnerable path (around line 178-200)

```python
def _dispatch_single(db, client, sub, body_bytes, upload_id_str) -> bool:
    if not sub.secret:
        logger.warning(...); return False
    if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED:
        logger.debug(...); return False
    delivery_id = _generate_delivery_id()
    signature = hmac.new(sub.secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {...}
    delivery = OrmWebhookDelivery(id=delivery_id, subscription_id=sub.id, upload_id=upload_id_str, attempt=1)
    delivery.payload = body_bytes
    delivery.next_attempt_at = _utcnow()
    db.add(delivery)
    try:
        resp = client.post(sub.url, content=body_bytes, headers=headers)  # ← NO SSRF re-check
    except httpx.HTTPError as exc:
        delivery.error = f"{type(exc).__name__}: {exc}"
        return False
    ...
```

The same `client.post(sub.url, ...)` exists in `webhook_scheduler.py::_attempt_retry` (around line 178-185).

---

## Step-by-step

### Step 1 — Extract the IP-block helpers to a shared module

Create `apps/api/src/gw2analytics_api/_webhook_security.py`:

```python
"""v0.9.3 plan 010: shared SSRF block helpers for both subscribe-time
(create) and dispatch-time (per-attempt) URL validation.

Single source of truth so the create-time check and the
dispatch-time check cannot drift. Both call sites honor the same
``GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS`` opt-out env (read on
every call so a server restart is not required to flip the gate).
"""
from __future__ import annotations

import ipaddress
import os
import socket

_BLOCKED_KIND_PRIVATE = "private"
_BLOCKED_KIND_LOOPBACK = "loopback"
_BLOCKED_KIND_LINK_LOCAL = "link_local"
_BLOCKED_KIND_MULTICAST = "multicast"
_BLOCKED_KIND_DNS_FAIL = "dns_failure"


def _ip_kind(addr):
    if addr.is_private: return _BLOCKED_KIND_PRIVATE
    if addr.is_loopback: return _BLOCKED_KIND_LOOPBACK
    if addr.is_link_local: return _BLOCKED_KIND_LINK_LOCAL
    if addr.is_multicast: return _BLOCKED_KIND_MULTICAST
    return ""


def _resolved_address_kind(hostname: str) -> str:
    """Return the kind of the first resolved IP that is private / loopback /
    link_local / multicast, or '' if none. Fail-closed on DNS errors.
    """
    if not hostname:
        return _BLOCKED_KIND_DNS_FAIL
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        addr = None
    if addr is not None:
        return _ip_kind(addr)
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, TimeoutError):
        return _BLOCKED_KIND_DNS_FAIL
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        kind = _ip_kind(addr)
        if kind:
            return kind
    return ""


class WebhookUrlBlockedError(Exception):
    """Raised from worker context when a stored URL resolves to a
    private/loopback/link-local/multicast address (DNS rebind defence)."""

    def __init__(self, url: str, kind: str) -> None:
        self.url = url
        self.kind = kind
        match kind:
            case _BLOCKED_KIND_DNS_FAIL:
                msg = f"webhook url {url!r} DNS resolution failed at dispatch time"
            case _:
                msg = (
                    f"webhook url {url!r} resolves to a {kind} address "
                    f"at dispatch time (DNS rebind defence)"
                )
        super().__init__(msg)


def assert_url_safe_for_dispatch(url: str) -> None:
    """Re-resolve ``url`` and raise :class:`WebhookUrlBlockedError` if
    any resolved IP is private/loopback/link-local/multicast OR DNS
    fails. Honors the same ``GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS``
    opt-out as the create-time check (read on every call).

    Call this BEFORE every outbound POST in
    :mod:`workers.webhook_dispatch` and :mod:`workers.webhook_scheduler`.
    """
    if os.environ.get("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS"):
        return
    # Use ``urlparse`` for the hostname extraction (defensive
    # against the case where the stored URL has a scheme we didn't
    # validate at create time due to a future bug — we still
    # re-resolve the hostname regardless).
    from urllib.parse import urlparse
    hostname = (urlparse(url).hostname or "").strip()
    kind = _resolved_address_kind(hostname)
    if kind:
        raise WebhookUrlBlockedError(url, kind)
```

### Step 2 — Wire the dispatch-time check into the workers

**`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`** — in `_dispatch_single`, immediately AFTER the `sub.secret` / `sub.filter_payload.kind` early-outs and BEFORE `client.post(...)`:

```python
from gw2analytics_api._webhook_security import (
    WebhookUrlBlockedError,
    assert_url_safe_for_dispatch,
)

def _dispatch_single(db, client, sub, body_bytes, upload_id_str) -> bool:
    if not sub.secret:
        logger.warning("webhook subscription %s empty secret; skip", sub.id)
        return False
    if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED:
        logger.debug("..."); return False

    # v0.9.3 plan 010: re-resolve the URL at dispatch time to
    # defend against DNS rebind between create and dispatch.
    # Raises WebhookUrlBlockedError; we treat it as a non-recoverable
    # failure (the rebind is the operator's choice to allow).
    try:
        assert_url_safe_for_dispatch(sub.url)
    except WebhookUrlBlockedError as exc:
        delivery = OrmWebhookDelivery(id=delivery_id, subscription_id=sub.id, upload_id=upload_id_str, attempt=1)
        delivery.payload = body_bytes
        delivery.next_attempt_at = _utcnow()
        delivery.error = f"url blocked at dispatch: {exc.kind}"
        db.add(delivery)
        logger.warning("webhook dispatch blocked: %s sub=%s", exc, sub.id)
        return False

    delivery_id = _generate_delivery_id()
    # ... (rest of the function unchanged)
```

**`apps/api/src/gw2analytics_api/workers/webhook_scheduler.py`** — analogous insertion in `_attempt_retry` BEFORE the `client.post(...)`. On `WebhookUrlBlockedError` mark `delivery.attempt = _MAX_ATTEMPTS` so the next scheduler tick promotes the row to DLQ (consistent with "subscription missing/revoked" treatment).

### Step 3 — Update `routes/webhooks.py` to USE the shared helper

Replace the `_resolved_address_is_blocked` + `_ip_is_blocked` helpers in `routes/webhooks.py` with imports from `_webhook_security.py` (or keep thin re-exports for back-compat). Update `_validate_webhook_url` to call `_resolved_address_kind(parsed.hostname)` and produce the existing 422 message via the captured kind.

### Step 4 — Add the regression tests

In `apps/api/tests/test_webhooks_e2e.py` (or a NEW `apps/api/tests/test_webhooks_e2e_resolve.py`):

```python
"""v0.9.3 plan 010: SSRF DNS-rebind regression tests."""
from __future__ import annotations

import os
import time
from unittest.mock import patch

import httpx
import pytest
import respx


@pytest.fixture(autouse=True)
def _no_private_opt_out(monkeypatch):
    monkeypatch.delenv("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", raising=False)


def test_dispatch_blocks_rebind_to_private_ip(monkeypatch, ...):
    """Register against public IP, dispatch after DNS rebinds to private."""
    # Use the existing _post_minimal_fight + create_webhook helpers
    # from test_uploads_e2e.py / test_webhooks_e2e.py.
    # At create: socket.getaddrinfo returns ("1.2.3.4", 443) (TEST-NET-3 public).
    # At dispatch: socket.getaddrinfo returns ("10.0.0.1", 443) (RFC1918).
    create_resolutions = [("1.2.3.4", 443)]
    dispatch_resolutions = [("10.0.0.1", 443)]

    with patch("socket.getaddrinfo", side_effect=_selective_resolution(create_resolutions, dispatch_resolutions)):
        # ... register the subscription, trigger an upload, await
        # completion, assert the delivery row's `error` contains
        # `kind == "private"` AND respx recorded zero outbound POSTs.
        ...


def test_dispatch_bypass_when_env_allows(monkeypatch, ...):
    """GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1 lets the rebind through."""
    monkeypatch.setenv("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", "1")
    # ... same monkeypatch pattern but the rebind target is private.
    # Assert: outbound POST happens.


def test_retry_promotes_to_dlq_on_blocked_rebind(...):
    """Retry path treats blocked rebind as a non-recoverable failure."""
    # ... at scheduler tick, socket.getaddrinfo returns private.
    # Assert: delivery row promoted to OrmWebhookDlq with
    # last_error containing "kind=private".
```

(Note: the `respx` library **IS** thread-safe in its mock state on v0.21+; verify via the dispatch assertion. If it isn't, route the test through the single-shot path explicitly.)

### Step 5 — Update CONTRIBUTING.md

Add a 1-line cross-reference:

```markdown
## SSRF defense (v0.9.3)

Webhook URLs are re-resolved on every dispatch (initial + retries) to defend
against DNS rebind between subscription creation and the actual POST.
See ``apps/api/src/gw2analytics_api/_webhook_security.py`` for the shared
helper and the opt-out ``GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS`` env.
```

---

## Verification commands

```bash
# Lint + type-check the whole repo.
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy --no-incremental libs apps

# Existing webhook tests still pass (no behavior change for benign DNS).
uv run pytest apps/api/tests/test_webhooks_e2e.py apps/api/tests/test_webhooks_e2e_scheduler.py -v
# Expected: 22 pass + 1 skip (the existing Windows-only concurrent-replay skip).

# New rebind tests pass.
uv run pytest apps/api/tests/test_webhooks_e2e_resolve.py -v
# Expected: 3 pass.

# Full pytest suite stays green.
uv run pytest apps/api/tests/ -v
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/_webhook_security.py` (NEW)
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (1 helper call added; rest unchanged)
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (same)
- `apps/api/src/gw2analytics_api/routes/webhooks.py` (refreshed imports)
- `apps/api/tests/test_webhooks_e2e_resolve.py` (NEW)
- `apps/api/tests/test_webhooks_e2e.py` (minor: no API change)
- `CONTRIBUTING.md` (1 section)

---

## Maintenance note

- The TOCTOU window between `assert_url_safe_for_dispatch` and `httpx.post` is roughly 1-50 ms (Python function-call overhead + the DNS roundtrip `httpx` does itself). An attacker who can poison DNS for &lt; 50 ms could still slip through. CAVEAT — document in any operator-facing runbook: the canonical airtight fix is **network-level egress filtering** (iptables/nftables on the host or a Kubernetes NetworkPolicy that blocks outbound from the API pod except to a known allowlist of webhook receivers). This plan does NOT implement egress filtering.
- The DNS resolution adds ~1-50 ms per dispatch per subscriber. The dispatch runs as a FastAPI BackgroundTask; the latency is amortized after the response is sent and does not impact the user-facing POST /uploads contract.
- The shared module (`_webhook_security.py`) is the single source of truth for the block list. Any future block addition (CARRIER-GRADE NAT, IPv6 ULA, etc.) lands in ONE place — `_ip_kind` — and both create + dispatch paths inherit it.
- DO NOT add asyncio.to_thread wrapping around `assert_url_safe_for_dispatch` — the dispatch worker is sync (FastAPI BackgroundTask `add_task` runs sync code). `socket.getaddrinfo` blocking the dispatch is acceptable because the dispatch already spends milliseconds in HMAC computation and DB writes.

## Escape hatches

- If a future worker (e.g. Arq-migrated) needs async dispatch, wrap the call site in `asyncio.to_thread(...)` and translate `WebhookUrlBlockedError` to `httpx.HTTPError` semantics. Out of scope for this plan; document in a followup.
- If the regression tests prove flaky due to `respx` thread-safety (unlikely in 0.21+, but possible), pin the new tests to single-thread Postgres fixtures only — the existing 22 tests already verify multi-row flows.
- If the `_split_cors_origins`-style validator pattern needs to be DRY-ed across more fields in the future, extract a separate `_config_validator` module — out of scope here.
