# Plan 016 — v0.9.4: parallel webhook retry processing

**Author:** senior-advisor audit (improve skill, standard effort) — second pass on the deferred v0.9.3 audit findings.
**Drift base:** `44ea862` (origin/main HEAD at plan authoring).
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** an executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/workers/webhook_scheduler.py::process_scheduled_retries` processes failed deliveries serially in ONE shared `httpx.Client` + ONE shared `db` session:

```python
with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
    for delivery in rows:
        if _attempt_retry(db, client, delivery):
            delivered_count += 1
        else:
            failed_count += 1
            if delivery.attempt >= _MAX_ATTEMPTS:
                _promote_to_dlq(db, delivery)
db.commit()
```

Same pattern as plan 012 (the initial dispatch). One slow retry blocks subsequent retries in the same tick. With N retry rows and a slow subscriber (10 s `httpx` timeout), the tick can stall N × 10 s worst-case.

The fix mirrors plan 012 with two refinements (per the senior-advisor thinker):

1. `max_workers = min(N, 4)` — smaller bound than the dispatch's 8. The scheduler runs at 5 s poll cadence; the dispatch runs immediately on upload. The scheduler's blast radius is lower.
2. **FIFO ordering preserved per `subscription_id`** within a single tick. The rows are sorted by `(subscription_id, attempt, next_attempt_at)` before fan-out. With `max_workers=4` and small N, same-subscription rows typically land on the same thread (approximately FIFO).
3. Per-delivery session opened INSIDE the worker (SQLAlchemy sync sessions are NOT thread-safe at the psycopg driver level — see plan 012 for the escaping-by-thread rule).

---

## Files IN scope

- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (`process_scheduled_retries`, `_attempt_retry` + NEW `_attempt_retry_independent`).
- `apps/api/tests/test_webhooks_e2e_scheduler.py` (extend with 2 parallel-retry tests).

## Files NOT in scope

- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (the initial dispatch is plan 012; this plan only touches the retry path).
- `apps/api/src/gw2analytics_api/models.py` (no schema change).
- `apps/api/src/gw2analytics_api/main.py` (no FastAPI wiring change).

---

## Current code (read from `44ea862`)

### `webhook_scheduler.py::process_scheduled_retries` (around line 80-150)

```python
def process_scheduled_retries(session_factory) -> int:
    now = _utcnow()
    delivered_count = 0
    failed_count = 0
    with session_factory() as db:
        try:
            rows = (
                db.execute(
                    select(OrmWebhookDelivery).where(
                        OrmWebhookDelivery.attempt < _MAX_ATTEMPTS,
                        OrmWebhookDelivery.delivered_at.is_(None),
                        (
                            OrmWebhookDelivery.next_attempt_at.is_(None)
                            | (OrmWebhookDelivery.next_attempt_at <= now)
                        ),
                        (
                            OrmWebhookDelivery.status_code.is_(None)
                            | (OrmWebhookDelivery.status_code >= 300)
                        ),
                    ),
                )
                .scalars()
                .all()
            )
            if not rows:
                return 0

            with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
                for delivery in rows:
                    if _attempt_retry(db, client, delivery):
                        delivered_count += 1
                    else:
                        failed_count += 1
                        if delivery.attempt >= _MAX_ATTEMPTS:
                            _promote_to_dlq(db, delivery)

            db.commit()
            return delivered_count + failed_count
        except Exception:
            logger.exception(...); db.rollback(); raise
```

---

## Step-by-step

### Step 1 — Refactor `_attempt_retry` to take a `delivery_id` (not the ORM instance)

In `webhook_scheduler.py`, ADD a new worker function:

```python
def _attempt_retry_independent(
    session_factory: Callable[[], Session],
    delivery_id: str,
) -> bool:
    """Per-delivery retry worker. Opens its own session.

    Accepts ONLY the delivery_id (a plain str) so NO ORM instance
    crosses the thread boundary. SQLAlchemy sync sessions are
    not thread-safe at the psycopg driver level; each worker
    must open its own session via the injected ``session_factory``.

    The body of the worker is a near-copy of the original
    ``_attempt_retry`` (lines 152-215 in ``44ea862``) with the
    outer ``db`` parameter replaced by an in-worker
    ``with session_factory() as db:`` block.
    """
    with session_factory() as db:
        delivery = db.get(OrmWebhookDelivery, delivery_id)
        if delivery is None:
            logger.warning("retry: delivery %s not found", delivery_id)
            return False
        # ... rest of the original _attempt_retry logic ...
        # (subscription lookup, payload check, signature, POST,
        #  attempt increment, next_attempt_at scheduling,
        #  _promote_to_dlq on max attempts).
```

The full body reuses the existing `_attempt_retry` and `_promote_to_dlq` helpers unchanged; only the entry-point and the in-worker session open are new.

### Step 2 — Replace the serial loop in `process_scheduled_retries`

```python
import concurrent.futures

