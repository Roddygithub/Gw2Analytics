# Plan 002 — Per-fight timeline tab on `/fights/[id]`

## Context

The `/fights/[id]` page (v0.7.1 + v0.7.2 + v0.8.0 + v0.8.3)
currently has 5 sections:

1. Per-target damage roll-up (`TargetRollupsGrid`)
2. Per-target healing roll-up (same grid, different columns)
3. Per-target buff-removal roll-up (same grid, different columns)
4. Per-subgroup roll-up (`SquadRollupsGrid`)
5. Per-skill roll-up (`SkillUsageTable` + `EventWindowsChart`)

None of these show a **temporal** view of the fight — i.e.
damage / healing / buff-removal plotted as 3 polylines over
the fight's duration. The v0.8.0 player timeline
(`/players/[account_name]` with `PlayerTimelineChart`) shows
exactly this view, but **across many fights** (the
historical-timeline use case); a per-fight timeline would
show the same 3 polylines **within a single fight** (the
"what happened in this fight?" use case).

The v0.8.8 advisor audit considered this finding and
explicitly reserved it for v0.8.9+:

> "Build /fights/[id]/timeline tab" ... plausible but
> small-leverage vs the plans above; would need full
> design + UX validation first. Reserved for v0.8.9+.

The "full design + UX validation" is the well-established
v0.8.0 pattern: 3 polylines, per-series normalisation to
0-100% of per-series max, SVG-native `<title>` tooltip on
hover, decade-style X-axis labels, drag-resilient layout.
A future refactor could extract a shared `<TimelineChart>`
base component from the v0.8.0 `PlayerTimelineChart` and
this new `PerFightTimelineChart`, but for v0.8.9 the two
can live as separate components with parallel data shapes.

The aggregator is a small wrapper over the existing
`EventWindowAggregator` (v0.6.0) + a per-kind total
accumulator. The route is a thin wrapper over the
existing `GET /api/v1/fights/{id}/events` events-blob
decompress path. The total surface is small + well-scoped.

## Goal

Add a new "Timeline" section to `/fights/[id]` that
shows damage / healing / buff-removal over time within
the single fight. The chart reuses the v0.8.0
`PlayerTimelineChart` data shape (3 polylines, per-series
normalisation, SVG-native `<title>` tooltip on the
parent `<g>` group). The backend route is
`GET /api/v1/fights/{id}/timeline?window_s=5` (new).

## Files in scope

