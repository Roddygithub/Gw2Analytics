# Plan 026 — v0.10.10: webhook DNS executor DoS fix (`max_workers=1` → bounded concurrency)

**Stamped at:** `f0249ef` (working-tree diff HEAD; all changes in this plan live in the uncommitted working tree)
**Severity:** HIGH (security + perf)
**Category:** security, perf
**Addresses finding:** `_DNS_EXECUTOR` single-thread DoS on webhook creation — `apps/api/src/gw2analytics_api/routes/webhooks.py:65` defines a `ThreadPoolExecutor` with `max_workers=1`. A single POST with a slow DNS hostname blocks the sole worker for the full OS-resolution timeout; subsequent legitimate requests queue behind it, fail `future.result(timeout=2.0)` with `concurrent.futures.TimeoutError`, and the `except (..., TimeoutError): return True` fail-closed block returns 422 even for valid URLs.

---

## Finding

Evidence (current working-tree source):

```python
# apps/api/src/gw2analytics_api/routes/webhooks.py:60-72
_DNS_RESOLVE_TIMEOUT_S = 2.0
_DNS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,                                         # <-- the bug
    thread_name_prefix="dns_resolve",
)
atexit.register(_DNS_EXECUTOR.shutdown)
```

And the call site:

```python
# apps/api/src/gw2analytics_api/routes/webhooks.py:200-216 (in _resolved_address_is_blocked)
try:
    future = _DNS_EXECUTOR.submit(
        socket.getaddrinfo,
        hostname,
        None,
        type=socket.SOCK_STREAM,
    )
    infos = future.result(timeout=_DNS_RESOLVE_TIMEOUT_S)
except (socket.gaierror, TimeoutError, concurrent.futures.TimeoutError):
    return True  # fail-closed on DNS failure or timeout
```

### Why this is HIGH-severity

`/api/v1/webhooks` is a public (unauthenticated — single-tenant by contract per ROADMAP §3) POST endpoint. An attacker sends **one** request with a hostname pointing to a tarpit DNS resolver (or any resolver that drops queries silently) and the sole worker is parked for the full resolver timeout (the standard `getaddrinfo` does not honor `socket.setdefaulttimeout`). Every concurrent legitimate POST queues behind it. Because the bounded `future.result(timeout=2.0)` abandons the caller after 2.0s but the worker keeps running, the **second** legitimate POST also times out and returns 422 via the fail-closed branch — even for `https://hookbin.example.com/foo` that resolves in 5ms. An attacker can sustain the stall (resolver silently drops the query) and the entire endpoint returns 422 for every subsequent caller for the duration of the attack.

### Why the v0.9.4 plan 013 fix didn't close this gap

Plan 013 bounded the *caller's* wait time but kept a single worker. The bounded future-result is a per-caller timeout, NOT a per-worker concurrency cap. The two bugs are orthogonal.

---

## Fix

### Step 1 — Bump `max_workers` to a meaningful concurrency cap

In `apps/api/src/gw2analytics_api/routes/webhooks.py`:

- Change `_DNS_EXECUTOR` from `max_workers=1` to `max_workers=32`.
- Rationale: 32 concurrent DNS resolutions == >800 hostname resolutions/sec on any modern CPU (DNS is mostly network-bound + a tiny amount of reply parsing). An attacker posting 100 webhook URLs/sec still leaves every legitimate POST get a worker for its own 2-50ms DNS round-trip.

```python
# Replaces the existing max_workers=1
_DNS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=32,
    thread_name_prefix="dns_resolve",
)
atexit.register(_DNS_EXECUTOR.shutdown)
```

### Step 2 — Keep the existing per-caller 2.0s timeout

Do NOT change `_DNS_RESOLVE_TIMEOUT_S = 2.0`. The 2.0s per-caller fence is the right defense — even with 32 workers, a single caller's request that hits a tarpit resolver still fails closed (422) within 2 seconds. The fix is the **concurrency cap**, not the per-call timeout.

### Step 3 — Add a process-wide async-signal: COMPLETED log on shutdown

