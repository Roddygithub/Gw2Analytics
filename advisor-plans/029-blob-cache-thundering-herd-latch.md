# Plan 029 — v0.10.10: `_cached_get_events` thundering-herd latch (serialize concurrent MinIO GETs for the same `blob_uri`)

**Stamped at:** `f0249ef` (working-tree diff HEAD; all changes in this plan live in the uncommitted working tree)
**Severity:** MED-HIGH (perf — defeats the cache for the canonical 4-parallel-fetcher case)
**Category:** perf
**Addresses finding:** `apps/api/src/gw2analytics_api/routes/fights.py:65` defines `_cached_get_events(blob_uri) = get_events(blob_uri)` wrapped in `@functools.lru_cache(maxsize=8)`. The cache is per-process but has NO concurrency latch. The `/fights/{id}` drilldown page makes 4 parallel fetches via the frontend (`Promise.allSettled`): `/events`, `/squads`, `/skills`, `/timeline`. FastAPI dispatches sync `def` handlers on `anyio`'s worker-thread pool. When 4 threads concurrently call `get_fight_events` + `get_fight_squads` + `get_fight_skills` + `get_fight_timeline`, ALL 4 invoke `_cached_get_events(same_blob_uri)` simultaneously. `functools.lru_cache` does NOT block other callers while computing; all 4 download the blob from MinIO independently. The cache's stated purpose ("avoid 4x MinIO GETs") is defeated. With cold cache + a 30 MB gzip blob + 4 parallel GETs, RAM peak is **4× the single-call peak** (≈1.2 GB) and MinIO sees 4x the requests.

---

## Finding

Evidence (current working-tree source):

```python
# apps/api/src/gw2analytics_api/routes/fights.py:55-68
@functools.lru_cache(maxsize=8)
def _cached_get_events(blob_uri: str) -> bytes:
    """LRU-cached MinIO GET for the gzipped events blob."""
    return get_events(blob_uri)
```

The standard `functools.lru_cache` semantics: on a cache MISS, the underlying function executes (no lock), THEN the result is stored. Concurrent callers with the same key all execute the function concurrently. The pattern is well-documented (Python docs: *"if a callable has side effects, the cache should be used with care"*).

### What's NOT happening on a miss

Concurrent threads do NOT wait for the first one to populate the cache. Python 3.12+ added `_CacheInfo` and the slow path but no concurrency latch. For a network-bound function (MinIO `get` over `httpx`), this means N parallel TCP connections to the same endpoint.

### Existing test coverage

`apps/api/tests/test_fights_blob_cache.py` (existing v0.9.4 plan 014 test) verifies the cache *dedupes sequential* calls. The new test in this plan adds the *concurrent* case.

---

## Fix

### Step 1 — Add a per-URI `threading.Lock` wrapped around the cache

In `apps/api/src/gw2analytics_api/routes/fights.py`:

```python
import functools
import threading
from collections import defaultdict

# v0.10.10 plan 029: per-URI locking prevents the thundering-herd
# stampede when the frontend's ``Promise.allSettled`` fires N
# parallel get_fight_* requests against the same blob_uri on a
# cold cache. ``defaultdict(threading.Lock)`` lazily creates a
# lock per URI; old locks are NEVER garbage-collected (memory
# grows with the count of distinct URIs ever cached). That's
# acceptable because ``lru_cache(maxsize=8)`` already bounds the
# number of distinct URIs at any one time to 8; once a URI is
# evicted from the LRU, the lock becomes a deployment-time only
# artefact (never acquired again). The lock dict mirrors the LRU
# keyset within a factor of ``maxsize*2`` in the steady state.
_BLOB_URI_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)

# v0.9.4 plan 014's lru_cache stays (sequential calls still benefit).
# The lock is the concurrency safety net that plan 014 missed.
@functools.lru_cache(maxsize=8)
def _cached_get_events(blob_uri: str) -> bytes:
    """LRU-cached MinIO GET for the gzipped events blob.

    Sequential calls (the v0.9.4 plan 014 contract): cache hit short-circuits.
    Concurrent calls (this plan's contract): the per-URI lock ensures
    exactly ONE MinIO GET per (blob_uri, cold-cache) event; the other
    N-1 callers block on the lock and pick up the populated cache value
    when the lock releases.
    """
    with _BLOB_URI_LOCKS[blob_uri]:
        return get_events(blob_uri)
```

### Step 2 — Document the lock dict never shrinks

Add a 3-line comment above `_BLOB_URI_LOCKS` explaining the lock dict grows monotonically but is bounded by `maxsize * 2` in the steady state. Operators reading the code MUST not mistake the unbounded-looking dict for a leak.

### Step 3 — Verify the `_load_fight_events` re-raises on cache exception fail