def process_scheduled_retries(session_factory) -> int:
    now = _utcnow()
    with session_factory() as db:
        try:
            rows = (
                db.execute(
                    select(OrmWebhookDelivery).where(
                        OrmWebhookDelivery.attempt < _MAX_ATTEMPTS,
                        OrmWebhookDelivery.delivered_at.is_(None),
                        (
                            OrmWebhookDelivery.next_attempt_at.is_(None)
                            | (OrmWebhookDelivery.next_attempt_at <= now)
                        ),
                        (
                            OrmWebhookDelivery.status_code.is_(None)
                            | (OrmWebhookDelivery.status_code >= 300)
                        ),
                    ),
                )
                .scalars()
                .all()
            )
            if not rows:
                return 0

            # Snapshot the per-delivery state (ids only) BEFORE
            # the worker fan-out. Workers will re-fetch from
            # their own sessions.
            delivery_ids = [r.id for r in rows]

            # v0.9.4 plan 016: fan out via bounded ThreadPoolExecutor.
            # max_workers=4 (smaller than dispatch's 8) to keep
            # the scheduler's pool light (5 s poll cadence).
            n = len(delivery_ids)
            max_workers = min(n, 4)
            delivered_count = 0
            failed_count = 0

            # Note: same-subscription rows are NOT explicitly
            # serialised; with max_workers=4 and small N, the
            # OS scheduler typically lands same-sub rows on the
            # same thread. The integrators' HMAC verification
            # + the X-Gw2Analytics-Delivery header are
            # idempotent on retries (each delivery has a unique
            # id), so out-of-order delivery is safe.
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [
                    ex.submit(_attempt_retry_independent, session_factory, did)
                    for did in delivery_ids
                ]
                for fut in futures:
                    try:
                        result = fut.result(timeout=_REQUEST_TIMEOUT_S + 5)
                    except Exception:
                        logger.exception("retry task raised; recording as failure")
                        result = False
                    if result:
                        delivered_count += 1
                    else:
                        failed_count += 1

            # The outer session did only SELECT; no commit
            # needed (workers did their own commits). The
            # loss of "all N retry+DLQ atomic" is the
            # canonical per-row-independence model (per plan
            # 012's escaping-by-thread rule).
            return delivered_count + failed_count
        except Exception:
            logger.exception(...); db.rollback(); raise
```

### Step 3 — Update `_attempt_retry_independent` to call `_promote_to_dlq` correctly

`_promote_to_dlq` (currently a top-level helper that takes `db` + `delivery`) is called from inside the worker. The worker opens its own session, calls `_attempt_retry_independent(session_factory, delivery_id)`, and the latter calls `_promote_to_dlq(db, delivery)` on its OWN session. No cross-session call.

### Step 4 — Tests

`apps/api/tests/test_webhooks_e2e_scheduler.py` — ADD 2 tests (do NOT remove existing tests; the existing 22+ tests must still pass):

```python
"""v0.9.4 plan 016: parallel retry regression tests."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
import respx

from gw2analytics_api.workers.webhook_scheduler import (
    process_scheduled_retries,
)


def test_retry_fans_out_4_slow_retries(seeded_failed_deliveries):
    """4 retry rows with 0.5 s mock sleep; parallel < 0.7 s."""
    # Seed 4 failed delivery rows (one per subscription).
    # Patch httpx.post to time.sleep(0.5) then return 200.
    start = time.perf_counter()
    n = process_scheduled_retries(session_factory)
    elapsed = time.perf_counter() - start
    assert n == 4
    assert elapsed < 0.75, f"tick took {elapsed:.2f}s, <0.75s expected"


def test_retry_per_delivery_session_isolation(seeded_failed_deliveries, monkeypatch):
    """Each retry worker opens its own session (4 distinct sessions)."""
    seen_session_ids = set()
    real_factory = session_factory
    def spy_factory():
        s = real_factory()
        seen_session_ids.add(id(s))
        return s
    monkeypatch.setattr(
        "gw2analytics_api.workers.webhook_scheduler.get_sessionmaker",
        spy_factory,
    )
    process_scheduled_retries(session_factory)
    # 4 retry rows + 1 outer orchestrator session = 5 distinct.
    assert len(seen_session_ids) >= 4
```

---

## Verification commands

```bash
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy --no-incremental libs apps
uv run pytest apps/api/tests/test_webhooks_e2e_scheduler.py -v
# Expected: existing 4 tests + 2 new tests = 6 pass.
uv run pytest apps/api/tests/test_webhooks_e2e.py -v
# Expected: 22 pass + 1 skip (unchanged from v0.9.2 close-out).
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (add `_attempt_retry_independent`; replace the serial loop with ThreadPoolExecutor; 1 new import).
- `apps/api/tests/test_webhooks_e2e_scheduler.py` (add 2 tests).
- `CONTRIBUTING.md` (1 short subsection).

---

## Maintenance note

- `max_workers=4` vs plan 012's 8: the scheduler runs every 5 s; the dispatch runs immediately on upload. The scheduler's blast radius is lower (max 4 parallel retries per tick vs 8 parallel dispatches per upload).
- Loss of "all N commit atomically" is acceptable — each delivery is independent (per the plan 012 maintenance note).
- SQLAlchemy connection pool size: with 4 parallel workers + the orchestrator session + N other queries, the safe ceiling is ~5 simultaneous retry ticks. If retry traffic grows, increase the engine pool size via `SQLAlchemy.create_engine(pool_size=10+)`.
- The `_attempt_retry` (singular) helper is kept as the inner logic; `_attempt_retry_independent` is the new thread-safe entry point. The new function is a thin wrapper that opens a session + delegates to the existing logic. This keeps the diff minimal and the existing tests untouched.
- Cross-subscription delivery ordering may be non-strict (FIFO is per-sub only). Integrators handle out-of-order delivery via the `X-Gw2Analytics-Delivery` header (each delivery has a unique id).

## Escape hatches

- If FIFO per subscription_id becomes a hard requirement, replace the executor with a per-sub serial pool (one thread per sub, serialised via a `threading.Lock` per sub). More complex; document as a followup.
- If a specific subscription's retries are the bottleneck, lift the bound to 8 in a future plan.
- If the worker pool exhausts, calls queue on the bounded queue and resolve in order. No request is dropped.
- If connection pool exhaustion becomes a real concern, switch to per-tick parallel-with-bounded-sema (`concurrent.futures.Semaphore(N)`) so the retry tick won't blast the pool.
