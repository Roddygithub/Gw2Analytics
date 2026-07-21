# Plan 012 — v0.9.3: Webhook dispatch parallelised across N subscribers

**Author:** senior-advisor audit (improve skill, standard effort) — selected by maintainer (top-3 by leverage).
**Drift base:** `44ea862` (origin/main HEAD at plan authoring).
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** an executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` runs dispatch serially inside ONE FastAPI BackgroundTask:

```python
# webhook_dispatch.py around line 138-141
with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
    for sub in active_subs:
        if _dispatch_single(db, client, sub, body_bytes, upload_id_str):
            delivered_count += 1
```

For `N` active subscribers, wallclock is `O(N × _REQUEST_TIMEOUT_S = N × 10s)` worst-case. A single slow recipient (the 10 s `httpx` timeout firing on a TCP hang) stalls every subsequent subscriber. With **10** subscribers and one slow integration, an upload takes up to **100 seconds** of background-task time — competing with `process_parse` and `dispatch_for_upload` for the same FastAPI threadpool.

The fix: fan out via `concurrent.futures.ThreadPoolExecutor`, per-sub session so SQLAlchemy session connection state is never shared across threads.

### Critical constraint (per the senior-advisor thinker)

> SQLAlchemy sync sessions are NOT thread-safe at the DB driver level (a single `psycopg` connection cannot be shared across threads). The plan MUST open `with session_factory() as db:` INSIDE each worker function — NOT pass a shared session into the executor — and MUST NOT pass any ORM model instance across thread boundaries. Pass plain-typed data (`dict[str, str | object]`) into the worker; the worker hydrates ORM instances from its own session.

The plan accepts the loss of "all N deliveries commit atomically": each delivery row is its own target of truth (success OR failure OR DLQ are independent states). The current "all-or-nothing commit" pattern was inherited from when the dispatch was a single-FastAPI-request flow; with parallelisation, the per-row independence is the canonical model.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` — extract `_deliver_for_sub`, replace the serial loop with a ThreadPoolExecutor.
- `apps/api/tests/test_webhooks_dispatch_e2e.py` — **NEW** (parallel-dispatch specific tests; mirrors the existing `test_webhooks_e2e_scheduler.py` module split).
- `apps/api/tests/test_webhooks_e2e.py` — minor refresh of one assertion that asserted serial timing.

## Files NOT in scope

- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` — dispatch retry is per-delivery in a single tick, not N-rows-per-tick. Per-tick parallelisation is a separate concern; deferred.
- `apps/api/src/gw2analytics_api/database.py` — `session_factory` already exists.
- `apps/api/src/gw2analytics_api/models.py` — `OrmWebhookDelivery` schema unchanged.
- `web/` — frontend unaffected.

---

## Current code (read from `44ea862`)

### `webhook_dispatch.py::dispatch_for_upload` (around line 78-145)

```python
def dispatch_for_upload(
    session_factory: Callable[[], Session],
    upload_id: uuid_lib.UUID,
) -> None:
    with session_factory() as db:
        try:
            upload = db.get(Upload, upload_id)
            if upload is None:
                logger.warning(...); return
            if upload.status != UPLOAD_STATUS_COMPLETED:
                logger.debug(...); return
            if upload.fight is None:
                logger.warning(...); return

            payload = {
                "kind": _FILTER_KIND_UPLOAD_COMPLETED,
                "upload_id": str(upload.id),
                "fight_id": upload.fight.id,
                "sha256": upload.sha256,
                "started_at": upload.fight.started_at.isoformat(),
            }
            body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

            active_subs = (
                db.execute(
                    select(OrmWebhookSubscription).where(
                        OrmWebhookSubscription.revoked_at.is_(None),
                    ),
                )
                .scalars()
                .all()
            )

            if not active_subs:
                logger.debug("no active webhook subscriptions; ...")
                db.commit()
                return

            upload_id_str = str(upload.id)
            delivered_count = 0
            with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
                for sub in active_subs:                                # ← SERIAL
                    if _dispatch_single(db, client, sub, body_bytes, upload_id_str):
                        delivered_count += 1

            db.commit()                                                 # ← ATOMIC
            logger.info("webhook dispatch for upload %s: %d/%d ...", ...)
        except Exception:
            logger.exception(...); db.rollback(); raise