- `libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py`
  (NEW): `PerFightTimelineAggregator.aggregate(events,
  agents, duration_s, *, window_s: int = 5) ->
  list[PerFightTimelineRow]`. Reuses the existing
  `EventWindowAggregator` for the per-bucket skeleton
  + a per-kind total accumulator. Schema:
  `PerFightTimelineRow` with `window_start_ms: int`,
  `window_end_ms: int`, `total_damage: int`,
  `total_healing: int`, `total_buff_removal: int`.
  Frozen Pydantic semantics. Deterministic ordering
  (ascending by `window_start_ms`).
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`:
  re-export the new aggregator + the row model. The
  `__version__` bump is NOT in this commit — the
  `apps/api` package re-exports the aggregator at
  the existing version (the per-fight timeline is a
  new route, not a new analytics version). The
  analytics lib's `__version__` stays at `0.7.0`.
- `libs/gw2_analytics/tests/test_per_fight_timeline.py`
  (NEW): 6 pytest cases — empty input, single-bucket
  shape, multi-bucket ordering, mixed-kind (damage +
  healing + strip from the same cbtevent record
  exercises the dual-emit path), zero/negative
  `duration_s` guard, frozen-Pydantic guarantee.
- `apps/api/src/gw2analytics_api/schemas.py`: 2 new
  Pydantic v2 response schemas —
  `PerFightTimelinePointOut` (the 5 fields from the
  row) + `PerFightTimelineOut` (`fight_id`, `window_s`,
  `duration_s`, `points: list[PerFightTimelinePointOut]`).
- `apps/api/src/gw2analytics_api/routes/fights.py`:
  new `GET /api/v1/fights/{fight_id}/timeline?window_s=5`
  route. Reuses the existing events-blob decompress +
  per-kind `isinstance` filter pattern from
  `get_fight_events`. `window_s: int = Query(5,
  ge=1, le=600)` matches the pre-existing
  `get_fight_events` window-s contract. 404 contract
  mirrors `get_fight_events`: unknown fight OR
  `events_blob_uri is None` OR the MinIO read raises
  `S3Error` all return 404. 502 contract mirrors
  `get_fight_events`: events blob is present but
  corrupt (`gzip.decompress` failed). Declaration
  order matters — the new route MUST be declared
  BEFORE the catch-all `/api/v1/fights/{fight_id}`
  detail route (same FastAPI matching-order gotcha as
  the v0.8.0 player timeline route).
- `apps/api/tests/test_uploads_e2e.py`: 4 new e2e
  tests (see Test plan).
- `web/src/lib/api.ts`: new `fetchFightTimeline(fightId,
  opts?: { windowS?: number }): Promise<FightTimelineRow>`
  helper + 2 new TS interfaces
  (`PerFightTimelinePoint`, `FightTimeline`). The
  signature mirrors `fetchFightEvents` (the existing
  helper for the same route's events payload).
- `web/src/app/fights/[id]/page.tsx`: extended to
  fetch the per-fight timeline (default `window_s=5`)
  on the server alongside the existing events fetch.
  404 from the timeline is swallowed (treated as
  "fight has no per-fight timeline yet" — same
  rationale as the v0.8.0 player timeline's 404
  contract). 5xx from the timeline is fatal. The
  new `<PerFightTimelineSection>` is rendered between
  the per-target trio and the per-subgroup trio
  (the "temporal view sits in the middle of the
  cross-section views" UX decision — the per-target
  trio answers "who did what", the timeline answers
  "when did they do it", the per-subgroup + per-skill
  answer "by which squad / skill").
- `web/src/components/PerFightTimelineChart.tsx`
  (NEW): strict parallel of the v0.8.0
  `PlayerTimelineChart` (3 polylines normalised to
  0-100% of per-series max; SVG-native `<title>`
  tooltip on the parent `<g>` group; decade-style
  X-axis labels with `Intl.DateTimeFormat`; 8-tick
  cap; first + last labels always drawn; empty-state
  panel mirroring the `EventWindowsChart` style).
- `web/src/components/PerFightTimelineSection.tsx`
  (NEW): Server-Component-friendly wrapper that
  takes the SSR-fetched timeline data + renders
  the chart. The existing
  `PlayerTimelineSection` is a Client Component
  (it owns the "Load more" pagination state); the
  per-fight timeline has no pagination (the fight
  is bounded by `duration_s / window_s` so the
  bucket count is naturally finite — typically
  10-100 buckets for a 1-5 min fight at `window_s=5`).
  A pure Server Component is the right call; no
  Client Component needed.
- `web/tests/components/per-fight-timeline-chart.test.tsx`
  (NEW): 6 vitest cases — empty state, single
  all-zero point, 3 points with 9 circles + 3 paths
  + 3 legend swatches, multi-bucket layout for a
  realistic 5-min fight at `window_s=5` (60 buckets),
  `buildTimelineLayout` helper for empty / single
  point / all-zero clamp to 1 / mixed magnitudes,
  hovering any of the 3 sibling dots surfaces the
  native SVG `<title>` tooltip.
- `web/tests/e2e/fights.spec.ts`: extend the
  existing 2 tests to also assert the new
  "Per-fight timeline" heading is visible (locks
  the section rendering contract).
- `web/tests/setup.ts`: global no-op mock for
  `PerFightTimelineChart` (the page-level Server
  Component test can render the wrapper without
  booting the React state + SVG plumbing; a
  dedicated component-level test exercises the
  real chart).

## Files explicitly out of scope

- The per-target trio (unchanged)
- The per-subgroup + per-skill roll-ups (unchanged)
- The event windows table (unchanged)
- The `?bucket=day` mode (that's plan 001; the
  per-fight timeline is always per-fight — there's
  no day-mode for a single fight)
- A future `<TimelineChart>` shared base
  component (a refactor that DRYs the v0.8.0
  `PlayerTimelineChart` + this new
  `PerFightTimelineChart`; deferred to v0.9.0+)
- A "compare 2 fights side by side" feature
  (could use the per-fight timeline + 2 fight
  selectors; deferred)

## Steps

1. **Read the v0.8.0 `PlayerTimelineChart` +
   `PlayerTimelineSection` + the cross-fight
   timeline route in
   `apps/api/src/gw2analytics_api/routes/players.py`**
   to internalise the established pattern. The
   per-fight timeline is a strict parallel.
2. **Add the `PerFightTimelineAggregator` to
   `libs/gw2_analytics`**. The aggregator
   signature is `aggregate(events, agents,
   duration_s, *, window_s: int = 5) ->
   list[PerFightTimelineRow]`. Internally, it
   uses the existing `EventWindowAggregator` for
   the per-bucket skeleton + iterates the
   per-bucket events once to accumulate the
   per-kind totals. The frozen Pydantic
   guarantee mirrors the v0.8.0 PlayerTimeline
   pattern.
3. **Add 6 pytest cases** in
   `libs/gw2_analytics/tests/test_per_fight_timeline.py`
   (see Test plan).
4. **Add the 2 new schemas** in
   `apps/api/src/gw2analytics_api/schemas.py`.
5. **Add the new route**
   `GET /api/v1/fights/{fight_id}/timeline?window_s=5`
   in
   `apps/api/src/gw2analytics_api/routes/fights.py`.
   **Declaration order matters**: declare the new
   route BEFORE the existing
   `GET /api/v1/fights/{fight_id}` detail route
   (same FastAPI matching-order gotcha as the
   v0.8.0 player timeline).
6. **Add 4 new e2e tests** in
   `apps/api/tests/test_uploads_e2e.py` (see
   Test plan).
7. **Forward the helper + types** through
   `web/src/lib/api.ts` (new `fetchFightTimeline`
   + 2 new TS interfaces).
8. **Create the new
   `PerFightTimelineChart` +
   `PerFightTimelineSection`** components.
9. **Mount the new section in
   `web/src/app/fights/[id]/page.tsx`**
   (between the per-target trio and the
   per-subgroup trio).
10. **Add 6 new vitest cases** for the chart
    (see Test plan).
11. **Extend `web/tests/e2e/fights.spec.ts`**
    with the new "Per-fight timeline" heading
    check in both existing tests.
12. **Add the no-op mock for
    `PerFightTimelineChart`** in
    `web/tests/setup.ts`.
13. **Run the validation gates** (see
    Test plan's "Validation" subsection).

## Test plan

- **6 new pytest cases in
  `libs/gw2_analytics/tests/test_per_fight_timeline.py`**:
  - `test_per_fight_timeline_empty_input`:
    empty `Iterable[Event]` yields 0 rows.
  - `test_per_fight_timeline_single_bucket_shape`:
    3 events in the same bucket -> 1 row with
    correct totals + the 3 metadata fields.
  - `test_per_fight_timeline_multi_bucket_ordering`:
    6 events across 3 buckets -> 3 rows in
    ascending `window_start_ms` order with the
    correct per-bucket totals.
  - `test_per_fight_timeline_dual_emit_path`:
    a single cbtevent record with `is_nondamage=1`
    + `value>0` + `buff_dmg>0` (the v0.6.0
    dual-emit) contributes to BOTH the heal
    total AND the strip total in the same
    bucket.
  - `test_per_fight_timeline_zero_duration_guard`:
    `duration_s=0` yields 0 rows (the bucket
    count is `ceil(0 / window_s) = 0`).
  - `test_per_fight_timeline_frozen_pydantic_guarantee`:
    the `model_config = ConfigDict(frozen=True)`
    invariant holds (a `__setattr__` attempt
    raises).
- **4 new e2e tests in
  `apps/api/tests/test_uploads_e2e.py`**:
  - `test_fight_timeline_returns_per_bucket_totals_for_known_fight`:
    seed 3 cbtevent records at distinct
    `time_ms` values within a 3-second window
    (1 damage, 1 heal, 1 strip) + assert
    `GET /fights/{id}/timeline?window_s=1`
    returns 1 row with `total_damage=...` +
    `total_healing=...` + `total_buff_removal=...`
    from the 3 events.
  - `test_fight_timeline_404_when_unknown_fight`:
    unknown fight id -> 404 (same contract as
    `get_fight_events`).
  - `test_fight_timeline_422_when_window_s_too_small`:
    `?window_s=0` -> 422 (the FastAPI
    `Query(ge=1)` validator fires).
  - `test_fight_timeline_422_when_window_s_too_large`:
    `?window_s=601` -> 422 (the FastAPI
    `Query(le=600)` validator fires).
- **6 new vitest cases in
  `web/tests/components/per-fight-timeline-chart.test.tsx`**:
  empty state, single all-zero point, 3 points
  with 9 circles + 3 paths + 3 legend swatches,
  multi-bucket layout for a realistic 5-min
  fight at `window_s=5`, `buildTimelineLayout`
  helper for empty / single point / all-zero
  clamp to 1 / mixed magnitudes, SVG-native
  `<title>` tooltip presence.
- **2 extended e2e tests in
  `web/tests/e2e/fights.spec.ts`**: the
  existing "renders the 5 roll-up sections" +
  "renders the upstream-error card" tests each
  gain a new "Per-fight timeline" heading
  visibility check.
- **No new vitest cases in
  `web/tests/app/fight-events-page.test.tsx`**:
  the page-level test's `fetchFightTimeline`
  mock is no-op'd via the new
  `PerFightTimelineChart` mock in
  `web/tests/setup.ts`; the existing 5
  page-level cases still pass.

## Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy --no-incremental libs apps`: clean
  (MYPY=0; the new aggregator is fully typed).
