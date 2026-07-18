# Plan 162 — `/fights/{id}/timeline/players` slow (~10s)

**Source:** E2E journey finding #6 (`plans/E2E-JOURNEY-2026-07-11.md`). **Severity:** LOW (perf). **Effort:** M.

## Problem

`GET /api/v1/fights/{id}/timeline/players` took **~10s** for a single 47-agent fight during the E2E (vs sub-second for `/squads`, `/skills`). Because `/fights/[id]` fetches it during SSR, it drags the whole detail-page render (and any client waiting on it).

## Likely cause

The per-player timeline decompresses + walks the full event blob and buckets per `(player × window)` with no cap and no index-backed shortcut — O(events × players). Worth profiling to confirm (event count for this fight, per-player bucket build, JSON serialization size).

## Suggested fix (pick after profiling)

1. **Lazy-load client-side** — drop it from the SSR critical path; fetch it from the browser after first paint so the detail page renders immediately. Cheapest, biggest perceived win.
2. **Single-pass partition** — bucket all players in one walk over the event stream instead of per-player passes.
3. **Cap / paginate** the series (top-N players) as the per-target rollups already do (v0.10.2 hotfix #12 pattern).

Non-blocking; do #1 first.