`functools.lru_cache` does NOT cache exceptions (canonical Python semantics). If `get_events` raises `S3Error`, the exception surfaces to the caller. The lock released; subsequent callers will RETRY the `get_events` call. This is correct behaviour (a transient S3 error shouldn't permanently poison the cache), but worth a regression test (Step 4 below pins it).

---

## Tests

### Test file 1 — NEW `apps/api/tests/test_fights_blob_cache_thundering_herd.py`

Pattern reference: `apps/api/tests/test_fights_blob_cache.py` (existing v0.9.4 plan 014 test file).

5 hermetic tests using `concurrent.futures.ThreadPoolExecutor` to simulate parallel fetches (no live MinIO):

1. `test_concurrent_calls_to_same_uri_invoke_get_events_once` — pre-fix: 4 parallel calls → 4 `get_events` invocations. Post-fix: 4 parallel calls → 1 `get_events` invocation (3 callers block on the per-URI lock). Use a `threading.Barrier(N)` to release all 4 threads simultaneously + assert `fake_get_events.call_count == 1` (the lock serialises the actual MinIO GET).

2. `test_concurrent_calls_to_different_uris_run_in_parallel` — 4 parallel calls, each with a distinct `blob_uri`. Each call's `get_events` MUST be invoked (4 total); wallclock MUST be `~max(per_call_latency)` (paralle­l), NOT `~sum(per_call_latency)` (serialised). Assert `fake_get_events.call_count == 4` AND `total_wallclock_ms < 4 * per_call_latency_ms * 0.5`.

3. `test_lock_releases_on_exception_does_not_poison_cache` — fake `get_events` raises `S3Error` on the first call, successfully returns on the second. Concurrent callers: first sees the exception propagate; second sees the success. Assert `fake_get_events.call_count == 2` (NOT cached); both exceptions bubble up to their respective callers (the route's `except S3Error → 404` handler).

4. `test_cache_maxsize_unchanged_post_fix` — `_cached_get_events.cache_info()` reports `maxsize=8`. The lock is orthogonal to the LRU semantics.

5. `test_lock_dict_bounded_by_maxsize` — submit 9 distinct URIs; assert `_BLOB_URI_LOCKS` keys count ≤ 9 (one per URI). The locks for evicted URIs remain in the dict (the comment-block "memory bounded" claim is upheld: ≤ maxsize + transient in-flight).

### Test file 2 — EXTEND `apps/api/tests/test_fights_blob_cache.py`

Add 1 regression test:

`test_fights_routes_use_cached_get_events` — set `fake_get_events` to record all calls; call `GET /api/v1/fights/{id}/events` + `/squads` + `/skills` + `/timeline` (via TestClient, 4 parallel via `concurrent.futures.ThreadPoolExecutor`). Assert the underlying `get_events` was called exactly ONCE per cold cache period (the post-fix contract).

---

## Out of scope

- Replacing `functools.lru_cache` with `cachetools.LRUCache` (cachetools is an extra dep; `functools.lru_cache` is sufficient + the lock layer solves the actual stampede).
- Async cache (FastAPI handlers are sync by contract; an `asyncio.Lock`-based cache would require migrating all 4 `/fights/{id}/*` handlers to `async def`).
- Cache invalidation on re-upload (the docstring already addresses this — blob is immutable after parse; if a future refactor allows re-upload under the same URI, the cache serves stale bytes until eviction).
- A `Settings`-driven `BLOB_CACHE_MAXSIZE` field (out of scope for this plan; a follow-up can lift the hardcoded 8 to a knob).

---

## Done criteria

Run from repo root after the fix is applied:

```bash
# 1. Ruff is clean.
uv run ruff check apps/api/

# 2. mypy --strict tolerates the change (the defaultdict+Lock typing is fine).
uv run mypy libs apps --no-incremental

# 3. Both new/extended test files pass.
uv run pytest apps/api/tests/test_fights_blob_cache_thundering_herd.py -v
uv run pytest apps/api/tests/test_fights_blob_cache.py -v

# 4. The full apps/api tests stay green (no regression in the upstream /fights/* routes).
uv run pytest apps/api/tests/ -q

# 5. The legacy test from plan 014 still asserts sequential cache dedup.
grep -nE 'test_cache_dedupes_minio_get_per_blob_uri' apps/api/tests/test_fights_blob_cache.py
# Expected output: 1 match (the existing test still references the same lru_cache)
```

---

## Maintenance note

- The lock dict grows monotonically with the count of distinct `blob_uri` ever accessed (bounded by `maxsize * N` over the lifetime of the process). In production with a turnover of 1000s of fights, the dict reaches a few hundred entries — negligible memory (~80 bytes per lock). If a much larger deployment emerges, an `LRU`-bounded lock dict can replace the unbounded defaultdict. Out of scope for this plan.
- `_BLOB_URI_LOCKS` is module-level (per-process). Multi-worker Uvicorn = each worker has its own dict + its own `lru_cache`. The MinIO load is then *worker_count*-distributed, which is the intended pattern.
- If a future refactor swaps `lru_cache` for an async-friendly cache (e.g. `aiocache.lru`), this lock becomes obsolete and MUST be removed (async caches have their own concurrency safety).

---

## Escape hatches

- **Lock contention is observable (a single blob_uri triggers >100 parallel threads)?** Reduce `max_workers` in the FastAPI thread pool (currently `anyio`'s default of 40). The lock per URI limits parallelism to 1 cold-cache miss; subsequent warm-cache calls are unconstrained. 100 threads waiting on a single lock is acceptable but not ideal; reduce thread-pool concurrency if you observe contention.
- **`defaultdict(threading.Lock)` forbids `gc` of an evicted URI's lock?** That's correct — the lock outlives the URI's LRU entry. The comment-block in step 1 documents this. If memory profiling shows lock accumulation matters, the fix is `weakref.WeakValueDictionary` keyed by `blob_uri` (lock values; lock is GC'd when the URI's LRU entry is evicted and the key is no longer referenced). Out of scope for this plan.
- **STOP and report back if**: 4 parallel callers take >2x the single-caller latency post-fix. That's a different bug (probably the lock holder itself is slow — typically MinIO is the bottleneck); surface as a MinIO-latency audit, not a cache-layer audit.

---

## Dependency graph

- **Independent.** Touches only `routes/fights.py` + 1 NEW test file + 1 EXTENDED test file. No plan depends on this one; this plan doesn't depend on any.

## Cross-references

- Plan 014 (v0.9.4) — the predecessor (`lru_cache(maxsize=8)`). This plan closes the concurrency-gap that plan 014 missed.
- Plan 027 (v0.10.10) — companion read-side perf fix (`build_event_iterator` streaming). Independent; both land together for the canonical "load `/fights/{id}` page" perf story.