- `uv run pytest libs/gw2_analytics/tests/test_per_fight_timeline.py -v`:
  6 passed (PYTEST_LIBS=0).
- `uv run pytest apps/api/tests/test_uploads_e2e.py -k timeline`:
  4 new + 4 pre-existing v0.8.0 player-timeline
  tests pass (PYTEST_APPS=0).
- `pnpm tsc --noEmit`: clean (TSC=0; the new
  TS interfaces + helper type-check).
- `pnpm test:unit`: clean (VITEST=0; 6 new chart
  vitest cases + 70+ pre-existing cases pass).
- `pnpm exec playwright test`: clean
  (PLAYWRIGHT=0; 2 existing fights.spec.ts tests
  extended + 5 other pre-existing tests pass).

## Done criteria

- `GET /api/v1/fights/{id}/timeline?window_s=5`
  returns a `PerFightTimelineOut` for a known
  fight (3+ buckets with the correct per-kind
  totals).
- Unknown fight returns 404; out-of-range
  `window_s` returns 422 (matches the
  `get_fight_events` contract).
- The `/fights/[id]` page renders the new
  "Per-fight timeline" section between the
  per-target trio and the per-subgroup trio.
- The chart's 3 polylines are visible + the
  legend's 3 swatches are visible + the
  "Showing N of N buckets" caption is rendered.