```

### `webhook_dispatch.py::_dispatch_single` (current shape; will be split into a thread-safe primitive)

```python
def _dispatch_single(db, client, sub, body_bytes, upload_id_str) -> bool:
    """Create one delivery row, fire POST, record outcome. NO commit."""
    if not sub.secret:
        logger.warning(...); return False
    if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED:
        logger.debug(...); return False
    delivery_id = _generate_delivery_id()
    signature = hmac.new(sub.secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Gw2Analytics-Signature": f"sha256={signature}",
        "X-Gw2Analytics-Delivery": delivery_id,
        "User-Agent": _USER_AGENT,
    }
    delivery = OrmWebhookDelivery(
        id=delivery_id, subscription_id=sub.id, upload_id=upload_id_str, attempt=1,
    )
    delivery.payload = body_bytes
    delivery.next_attempt_at = _utcnow()
    db.add(delivery)
    try:
        resp = client.post(sub.url, content=body_bytes, headers=headers)
    except httpx.HTTPError as exc:
        delivery.error = f"{type(exc).__name__}: {exc}"
        return False
    delivery.status_code = resp.status_code
    if resp.is_success:
        delivery.delivered_at = _utcnow()
        return True
    delivery.error = f"non-2xx response: {resp.status_code}"
    return False
```

---

## Step-by-step

### Step 1 — Extract `_deliver_for_sub` (thread-safe primitive)

In `webhook_dispatch.py`, ADD a new top-level function:

```python
def _payload_for_sub(sub_data: dict, upload_id_str: str, fight_id: str, sha256: str, started_at) -> bytes:
    """Compute the canonical outbound body. Pure, no DB access."""
    body = {
        "kind": _FILTER_KIND_UPLOAD_COMPLETED,
        "upload_id": upload_id_str,
        "fight_id": fight_id,
        "sha256": sha256,
        "started_at": started_at.isoformat(),
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _deliver_for_sub(
    sub_data: dict[str, object],
    body_bytes: bytes,
    upload_id_str: str,
) -> dict[str, object]:
    """Thread-safe per-sub dispatch.

    Opens its OWN session (sessions are NOT safe to share across
    threads at the psycopg driver level). Passes plain dicts across
    the thread boundary — no ORM instance ever crosses a thread.

    Returns a plain dict summary so the caller (the dispatch loop)
    can aggregate results without touching the ORM models.
    """
    sub_id = sub_data["id"]
    try:
        secret = sub_data["secret"]
        url = sub_data["url"]
        kind = sub_data["filter_kind"]
    except KeyError as exc:
        return {"subscription_id": None, "delivered": False, "error": f"missing key: {exc}"}

    if not secret:
        return {"subscription_id": sub_id, "delivered": False, "error": "empty secret"}
    if kind != _FILTER_KIND_UPLOAD_COMPLETED:
        return {"subscription_id": sub_id, "delivered": False, "error": "filter mismatch"}

    delivery_id = _generate_delivery_id()
    signature = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Gw2Analytics-Signature": f"sha256={signature}",
        "X-Gw2Analytics-Delivery": delivery_id,
        "User-Agent": _USER_AGENT,
    }

    # Open a session INSIDE the worker. Never share across threads.
    from gw2analytics_api.database import get_sessionmaker
    session_factory = get_sessionmaker  # module-level singleton; thread-safe to call

    with session_factory() as db:
        delivery = OrmWebhookDelivery(
            id=delivery_id, subscription_id=sub_id, upload_id=upload_id_str, attempt=1,
        )
        delivery.payload = body_bytes
        delivery.next_attempt_at = _utcnow()
        db.add(delivery)
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
                resp = client.post(url, content=body_bytes, headers=headers)
        except httpx.HTTPError as exc:
            delivery.error = f"{type(exc).__name__}: {exc}"
            db.commit()
            return {"subscription_id": sub_id, "delivery_id": delivery_id, "delivered": False, "error": delivery.error}

        delivery.status_code = resp.status_code
        if resp.is_success:
            delivery.delivered_at = _utcnow()
            db.commit()
            return {"subscription_id": sub_id, "delivery_id": delivery_id, "delivered": True}
        delivery.error = f"non-2xx response: {resp.status_code}"
        db.commit()
        return {"subscription_id": sub_id, "delivery_id": delivery_id, "delivered": False, "error": delivery.error}
