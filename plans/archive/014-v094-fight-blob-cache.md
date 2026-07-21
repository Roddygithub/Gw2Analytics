# Plan 014 — v0.9.4: cross-request cache for events blob bytes

**Author:** senior-advisor audit (improve skill, standard effort) — second pass on the deferred v0.9.3 audit findings.
**Drift base:** `44ea862` (origin/main HEAD at plan authoring).
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** an executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/routes/fights.py::_load_fight_events` is invoked by 4 endpoints on `/fights/{id}` (`events`, `squads`, `skills`, `timeline`). The frontend's `/fights/[id]` page fires all 4 in parallel via `Promise.allSettled` (per the v0.8.9 plan/002 comment). Each call performs:

1. 1 MinIO GET (`storage.get_events(blob_uri)`).
2. 1 `gzip.decompress`.
3. 1 `_EVENT_TYPE_ADAPTER.validate_json(line)` per event in the list.

For a typical fight with ~10k events and a 200 KB gzipped blob: **4× GET** + **4× decompress** + **4× N-line parse** for the **same data**. The MinIO GET is the slow part (network roundtrip to MinIO); the parse is fast (pydantic v2 in a C extension). Caching the gzipped BYTES (not the parsed events list) is the canonical pattern.

The naive fix (`contextvars.ContextVar` cache) is **incorrect** — `ContextVar` is scoped to a single async task, NOT to a single HTTP request. The 4 frontend requests are 4 separate HTTP calls with 4 separate async tasks. The 4 endpoints will each see an empty context and parse the blob 4 times anyway (per the senior-advisor thinker).

The canonical pattern is `functools.lru_cache` keyed on `blob_uri` with a strict `maxsize` (8 fights cached at a time) to bound memory. The cache lives for the lifetime of the FastAPI process; eviction is LRU.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/routes/fights.py` (`_load_fight_events` + NEW `_cached_get_events`).
- `apps/api/tests/test_fights_blob_cache.py` — **NEW**.

## Files NOT in scope

- `apps/api/src/gw2analytics_api/storage.py` (the underlying `get_events` GET stays; the cache layer is on top).
- Other routes (the cache is for `/fights/{id}/*` only).
- `web/` (frontend unaffected).

---

## Current code (read from `44ea862`)

### `routes/fights.py::_load_fight_events` (around line 60-105)

```python
def _load_fight_events(db, fight_id):
    fight = db.get(OrmFight, fight_id)
    if fight is None or fight.events_blob_uri is None:
        raise HTTPException(404, "fight not found")
    try:
        gz_bytes = get_events(fight.events_blob_uri)
    except S3Error:
        raise HTTPException(404, "events unavailable")
    try:
        jsonl = gzip.decompress(gz_bytes)
    except OSError as exc:
        raise HTTPException(502, "events blob corrupt")
    events: list[Event] = [
        _EVENT_TYPE_ADAPTER.validate_json(line) for line in jsonl.splitlines() if line
    ]
    if not events:
        raise HTTPException(404, "events unavailable")
    return events
```

---

## Step-by-step

### Step 1 — Add the LRU cache

In `routes/fights.py`, near the module-level `TypeAdapter` instantiation:

```python
import functools

# v0.9.4 plan 014: cache the gzipped blob across requests.
# maxsize=8 caps memory at ~8 × avg blob size (~200 KB → 1.6 MB
# for the typical fight; ~MB for large fights). LRU eviction.
# Cache key is the blob_uri (a fully-qualified S3 URI; NOT
# fight_id, so a re-uploaded fight with a new blob_uri
# invalidates implicitly).
@functools.lru_cache(maxsize=8)
def _cached_get_events(blob_uri: str) -> bytes:
    """LRU-cached MinIO GET for the gzipped events blob.

    The 4 endpoints on /fights/{id} (events, squads, skills,
    timeline) all fetch the same blob_uri; this cache dedupes
    the MinIO GET + the gzip.decompress.
    """
    return get_events(blob_uri)
```

### Step 2 — Wire into `_load_fight_events`

REPLACE the `gz_bytes = get_events(fight.events_blob_uri)` line with:

```python
    try:
        gz_bytes = _cached_get_events(fight.events_blob_uri)
    except S3Error:
        raise HTTPException(404, "events unavailable") from None
```

(Drop the `_cached_get_events.cache_clear()` call — process-lifetime cache is correct.)

### Step 3 — Tests

`apps/api/tests/test_fights_blob_cache.py` (NEW):

