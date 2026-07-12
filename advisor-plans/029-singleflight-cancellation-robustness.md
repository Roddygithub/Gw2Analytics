# Plan 029 — Singleflight CancelledError/KeyboardInterrupt robustness

**Stamped at:** `5cfd962` (origin/main HEAD at audit time)
**Severity:** MEDIUM (defensive hardening)
**Category:** correctness, resilience
**Addresses finding:** The new `_IN_FLIGHT_FUTURES` dict in `apps/api/src/gw2analytics_api/routes/fights/blob_cache.py` (the Future-dict + meta-lock under `@functools.lru_cache(maxsize=8)` shipped in the v0.10.10 singleflight refactor) was narrowed from `BaseException` to `Exception` in the broadcast step. `asyncio.CancelledError` and `KeyboardInterrupt` during Future resolution could leak stuck Future entries in the dict if the exception-narrowing misses the new `Exception`-derived subclasses.

---

## Finding

In Python 3.9+, `asyncio.CancelledError` derives from `BaseException` (not `Exception`). The singleflight broadcast step catches `Exception` to pop the Future from `_IN_FLIGHT_FUTURES` — but if `CancelledError` is raised during `future.result()`, the `except Exception` branch does NOT fire, and the Future entry leaks in the dict forever. Subsequent cold-cache misses for the same URI would then hit the stale Future (which may never resolve), causing a silent hang.

The `KeyboardInterrupt` case is analogous: a SIGINT during the broadcast loop would bypass the `except Exception` cleanup.

---

## Fix

### Step 1 — Add `finally` clause to the broadcast loop

In `apps/api/src/gw2analytics_api/routes/fights/blob_cache.py`, wrap the Future-resolution loop with a `finally` block that pops the entry regardless of exception type:

```python
for waiter in waiters:
    try:
        waiter.set_result(result)
    except asyncio.InvalidStateError:
        pass
    finally:
        _IN_FLIGHT_FUTURES.pop(uri, None)
```

### Step 2 — Add BaseException guard for the outer loop

If the broadcast loop itself is inside a `try/except Exception`, add a parallel `except BaseException` handler:

```python
try:
    # ... broadcast to waiters ...
except BaseException:
    # Ensure all waiters are cleaned up even on CancelledError/KeyboardInterrupt
    for uri_key in list(_IN_FLIGHT_FUTURES):
        _IN_FLIGHT_FUTURES.pop(uri_key, None)
    raise
```

### Step 3 — Commit

```bash
git add apps/api/src/gw2analytics_api/routes/fights/blob_cache.py
git commit -m "fix(api): singleflight cleanup on CancelledError/KeyboardInterrupt (plan 029)"
```

---

## Tests

### NEW `apps/api/tests/test_fights_blob_cache_cancellation.py`

3 hermetic tests:

1. `test_cancelled_error_does_not_leak_future` — simulate `asyncio.CancelledError` during `future.result()` in the broadcast loop; assert `_IN_FLIGHT_FUTURES` is empty after the exception.
2. `test_keyboard_interrupt_does_not_leak_future` — same pattern with `KeyboardInterrupt`.
3. `test_normal_broadcast_cleans_up` — existing behavior: N concurrent requests collapse to 1 MinIO GET; `_IN_FLIGHT_FUTURES` is empty after all waiters resolve.

---

## Rejected alternatives

- **Catch `BaseException` everywhere**: too broad — would swallow `SystemExit` and other non-recoverable signals. The `finally` clause is more surgical.
- **Remove the Future-dict and rely solely on `lru_cache`**: the Future-dict is the singleflight mechanism; removing it would re-introduce the N×MinIO-GET thundering herd.
- **Use `asyncio.shield` on the broadcast**: adds complexity without fixing the cleanup leak.

---

## Dependency graph

- **Standalone.** No plan depends on this one; this plan doesn't depend on any.

---

## Notes for executors

- The existing 12 cache tests in `apps/api/tests/test_fights_blob_cache.py` should pass without modification — the `finally` clause is additive.
- Do NOT touch the `lru_cache(maxsize=8)` decorator — it stays as defence-in-depth for the nanosecond race window between the Future pop and the lru_cache atomic cache-write.