```

### Step 2 — Replace `dispatch_for_upload`'s serial loop with a ThreadPoolExecutor

In `webhook_dispatch.py`, REPLACE the block:

```python
            with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
                for sub in active_subs:
                    if _dispatch_single(db, client, sub, body_bytes, upload_id_str):
                        delivered_count += 1

            db.commit()  # was atomic across N
            # ... log info ...

        except Exception:
            logger.exception(...); db.rollback(); raise
```

With:

```python
            # Extract the data we need BEFORE leaving the outer db session.
            # We MUST NOT pass ORM instances into the worker.
            upload_id_str = str(upload.id)
            fight_id = upload.fight.id
            sha256 = upload.sha256
            started_at = upload.fight.started_at
            sub_data_list = [
                {
                    "id": s.id,
                    "url": s.url,
                    "secret": s.secret,
                    "filter_kind": s.filter_payload.get("kind"),
                }
                for s in active_subs
            ]

            # v0.9.3 plan 012: fan out via bounded ThreadPoolExecutor.
            # max_workers is bounded by min(N_subs, 8) so a 1000-subscriber
            # scale does not blast the DB connection pool (default 10).
            # The outer `with session_factory() as db:` exits normally —
            # each sub-task opens its OWN session inside _deliver_for_sub.
            from concurrent.futures import ThreadPoolExecutor
            n = len(sub_data_list)
            if n == 0:
                logger.debug("no active subscriptions; skipping")
                db.commit()
                return

            max_workers = min(n, 8)
            results: list[dict[str, object]] = []
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [
                    ex.submit(_deliver_for_sub, sub_data, body_bytes, upload_id_str)
                    for sub_data in sub_data_list
                ]
                for fut in futures:
                    try:
                        results.append(fut.result(timeout=_REQUEST_TIMEOUT_S + 5))
                    except Exception as exc:
                        logger.exception("sub-task raised; recording as failure")
                        results.append({"subscription_id": None, "delivered": False, "error": f"{type(exc).__name__}: {exc}"})

            delivered_count = sum(1 for r in results if r.get("delivered"))
            failed_count = n - delivered_count
            logger.info(
                "webhook dispatch for upload %s: %d/%d delivered (%d failed, %d workers)",
                upload_id, delivered_count, n, failed_count, max_workers,
            )
            db.commit()
        except Exception:
            logger.exception(...); db.rollback(); raise
```

The outer `with session_factory() as db:` still wraps ONLY the `upload` + `active_subs` SELECT + the now-orphan `db.commit()`. The orchestrator session is **not** shared with the workers (workers open their own).

### Step 3 — Delete the now-unused `_dispatch_single` helper

After the rewrite, `_dispatch_single` no longer has any caller. Delete it. This keeps the file line count flat and prevents future drift.

### Step 4 — Add regression tests in NEW `apps/api/tests/test_webhooks_dispatch_e2e.py`

```python
"""v0.9.3 plan 012: parallel-dispatch regression tests."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import respx


def test_dispatch_fans_out_three_slow_subscribers(monkeypatch_upload, ...):
    """Three subscribers with 0.5s mocked sleep each -- parallel = ~0.5s, not 1.5s."""
    # Seed 3 active subscriptions.
    # Use respx.mock to intercept each sub.url and time.sleep(0.5) inside the side_effect.
    # Trigger upload completion; await dispatch.
    # Measure: elapsed < 0.75s (parallel) vs expected serial 1.5s.

    start = time.perf_counter()
    # ... trigger dispatch + await ..
    elapsed = time.perf_counter() - start
    assert elapsed < 0.75, f"dispatch took {elapsed:.2f}s, parallel <0.75s expected"


def test_dispatch_per_sub_session_isolation(...):
    """Each sub-task instantiates its OWN session (SQLAlchemy thread-safety)."""
    session_ids = []
    real_session_factory = ...  # spy on session_factory()
    def spy_factory():
        s = real_session_factory()
        session_ids.append(id(s))
        return s
    monkeypatch.setattr("gw2analytics_api.workers.webhook_dispatch.get_sessionmaker", spy_factory)
    # ... trigger 3-sub dispatch ...
    # Assert: 3 distinct session instances.


def test_dispatch_atomicity_loss_is_acceptable(...):
    """A failing sub in the middle doesn't cancel sibling successes."""
    # Seed 3 subs: sub-1 succeeds (200), sub-2 throws in handler (5xx),
    # sub-3 succeeds (200).
    # After dispatch: sub-1 + sub-3 delivery rows have delivered_at set;
    # sub-2's delivery row exists with status_code=500 + error set.
    # No rollback erases sub-1 or sub-3 (the parallel-per-row semantics).