- 16 new tests pass (6 analytics + 4 e2e +
  6 vitest).
- Pre-existing tests still pass (no regression).

## Maintenance note

- The chart is a strict parallel of the v0.8.0
  `PlayerTimelineChart`. A v0.9.0 refactor
  could extract a shared `<TimelineChart>` base
  component; the two components' data shapes
  (per-series normalisation, SVG-native `<title>`
  tooltip, decade-style X-axis labels) are
  identical.
- The new route declaration order
  (BEFORE the catch-all `/api/v1/fights/{id}`)
  is critical — a future refactor that reorders
  the routes will silently break the timeline
  endpoint (the catch-all would consume
  `/api/v1/fights/{id}/timeline` with
  `fight_id="{id}/timeline"`). The docstring
  documents the gotcha.
- The `?window_s=` param is shared with
  `get_fight_events`. A future v0.9.0 could
  surface a single "window size" preference on
  the page that drives both endpoints; out of
  scope for v0.8.9.

## Escape hatch

- If the `EventWindowAggregator`'s per-bucket
  skeleton proves incompatible with the
  per-kind total accumulation (e.g. the
  `EventWindowAggregator` doesn't expose the
  per-bucket event list), STOP and report
  back. The fallback is to duplicate the
  per-bucket skeleton logic in the new
  aggregator (~30 lines of duplication; not
  ideal but acceptable for a one-off). A
  cleaner fallback is to extend the
  `EventWindowAggregator` to optionally emit
  the per-bucket event list as a sibling
  field — a single-line change with
  backward-compat semantics.
- If the e2e test for the dual-emit path
  (damage + heal + strip from the same
  cbtevent record) is unstable across Python
  versions, simplify the test to use 3
  separate cbtevent records (one per kind) in
  the same bucket. The dual-emit path is still
  exercised by the analytics test
  `test_per_fight_timeline_dual_emit_path`;
  the e2e test just needs to prove the
  route is wired correctly.
