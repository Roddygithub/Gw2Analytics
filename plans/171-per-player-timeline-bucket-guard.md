# Plan 171 — PerPlayerTimeline `_MAX_BUCKETS` guard (defense-in-depth parity)

**Drift base:** `93f4082` (origin/main). **Severity:** MED (hardening). **Effort:** S.

## Context

The real-stack E2E journey (see `plans/E2E-JOURNEY-2026-07-11.md`) found that on a real 18 MB WvW log, `GET /fights/{id}/timeline/players` **hung and wedged the API**: `PerPlayerTimelineAggregator` zero-fills `range(last_bucket_index + 1)` **per account**, and — unlike `EventWindowAggregator` and `PerFightTimelineAggregator` (plan 159) — had **no `_MAX_BUCKETS` guard**, so a non-normalized `time_ms` (~1.8e19) blew it up.

Roddy has since fixed the **root cause** (`a9fd216 fix(api): neutralize arcdps uint64 max sentinel time_ms in blob_loader`) and lazy-loaded the per-player timeline (plan 162), so garbage `time_ms` no longer reaches this aggregator in practice.

## Fix

Add the same `_MAX_BUCKETS = 50_000` guard to `PerPlayerTimelineAggregator.aggregate` (after `last_bucket_index` is derived, before the per-account zero-fill). This is now **defense-in-depth**: it closes the last per-player/per-fight asymmetry (the three timeline-family aggregators — event_window, per_fight, per_player — now all fail fast on non-normalized input), so any future regression that re-introduces bad `time_ms` can't hang the worker.

## Tests

`test_per_player_timeline.py`: `test_aggregate_fails_fast_on_non_normalized_time_ms` (one player + one `time_ms=1.8e19` event → `ValueError`, no hang).

## Effort

`S` — 1 constant + 1 guard + 1 regression test. No behaviour change on valid input.