def test_dispatch_bounded_max_workers_eight(...):
    """20 active subscribers: max_workers = min(20, 8) = 8."""
    # Seed 20 subs. Spy on ThreadPoolExecutor(max_workers=...).
    # Assert the executor receives max_workers=8.
```

---

## Verification commands

```bash
# Lint + type-check.
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy --no-incremental libs apps

# Existing webhook tests still pass (post-refactor).
uv run pytest apps/api/tests/test_webhooks_e2e.py apps/api/tests/test_webhooks_e2e_scheduler.py -v
# Expected: 22 pass + 1 skip.

# New parallel-dispatch tests pass.
uv run pytest apps/api/tests/test_webhooks_dispatch_e2e.py -v
# Expected: 4 pass.

# Full pytest suite stays green.
uv run pytest apps/api/tests/ -v
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (extract `_deliver_for_sub` + ThreadPoolExecutor wiring + delete old `_dispatch_single`).
- `apps/api/tests/test_webhooks_dispatch_e2e.py` (NEW).
- `apps/api/tests/test_webhooks_e2e.py` (no API change; the v0.9.2 fixes from `abd7deb` stay untouched).
- `CONTRIBUTING.md` (1 subsection "## Webhook dispatch concurrency").

---

## Maintenance note

- `max_workers = min(N_subs, 8)` is a starting heuristic. Two followup levers if N_subs > 50:
  1. Increase `pool_size` on the SQLAlchemy engine (default 10 → 20+) to accommodate the per-sub session churn.
  2. Lift `max_workers` to a config setting (`GW2ANALYTICS_WEBHOOK_DISPATCH_MAX_WORKERS`).
- Per-sub session = N concurrent DB transactions (1 per worker). The default Postgres connection limit is 100; with 8 concurrent workers + 1 orchestrator session + N other queries, the safe ceiling is ~8 simultaneous dispatch uploads. If traffic grows, increase the engine pool size accordingly.
- Loss of atomic commit ("if delivery-2 fails, delivery-1 still lands") is the canonical per-row-independence model. The plan documents this in the function docstring so a future refactor doesn't try to restore atomicity (would require a 2-phase commit and is out of scope).
- The `body_bytes` payload is computed ONCE in the orchestrator and passed to all workers (sharing bytes is safe across threads; it is just `bytes`).

## Escape hatches

- If `respx` proves flaky under ThreadPoolExecutor in CI, route `test_dispatch_fans_out_three_slow_subscribers` to seed HTTP-delays via `time.sleep(0.5)` directly inside a custom `httpx.MockTransport`. The behavior under test is "wallclock", not the HTTP mock itself.
- If a future shift to async DB drivers (e.g. `asyncpg`) makes `session_factory` async-callable, switch the worker from `ThreadPoolExecutor` to `asyncio.gather(*[_deliver_for_sub_async(...)])`. Out of scope; document as a "when asyncpg lands" trigger.
- If `test_dispatch_bounded_max_workers_eight` proves too tight (Postgres pool default lowered), bump the bound to `min(N, 4)` as a more conservative default and adjust both plan + code.