The 32-worker pool should log its teardown so an operator running `strace -e network` on the worker process can correlate. Replace the `atexit.register(_DNS_EXECUTOR.shutdown)` with:

```python
atexit.register(_DNS_EXECUTOR.shutdown)  # already in place
# in main.py shutdown (optional): close the pool explicitly so the
# atexit hook is redundant but harmless. Keep atexit as a safety net.
```

No new log line — the existing `atexit.register` is sufficient.

---

## Tests

### Test file 1 — NEW `apps/api/tests/test_webhooks_dns_executor_concurrency.py`

Pattern reference: `apps/api/tests/test_webhooks_getaddrinfo_timeout.py` (existing v0.9.4 plan 013 test file).

5 hermetic tests (no live DNS):

1. `test_pool_max_workers_constant_is_32` — inspect `webhooks.DNS_POOL_MAX_WORKERS == 32` (a module-level public constant). Pins the literal so an accidental future revert to `max_workers=1` fails the test. **Avoid** asserting on `_DNS_EXECUTOR._max_workers` (CPython internal; brittles across versions, especially Python 3.13 free-threaded builds).

2. `test_concurrent_calls_dont_serialise` — submit 4 fake `slow_getaddrinfo` futures (each blocks `_DNS_RESOLVE_TIMEOUT_S * 10` — i.e. 20 seconds) via direct `_DNS_EXECUTOR.submit(...)` calls. With `max_workers=32`, the **4th** call should *not* queue (it should also get a worker). With `max_workers=1`, it would queue. Use a `threading.Semaphore` or `time.monotonic()` to verify: record the start time of each submit + measure the delta between the latest submit and the earliest future.result(timeout=N). The pool must accept all 4 in <100ms.

3. `test_dns_executor_behavior_after_shutdown` — BEHAVIOR test, not introspection. The previous test (which asserted `_DNS_EXECUTOR` was registered in `atexit._exithandlers`) was fragile (CPython internal registry). The behavior contract is: "after the pool is shut down (via the atexit hook firing OR a manual `shutdown()` call), submitting more work is a hard error". Simulate the atexit firing by calling `_DNS_EXECUTOR.shutdown(wait=False)` directly. Then assert `_DNS_EXECUTOR.submit(socket.getaddrinfo, "example.com", None)` raises `RuntimeError` ("cannot schedule new futures after shutdown") — this proves the pool is cleanly shut down, which the operator's Uvicorn process will rely on at exit (the canonical Python idiom: shutdown is idempotent and post-shutdown `submit` is documented to fail loud). **Avoid** introspecting `atexit._exithandlers` (CPython internal); the behavior test is more authoritative and survives Python upgrades.

4. `test_legacy_max_workers_1_guard` — explicit regression test asserting `webhooks.DNS_POOL_MAX_WORKERS != 1` (the pre-fix folklore value). Prevents a future revert to a single-worker pool. **Avoid** `_DNS_EXECUTOR._max_workers != 1` (CPython internal).

5. `test_concurrent_32_calls_dont_reject` — submit 32 simultaneous getaddrinfo futures; assert **none** raise (the queue is empty under the cap, so 32 simultaneous workers fit). Uses a fake resolver that resolves in <10ms each.

### Test file 2 — NEW `apps/api/tests/test_webhooks_dns_under_attack.py`

3 integration-style tests (still no live DNS thanks to monkeypatch):

1. `test_attacker_slow_dns_does_not_lock_legitimate_users` — with `_DNS_EXECUTOR` mocked to return `concurrent.futures.TimeoutError` for one specific hostname (`tarpit.attacker.example`) and a fast 5ms resolution for all others: send 1 POST to the tarpit hostname AND 1 concurrent POST to a fast hostname (`hookbin.example`). Assert: tarpit returns 422 (fail-closed), fast also returns 200/201 (NOT 422). This is the canonical DoS regression test.