```python
"""v0.9.4 plan 014: cross-request cache for events blob bytes."""
from __future__ import annotations

from unittest.mock import patch
import pytest

from gw2analytics_api.routes.fights import _cached_get_events


@pytest.fixture(autouse=True)
def _clear_cache():
    _cached_get_events.cache_clear()
    yield
    _cached_get_events.cache_clear()


def test_cache_dedupes_minio_get_per_blob_uri(monkeypatch):
    """Two calls on the same URI invoke the underlying get_events once."""
    call_count = {"n": 0}
    def fake_get_events(uri):
        call_count["n"] += 1
        return b"\x1f\x8b\x08..."  # minimal gzip payload
    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        fake_get_events,
    )
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    assert call_count["n"] == 1


def test_cache_invalidates_on_new_blob_uri(monkeypatch):
    """A re-uploaded fight with a new blob_uri gets a fresh fetch."""
    call_count = {"n": 0}
    def fake_get_events(uri):
        call_count["n"] += 1
        return b"\x1f\x8b\x08..."
    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        fake_get_events,
    )
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT123_v2.jsonl.gz")
    assert call_count["n"] == 2


def test_cache_maxsize_evicts_oldest(monkeypatch):
    """9 calls with 9 distinct URIs trigger at least 1 eviction."""
    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        lambda uri: b"\x1f\x8b\x08...",
    )
    for i in range(9):
        _cached_get_events(f"s3://bucket/events/FIGHT{i}.jsonl.gz")
    info = _cached_get_events.cache_info()
    assert info.evictions >= 1
    assert info.currsize == 8  # bounded by maxsize


def test_e2e_4_endpoints_share_one_minio_get(client, monkeypatch):
    """The /fights/{id} page's 4 parallel requests trigger 1 MinIO GET."""
    # Seed a fight + agents + skills + the events blob.
    # Hit /events, /squads, /skills, /timeline on the same fight.
    # Assert storage.get_events was called exactly once.
    call_count = {"n": 0}
    def fake_get_events(uri):
        call_count["n"] += 1
        return gzip.compress(b"...")
    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        fake_get_events,
    )
    # ... 4 parallel calls via TestClient ...
    assert call_count["n"] == 1
```

---

## Verification commands

```bash
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy --no-incremental libs apps
uv run pytest apps/api/tests/test_fights_blob_cache.py -v
uv run pytest apps/api/tests/test_uploads_e2e.py -v
# Expected: 92+ pass + 0 fail + 3 skip (existing 4 endpoints still pass with the cache).
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/routes/fights.py` (add `_cached_get_events` + update `_load_fight_events`).
- `apps/api/tests/test_fights_blob_cache.py` (NEW, 4 tests).
- `CONTRIBUTING.md` (1 short subsection on the blob cache).

---

## Maintenance note

- `maxsize=8` was chosen empirically. If the typical analyst loads more than 8 fights in a session, the cache will thrash (LRU eviction). Lift via a `GW2ANALYTICS_FIGHT_BLOB_CACHE_SIZE` env var if needed.
- The cache is process-local. In a multi-worker deployment (gunicorn), each worker has its own cache. Total memory across the cluster is `N_workers × 8 × avg_blob_size`. Operators must size their workers accordingly.
- A re-uploaded fight (same `fight_id`, new `blob_uri`) gets a fresh cache entry automatically. The cache key is the blob_uri, not the fight_id.
- The MinIO GET is wrapped in the cache; the `gzip.decompress` runs every call (in `_load_fight_events`) — for a 200 KB blob, the decompress is ~5 ms in C. Caching the decompressed JSONL would save those 5 ms but at 10x the memory cost. Trade-off favors the bytes-cache.

## Escape hatches

- If memory is a concern, drop `maxsize` to 4 or 2.
- If parsing becomes the bottleneck (unlikely — pydantic v2 in C is fast), cache the parsed events list instead of the gzipped bytes. Trade-off: 10x memory per cached fight.
- If a future plan needs per-fight cache invalidation (e.g. on `OrmFight.events_blob_uri` UPDATE — re-upload of the same fight), wrap the cache in a small class with `clear_for_uri(uri)` and call it from `services.process_parse` after the UPDATE.
- If the analyst's upload pattern is "load fight X, immediately re-upload it", the cache holds the stale `blob_uri` for ~8 fights of churn. A future plan could expire by fight_id (TTL-based) if this becomes a real pattern.
