# Plan 051 — v0.9.16: parallelise `webhook_dispatch.dispatch_for_upload` via network-only workers

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py::dispatch_for_upload`,
plus a new private helper `_fire_post()` at module scope.

## Finding

```python
with httpx.Client(timeout=_REQUEST_TIMEOUT_S) as client:
    for sub in active_subs:
        if _dispatch_single(db, client, sub, body_bytes, upload_id_str):
            delivered_count += 1
```

The fan-out is serial. For N=20 active subscriptions with a
10s-per-POST timeout, the worst-case wall-clock is 200s — the
FastAPI `BackgroundTasks` event-loop slot is blocked for 200s,
starving the rest of the request lifecycle (response to the
`POST /uploads` client is delayed by the upload's parser time
PLUS the fan-out time).

A 10s timeout is a documented design contract (design doc §5);
collapsing the wall-clock requires parallelising the per-sub
POST, NOT shortening the per-POST timeout.

## Fix (network-only workers — Option D)

Workers do **only** the HTTP POST. The main thread retains the
single `Session`, builds the `OrmWebhookDelivery` rows from the
futures' outcomes, and commits atomically at the end.

```python
_DISPATCH_MAX_WORKERS = 4  # bounded fan-out; matches scheduler bound


def _fire_post(
    client: httpx.Client,
    url: str,
    body: bytes,
    headers: dict[str, str],
) -> dict[str, object]:
    """Pure network I/O. NO SQLAlchemy access. Thread-safe.

    Returns ``{"status_code": int | None, "error": str | None}`` so
    the main thread can build the ``OrmWebhookDelivery`` row
    deterministically after the future resolves.
    """
    try:
        resp = client.post(url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        return {"status_code": None, "error": f"{type(exc).__name__}: {exc}"}
    if resp.is_success:
        return {"status_code": resp.status_code, "error": None}
    return {"status_code": resp.status_code, "error": f"non-2xx response: {resp.status_code}"}


def dispatch_for_upload(
    session_factory: Callable[[], Session],
    upload_id: uuid_lib.UUID,
) -> None:
    with session_factory() as db:
        try:
            upload = db.get(Upload, upload_id)
            # ... (3 early-return guards unchanged) ...

            payload = {...}
            body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

            active_subs = db.execute(...).scalars().all()
            if not active_subs:
                db.commit()
                return

            upload_id_str = str(upload.id)
            client = get_shared_client()  # post-plan-052

            # Pre-compute the per-sub work in the main thread; submit
            # ONLY the network I/O to the worker pool. The main
            # thread stays the sole owner of the SQLAlchemy ``db``.
            work: list[tuple[OrmWebhookSubscription, str, dict[str, str]]] = []
            for sub in active_subs:
                if not sub.secret:
                    logger.warning("...")
                    continue
                if sub.filter_payload.get("kind") != _FILTER_KIND_UPLOAD_COMPLETED:
                    logger.debug("...")
                    continue
                delivery_id = _generate_delivery_id()
                signature = hmac.new(sub.secret.encode(), body_bytes, hashlib.sha256).hexdigest()
                headers = {
                    "Content-Type": "application/json",
                    "X-Gw2Analytics-Signature": f"sha256={signature}",
                    "X-Gw2Analytics-Delivery": delivery_id,
                    "User-Agent": USER_AGENT,
                }
                work.append((sub, delivery_id, headers))

            outcomes: dict[str, dict[str, object]] = {}
            with ThreadPoolExecutor(max_workers=_DISPATCH_MAX_WORKERS) as ex:
                futures = {
                    sub.id: (delivery_id, ex.submit(_fire_post, client, sub.url, body_bytes, headers))
                    for sub, delivery_id, headers in work
                }
                # ``as_completed`` yields futures in completion order;
                # ``future.result()`` re-raises the first worker
                # exception (MemoryError, etc.) which jumps to the
                # outer ``except Exception`` -> ``db.rollback()``.
                for sub_id, (delivery_id, fut) in futures.items():
                    outcomes[sub_id] = fut.result()

            delivered_count = 0
            for sub, delivery_id, _headers in work:
                outcome = outcomes[sub.id]
                delivery = OrmWebhookDelivery(
                    id=delivery_id,
                    subscription_id=sub.id,
                    upload_id=upload_id_str,
                    attempt=1,
                )
                delivery.payload = body_bytes
                delivery.next_attempt_at = _utcnow()
                if outcome["status_code"] is not None:
                    delivery.status_code = int(outcome["status_code"])  # type: ignore[arg-type]
                err = outcome["error"]
                if isinstance(err, str):
                    delivery.error = err
                if err is None:
                    delivery.delivered_at = _utcnow()
                    delivered_count += 1
                db.add(delivery)

            db.commit()
            logger.info(
                "webhook dispatch for upload %s: %d/%d subscriptions delivered",
                upload_id, delivered_count, len(active_subs),
            )
        except Exception:
            logger.exception(...)
            db.rollback()
            raise
```

## Why network-only workers (not shared `Session`)

`db.add()` is NOT thread-safe. SQLAlchemy 2.0's Unit-of-Work mutates
internal dicts (`_new`, `_dirty`, `_deleted`) without locks. Sharing
a single `Session` across 4 worker threads will corrupt the
identity map and produce nondeterministic INSERTs.

Per-thread `Session` (the option considered in plans 012/016) is
cleaner but breaks the per-upload atomic-commit semantic: 2 of 4
threads succeeding would force the main thread to either commit
both (losing atomicity) or roll back the successes (over-rolling
back). Network-only workers preserve the atomic commit
(`db.commit()` once after all futures resolve) AND avoid the
thread-safety hazard.

## Exception propagation under `ThreadPoolExecutor`

`as_completed` + `future.result()` is the standard pattern: the
first worker exception propagates synchronously to the main
thread on the `.result()` call. The outer `try/except` catches
it, calls `db.rollback()` (no partial INSERTs were committed
because `db.commit()` runs only at the end), and re-raises.
In-flight worker threads orphan cleanly (their HTTP POSTs
finish or time out independently) — the orphan is benign
because the delivery rows they would have produced are not
written.

## `httpx.Client` lifetime

`client = get_shared_client()` returns the module-level
singleton (post-plan 052). The `ThreadPoolExecutor`'s workers
share the same client — `httpx.Client` is documented
thread-safe (the underlying `httpcore.ConnectionPool` is
guarded by an `RLock`). The `ThreadPoolExecutor` does NOT
own the client; it only owns the work-submission lifecycle.

## Why `max_workers=4`

- The webhook scheduler (plan 016) uses 4 workers for the
  same fan-out shape; consistency.
- Postgres default `max_connections=100`. With N=8 uvicorn
  workers × 5 pool_size (post-plan 040) = 40 connections
  baseline. The dispatch workers do NOT use the pool (no SQL
  in the workers), so the bound is independent of the DB
  pool.
- An integrator with 100 active subscriptions sees
  100/4 = 25 sequential 10s-timeout waves = 250s worst-case.
  A `max_workers=8` would halve that to 125s. The constant
  is exposed as a `Settings` field (`webhook_dispatch_max_workers`)
  for operator tuning without a code change.

## Risks

- `httpx.Client` singleton (plan 052) must land FIRST. If plan
  051 ships without 052, the `with httpx.Client(...)` line
  needs to be retained; that's a one-line edit at most.
- The `body_bytes` is read-only and shared across workers (no
  mutation); `sub.url`, `sub.secret` are read-only attributes
  on detached ORM objects. Both are thread-safe to read.
- `_utcnow()` is called in the main thread only (for
  `next_attempt_at` and `delivered_at`) — the `ThreadPoolExecutor`
  workers do NOT call `_utcnow()`. Side benefit: no
  thread-safety concern on the timezone-aware `datetime.now(UTC)`.
- The 4 worker threads' `httpx.Client.post()` calls contend on
  the shared `httpcore.ConnectionPool` RLock. Under
  `_DISPATCH_MAX_WORKERS=4` and 10s per POST, the contention
  is negligible vs the wire time.

## Tests

1. `test_fan_out_uses_thread_pool` — patch
   `concurrent.futures.ThreadPoolExecutor` with a `MagicMock`; call
   `dispatch_for_upload(...)`; assert the executor was instantiated
   with `max_workers=4` and `.submit()` was called once per active
   subscription.
2. `test_fan_out_serializes_outcome_to_main_thread` — patch
   `_fire_post` to return `{"status_code": 200, "error": None}`;
   call `dispatch_for_upload(...)`; assert exactly one `OrmWebhookDelivery`
   per active subscription is `db.add()`-ed with `status_code=200`
   and `delivered_at` set.
3. `test_fan_out_partial_failure_continues` — patch `_fire_post`
   to return `{"status_code": None, "error": "ConnectError: ..."}`
   for one sub and `{"status_code": 200, "error": None}` for
   another; call `dispatch_for_upload(...)`; assert 2 delivery
   rows committed, one with `error=...`, one with
   `delivered_at=...`.
4. `test_fan_out_worker_exception_triggers_rollback` — patch
   `_fire_post` to raise `MemoryError` for one sub; call
   `dispatch_for_upload(...)`; assert `db.rollback()` was called
   and ZERO delivery rows are persisted (the `MemoryError`
   propagates to the outer `try/except` before `db.commit()`).
5. `test_fan_out_atomic_commit_under_all_success` — N=10 active
   subs, all return 200; assert exactly ONE `db.commit()` call
   (not N).
6. `test_fire_post_returns_outcome_dict` — direct unit test of
   `_fire_post(client, url, body, headers)` against a mocked
   `httpx.Client`; assert the dict shape.

## Rejected alternatives

- **Share the `Session` across workers**: thread-unsafe; corrupts
  the UoW. Rejected.
- **Per-thread `Session` with manual flush**: loses per-upload
  atomic-commit semantic. Rejected.
- **`asyncio.gather` + `httpx.AsyncClient`**: would require
  making `dispatch_for_upload` async, which propagates to the
  FastAPI `BackgroundTasks` registration site (sync
  `BackgroundTasks.add_task(dispatch_for_upload, ...)`). The
  `asyncio.to_thread` wrap at the registration site is feasible
  but adds a second concurrency layer (asyncio loop + thread
  pool) for a marginal benefit. Rejected.
- **Cap `_DISPATCH_MAX_WORKERS` at 8 instead of 4**: doubles
  the wall-clock improvement but doubles the `httpcore.RLock`
  contention. 4 is the sweet spot for typical N=10-50 fan-out.
  The `Settings` field allows operator tuning.
- **No fan-out (status quo)**: 200s BG-task block for N=20
  subs is unacceptable.