2. `test_concurrent_attack_burst_does_not_starve_legitimate` — same mast, scale up to 5 slow + 5 fast concurrent POSTs (use `concurrent.futures.ThreadPoolExecutor(max_workers=10)` to fire them in parallel + `time.monotonic()` to measure wait times). All 10 must complete within `_DNS_RESOLVE_TIMEOUT_S * 2` = 4.0 seconds. Counts `Slow returns 422 `: 5 + `Fast returns 201`: 5.

3. `test_dns_executor_pool_saturation_returns_422_gracefully` — overkill: submit 100 simultaneous tarpit DNS lookups. With `max_workers=32`, the 33rd-100th queue. Assert: all return 422 (fail-closed) within 4.0 seconds, NOT 30+ seconds (the OS resolver default for tarpit scenarios).

---

## Out of scope

- `TODO` items in `apps/api/src/gw2analytics_api/` unrelated to webhook DNS (e.g. telemetry on the executor queue depth).
- Refactoring `_resolved_address_is_blocked` to be async (the route is sync by contract; per the v0.9.2 hardening posture, sync-SQL routes are the production contract).
- Reducing `_DNS_RESOLVE_TIMEOUT_S` below 1.0s — the 2.0s ceiling preserves the existing test contract (`test_getaddrinfo_timeout_returns_422` mocks a future with `_DNS_RESOLVE_TIMEOUT_S`).
- Per-IP rate limiting on the webhook endpoint — broader feature for a separate audit cycle.

---

## Done criteria

Run from repo root after the fix is applied:

```bash
# 1. Ruff is clean.
uv run ruff check apps/api/

# 2. mypy --strict tolerates the change.
uv run mypy libs apps --no-incremental

# 3. Both new test files pass.
uv run pytest apps/api/tests/test_webhooks_dns_executor_concurrency.py -v
uv run pytest apps/api/tests/test_webhooks_dns_under_attack.py -v

# 4. The existing getaddrinfo timeout tests still pass (no regression).
uv run pytest apps/api/tests/test_webhooks_getaddrinfo_timeout.py -v

# 5. The legacy max_workers=1 literal is gone.
grep -nE 'max_workers\s*=\s*1' apps/api/src/gw2analytics_api/routes/webhooks.py
# Expected output: (empty)
```

---

## Maintenance note

- `max_workers=32` is conservative; the pool serves one process's webhook POST rate. If the deployment expects >100 webhook POSTs/sec sustained, bump to `max_workers=64`. Update `test_pool_max_workers_equals_32` if the literal changes.
- The pool is per-process. If Uvicorn forks (multiple workers), each process has its own pool (acceptable; the per-process rate is bounded).
- Replaces the `futures.result(timeout=)` safety net if you switch to `AnyIO` / asyncio later (the executor is a FastAPI-sync-route pattern; async would replace it with `loop.getaddrinfo`).

---

## Escape hatches

- **`max_workers=32` is too high for resource-constrained dev environments?** Reduce to `max_workers=8` if the executor's thread stack amplification is observable (8 threads × 8MB stack = 64MB baseline; 32 × 8MB = 256MB). Document the swap as a deliberate `Settings`-field override if it lands.
- **The 2.0s ceiling is too aggressive for slow-but-legitimate DNS?** Bump `_DNS_RESOLVE_TIMEOUT_S` to `3.0` only if a downstream complaint about legitimate resolver latency appears. Update `test_getaddrinfo_timeout_returns_422` accordingly.
- **STOP and report back if**: fast public DNS (e.g. 1.1.1.1) returns getaddrinfo results in >500ms after the fix lands. That's a different operational tier (resolver-level issue), not this plan's surface.

---

## Dependency graph

- **Independent.** Touches only `apps/api/src/gw2analytics_api/routes/webhooks.py` + 2 NEW test files. No plan depends on this one; this plan doesn't depend on any.

## Cross-references

- Plan 005 (v0.9.1) — universal SSRF block (closed the original `is_private` gate).
- Plan 013 (v0.9.4) — getaddrinfo timeout (the predecessor's bounded timeout; this plan closes the worker-pool DoS).
