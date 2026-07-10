# Plan 052 — v0.9.16: shared `httpx.Client` pool + shared worker constants

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (sync `dispatch_for_upload`),
`apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (async `lifespan_scheduler`),
`apps/api/src/gw2analytics_api/main.py` (lifespan startup/shutdown hook),
`apps/api/src/gw2analytics_api/workers/__init__.py` (new export surface).

## Finding

`webhook_dispatch.py` and `webhook_scheduler.py` both build a fresh
`httpx.Client(timeout=_REQUEST_TIMEOUT_S)` on every call:

- `webhook_dispatch.dispatch_for_upload` opens a client for the duration
  of one upload's fan-out (N subscriptions) and closes it on exit.
- `webhook_scheduler.process_scheduled_retries` opens a client for the
  duration of one 5s poll tick and closes it on exit.

The 10s `_REQUEST_TIMEOUT_S` is identical in both files; the
`_USER_AGENT` differs by patch version (`"Gw2Analytics-Webhook/0.9.0"`
vs `"Gw2Analytics-Webhook/0.9.1"`) which is itself a smell (drift
between dispatch + retry wire identity).

Per-call `httpx.Client()` construction tears down the underlying
HTTP/1.1 keep-alive connection pool every cycle. For a busy
installation (1 upload/s = 1 dispatch/s, scheduler at 0.2 Hz = 12
client re-builds/min) the TLS handshake + TCP connection setup is
real CPU + real latency on every outbound POST.

The same `_utcnow()` helper is duplicated in `models.py`,
`webhook_dispatch.py`, and `webhook_scheduler.py` (3 copies).

## Fix

1. Create `apps/api/src/gw2analytics_api/workers/_pool.py`:
   - Module-level `_shared_client: httpx.Client | None = None`.
   - `get_shared_client() -> httpx.Client` lazy-init helper.
   - `async def close_shared_client() -> None` for lifespan shutdown.
   - Expose the 3 cross-worker constants:
     - `REQUEST_TIMEOUT_S = 10.0`
     - `USER_AGENT = "Gw2Analytics-Webhook/0.9.1"` (canonical, single source)
     - `utcnow() -> datetime` (single source for `_utcnow()`)
2. `webhook_dispatch.py`: replace `with httpx.Client(timeout=...)` with
   `client = get_shared_client()`; drop the `with` block. Stop importing
   `_utcnow` / `_REQUEST_TIMEOUT_S` / `_USER_AGENT` locally; import from
   `_pool`.
3. `webhook_scheduler.py`: same refactor (drop the `with httpx.Client`
   block in `process_scheduled_retries`; import the 3 symbols from
   `_pool`).
4. `main.py`: add `await close_shared_client()` to the lifespan
   shutdown path (after the existing `lifespan_scheduler` cancel
   point).
5. `models.py`: drop the local `_utcnow`; import `utcnow` from
   `_pool`. (`models.py` is not strictly a worker module but the
   helper is identical and the cycle (`models` → `database` → `Base`)
   does not transitively pull workers, so the import is safe.)
6. Update `workers/__init__.py` to re-export the 3 symbols so
   tests can monkeypatch via `workers.utcnow` / `workers.REQUEST_TIMEOUT_S`.

## Thread-safety

`httpx.Client` is documented thread-safe (it uses a single
`httpcore.ConnectionPool` internally guarded by an `RLock`). The
`webhook_dispatch` plan 051 (fan-out via `ThreadPoolExecutor`) is
safe BECAUSE the client is shared at module scope — per-worker
client construction would have made the fan-out require N clients
(also OK, but the shared-client model is canonical).

## Risks

- `_shared_client` lazy-init must be idempotent and tolerate multiple
  callers racing on first dispatch (FastAPI's `BackgroundTasks` + the
  lifespan scheduler both call into `_pool`). Use a module-level
  `threading.Lock` around the lazy init.
- Lifespan shutdown must close the client even if it was never opened
  (defensive `if _shared_client is not None: await _shared_client.aclose()`).
- Drop the `with httpx.Client(...) as client:` blocks — the client
  lifetime now spans the FastAPI process, not the function call.
  Adjust unit-test fixtures that previously asserted the client was
  closed on function exit (none today, but a future regression to
  catch with a test).

## Tests

1. `test_shared_client_is_singleton` — call `get_shared_client()` 2×;
   assert `is` identity.
2. `test_close_shared_client_is_idempotent` — call `close_shared_client()`
   2× without any `get_shared_client()`; assert no exception.
3. `test_close_releases_underlying_httpcore` — open + close; assert
   `client.is_closed` (httpx 0.27+ exposes this).
4. `test_dispatch_uses_shared_client` — monkeypatch
   `_pool._shared_client` with a `MagicMock`; call
   `dispatch_for_upload(...)`; assert the patched client's
   `.post(...)` was invoked (NOT a fresh `httpx.Client`).
5. `test_scheduler_uses_shared_client` — same pattern for
   `process_scheduled_retries`.
6. `test_models_uses_pool_utcnow` — assert `models.utcnow is _pool.utcnow`.

## Rejected alternatives

- **One client per fan-out cycle (today)**: leaves the connection
  pool tear-down in place; doesn't help the scheduler.
- **One client per worker thread (plan 051 model)**: works, but
  complicates the lifespan shutdown (need a registry of clients to
  close). Module-level singleton + lazy init is simpler.
- **`lru_cache(maxsize=1)` on `get_shared_client`**: works but the
  closure semantics + the lazy-init lock are easier to reason about
  with a module-level `None` sentinel + an explicit `threading.Lock`.
