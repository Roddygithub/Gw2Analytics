# Plan 159 — v0.10.25 — PerFightTimelineAggregator hangs on non-normalized time_ms (missing bucket guard)

**Drift base:** `943ab6b` (origin/main HEAD)
**Severity:** HIGH (robustness / DoS) — surfaced by the 2026-07-18 real-backend E2E user-journey.

## Symptom

Uploading a fight whose events carry a non-fight-relative `time_ms` (a raw arcdps timestamp — the E2E fixture leaked `time_ms ≈ 1.4e19` via a parser skill-table misread) makes `GET /api/v1/fights/{id}/timeline` **hang indefinitely**. The Next.js `/fights/[id]` detail page SSR-fetches that endpoint, so the whole page hangs (30s+ SSR timeout), and a single request pins the uvicorn worker.

## Root cause

`EventWindowAggregator` (`event_window.py`) has a `_MAX_BUCKETS = 50_000` safety cap: if `last_bucket_index + 1` exceeds it, it raises `ValueError` (so `/events` returns a fast 500 on garbage `time_ms`). `PerFightTimelineAggregator` (`per_fight_timeline.py`) — a "strict parallel" of it — was **missing that guard**, so its zero-fill `for idx in range(last_bucket_index + 1)` tried to allocate ~2.9e15 `PerFightTimelineRow` objects → effectively an unbounded hang / OOM.

## Fix

Add the identical `_MAX_BUCKETS = 50_000` guard to `PerFightTimelineAggregator.aggregate`, right after `last_bucket_index` is computed and before the zero-fill loop. Raises a `ValueError` with the same "would produce N buckets … time_ms may not be normalized" message as `EventWindowAggregator`, converting the hang into a fast, clear failure (parity with `/events`).

This is a defensive robustness fix; it does **not** fix the upstream parser misread that produces the garbage `time_ms` in the first place (see Findings — that is a separate parser-side issue, likely covered by the active WAVE-8 parser work).

## Tests

`libs/gw2_analytics/tests/test_per_fight_timeline.py`: new `test_aggregate_fails_fast_on_non_normalized_time_ms` feeds one event with `time_ms = 14_555_633_995_661_440_000` and asserts a `ValueError` is raised (the whole timeline suite completing quickly is itself the no-hang proof).

## Verification (live stack)

Before: `/timeline` hung (>20s timeout); web `/fights/[id]` hung (>30s). After (API restarted with the fix): `/timeline` → **500 in 0.04s**, web `/fights/[id]` → **200 in 0.45s** (renders instead of hanging).

## Effort

`S` — 1 constant + 1 guard + 1 regression test.
