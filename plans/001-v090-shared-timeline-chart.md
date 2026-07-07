# Plan 001 — Shared `<TimelineChart>` refactor + unified `?window_s=` UI

## Context

The v0.8.0 cycle shipped `PlayerTimelineChart` (the
cross-fight historical timeline on `/players/[account_name]`)
and the v0.8.9 plan/002 shipped `PerFightTimelineChart` (the
per-fight temporal view on `/fights/[id]`). Both charts render
**3 polylines** (damage / healing / buff-removal), use
**per-series normalisation to 0-100%** of per-series max,
expose a **SVG-native `<title>` tooltip** on the parent
`<g>` group, and use **decade-style X-axis labels** with
`Intl.DateTimeFormat` (8-tick cap, first + last labels always
drawn). The duplicated rendering logic is ~120 lines of
near-identical TSX in `web/src/components/`.

The v0.8.9 plan/002 entry (the per-fight timeline tab) noted
this duplication as a deferred refactor:

> "A v0.9.0 refactor could extract a shared
> `<TimelineChart>` base component; the two components'
> data shapes (per-series normalisation, SVG-native
> `<title>` tooltip, decade-style X-axis labels) are
> identical."

The same plan/002 entry also noted that the new
`GET /api/v1/fights/{id}/timeline?window_s=5` route shares
its `?window_s=` query param with the pre-existing
`GET /api/v1/fights/{id}/events?window_s=5` route. The page
fetches both independently with hardcoded `window_s=5`
defaults; a future cycle could surface a single
"window size" preference on the page that drives both
endpoints. The same applies to the v0.8.0 player timeline
(which uses its own pagination rather than `window_s`).

A combined S-effort refactor that DRYs the 2 chart
components + adds the unified window-size preference to
both pages is the right v0.9.0 plan/001.

## Goal

1. Extract a new shared `<TimelineChart>` base component
   that encapsulates the duplicated SVG rendering logic
   (per-series normalisation, `<title>` tooltip, decade-style
   X-axis labels, empty-state panel, legend swatches).
2. Refactor `PlayerTimelineChart` (v0.8.0) to wrap
   `<TimelineChart>` with no behaviour change.
3. Refactor `PerFightTimelineChart` (v0.8.9) to wrap
   `<TimelineChart>` with no behaviour change.
4. Add a "Window size" preference UI on `/fights/[id]`
   (5s / 10s / 30s / 60s buttons) that drives BOTH
   `?window_s=` params (events + timeline) in a single
   navigation, so the grid buckets + the temporal chart
   are guaranteed to align temporally.
5. Add a "Window size" preference UI on
   `/players/[account_name]` that drives the cross-fight
   timeline's pagination window.

The two refactors are independent and ship in a single
plan; the unified window-size UI is a small Server-Component
change (no new client state required — the buttons are
links that update the `?window_s=` URL search param).

## Files in scope

- `web/src/components/TimelineChart.tsx` (NEW, ~120 lines):
  the shared base component. Takes a generic
  `TimelinePoint` shape (or accepts 3 series directly) +
  a label formatter + a Y-axis legend label. The render
  function emits the 3 polylines + the SVG-native `<title>`
  tooltip on the parent `<g>` + the decade-style X-axis
  labels + the empty-state panel.
- `web/src/components/PlayerTimelineChart.tsx` (refactor):
  the existing component becomes a thin wrapper that
  prepares the data in the `TimelineChart`-compatible
  shape and delegates the SVG render. Net change: ~80
  lines removed, ~10 lines added.
- `web/src/components/PerFightTimelineChart.tsx`
  (refactor): same shape as the `PlayerTimelineChart`
  refactor. The component becomes a thin wrapper.
- `web/src/app/fights/[id]/page.tsx` (extend): add the
  "Window size" button group above the per-target trio
  (between the heading + the first roll-up grid). The
  buttons are links to the same route with the
  `?window_s=` URL param updated. The default is `5`
  (matching the v0.8.9 plan/002 contract).
- `web/src/app/players/[account_name]/page.tsx`
  (extend): same "Window size" button group pattern,
  placed above the historical timeline. The button
  values map to the cross-fight timeline's pagination
  window (e.g. 1d / 7d / 30d).
- `web/src/components/TimelineChart.test.tsx` (NEW, ~6
  vitest cases): the shared component's rendering contract
  (empty state, single point, multi-point, tooltip presence,
  legend swatches, decade-style X-axis labels).
- `web/src/components/PlayerTimelineChart.test.tsx`
  (refactor): the existing 6 cases are ported to the
  refactored wrapper; no behaviour change.
- `web/src/components/PerFightTimelineChart.test.tsx`
  (refactor): the existing 6 cases are ported to the
  refactored wrapper; no behaviour change.
- `web/src/lib/api.ts` (extend): `fetchFightTimeline` +
  `fetchFightEvents` both accept the `?window_s=` param
  from the URL search param rather than a hardcoded
  default. The Server Component reads `searchParams.window_s`
  and forwards it to both fetchers.
- `web/tests/e2e/fights.spec.ts` (extend): the existing 2
  tests gain a new "Window size" button visibility check +
  a click-through assertion that confirms the
  `?window_s=10` URL drives both endpoints.

## Files explicitly out of scope

- The per-fight timeline data shape (unchanged; the
  refactor is purely presentational).
- The player timeline data shape (unchanged).
- The events endpoint (unchanged).
- A future "compare 2 fights" view (deferred to v0.9.0+;
  would use the shared `<TimelineChart>` but the
  side-by-side layout is a separate concern).
- A future visual regression dashboard (deferred to
  v0.9.0+; could surface the `?window_s=` history).

## Steps

1. **Read both chart components** to confirm the
   duplicated rendering logic surface (the 120 lines
   of near-identical TSX).
2. **Create `web/src/components/TimelineChart.tsx`**:
   the shared base component. The render function takes
   3 series + a label formatter + a Y-axis legend label
   and emits the 3 polylines + the SVG-native `<title>`
   tooltip on the parent `<g>` + the decade-style X-axis
   labels + the empty-state panel + the legend swatches.
   The component is a pure Server Component (no client
   state; no effects).
3. **Refactor `PlayerTimelineChart.tsx`**: the existing
   component becomes a thin wrapper that prepares the
   data in the `TimelineChart`-compatible shape and
   delegates the SVG render. The public prop interface
   is unchanged (the page-level consumer doesn't need to
   change).
4. **Refactor `PerFightTimelineChart.tsx`**: same shape
   as the `PlayerTimelineChart` refactor. The public
   prop interface is unchanged.
5. **Add the "Window size" button group to
   `/fights/[id]`**: a small Server Component (inline
   in the page or extracted to a new
   `WindowSizeSelector` component) that renders 4
   buttons (5s / 10s / 30s / 60s) as links to the same
   route with the `?window_s=` URL param updated. The
   active button is highlighted via the `?window_s=`
   current value.
6. **Add the "Window size" button group to
   `/players/[account_name]`**: same pattern, placed
   above the historical timeline. The button values
   map to the cross-fight timeline's pagination
   window (1d / 7d / 30d).
7. **Update `web/src/lib/api.ts`**: the `fetchFightTimeline`
   + `fetchFightEvents` helpers accept the `window_s` from
   the URL search param. The Server Component reads
   `searchParams.window_s` and forwards it to both
   fetchers; the page no longer hardcodes `5`.
8. **Port the vitest cases** for both chart components
   to the refactored wrapper. The behaviour assertions
   are unchanged; the import paths update.
9. **Extend `web/tests/e2e/fights.spec.ts`**: the
   existing 2 tests gain a new "Window size" button
   visibility check + a click-through assertion.
10. **Run the validation gates** (see Test plan's
    "Validation" subsection).

## Test plan

- **6 new vitest cases in
  `web/src/components/TimelineChart.test.tsx`**:
  - `test_timeline_chart_empty_state`:
    3 empty series -> the "No data" panel renders
    + no polylines + no legend swatches.
  - `test_timeline_chart_single_point`:
    1 point per series (3 total) -> 3 circles, 3 paths,
    3 legend swatches; no X-axis labels (the
    decade-style labelling requires >= 2 points).
  - `test_timeline_chart_multi_point`:
    10 points per series (30 total) -> 30 circles, 3
    paths, 3 legend swatches, 8 X-axis labels
    (the 8-tick cap).
  - `test_timeline_chart_normalisation`:
    series A = [0, 1000, 2000] (max 2000), series B =
    [0, 500, 1000] (max 1000), series C = [0, 250, 500]
    (max 500) -> all 3 series are normalised to
    0-100% of their respective max; the highest
    circle in each series sits at the same Y coordinate.
  - `test_timeline_chart_svg_title_tooltip`:
    hovering any of the 3 sibling dots surfaces the
    native SVG `<title>` tooltip with the
    pre-formatted label (e.g. "00:30 — 1.2k damage").
  - `test_timeline_chart_legend_swatches`:
    3 legend swatches render in the correct order
    (damage / healing / buff-removal); each swatch
    is a small `<rect>` with the series colour.
- **6 refactored vitest cases in
  `web/src/components/PlayerTimelineChart.test.tsx`**:
  the existing 6 cases are ported to the refactored
  wrapper. The behaviour assertions are unchanged;
  the import paths update.
- **6 refactored vitest cases in
  `web/src/components/PerFightTimelineChart.test.tsx`**:
  same pattern as the `PlayerTimelineChart` refactor.
- **2 extended e2e tests in
  `web/tests/e2e/fights.spec.ts`**: the existing 2
  tests gain a new "Window size" button visibility
  check + a click-through assertion that confirms
  the `?window_s=10` URL drives both endpoints.
- **No new pytest cases** (no Python changes).
- **No new analytics aggregators** (this plan is
  purely a web refactor + UI improvement).

## Validation

- `pnpm tsc --noEmit`: clean (TSC=0; the new
  `TimelineChart` + the refactored wrappers type-check).
- `pnpm test:unit`: clean (VITEST=0; 6 new chart
  vitest cases + 12 refactored chart vitest cases
  + 70+ pre-existing cases pass).
- `pnpm exec playwright test`: clean
  (PLAYWRIGHT=0; the 2 existing fights.spec.ts tests
  extended + 5 other pre-existing tests pass).
- The "Window size" button group is visible on
  `/fights/[id]` (the v0.8.9 plan/002 spec asserts
  the section is rendered; the new buttons are
  above the per-target trio).
- The "Window size" button group is visible on
  `/players/[account_name]`.
- The visual-regression spec still passes 8/8
  against the existing baselines (no UI regression
  in the chart rendering).

## Done criteria

- `web/src/components/TimelineChart.tsx` exists and
  is the single source of truth for the timeline
  rendering logic.
- `PlayerTimelineChart` + `PerFightTimelineChart`
  are thin wrappers that delegate the SVG render to
  `<TimelineChart>`. The public prop interfaces are
  unchanged.
- The "Window size" button group is visible on
  `/fights/[id]` + `/players/[account_name]`.
- Clicking a "Window size" button updates the
  `?window_s=` URL search param + drives both
  endpoints (on `/fights/[id]`) or the pagination
  (on `/players/[account_name]`) in a single
  navigation.
- 6 new vitest cases + 12 refactored vitest cases
  + 2 extended e2e tests pass; pre-existing tests
  still pass (no regression).
- The visual-regression spec still passes 8/8
  (the chart refactor doesn't change the rendered
  output).

## Maintenance note

- A v0.9.0+ "compare 2 fights" view can use the
  shared `<TimelineChart>` as the base component;
  the side-by-side layout is a separate concern.
- The "Window size" preference is per-route (not
  persisted across navigations); a future v0.9.0+
  could store the preference in `localStorage` and
  apply it on every page load. Out of scope.
- The `<TimelineChart>` base component is generic
  enough to render any 3-series temporal data; a
  future v0.9.0+ "damage-type breakdown" chart
  (3 damage types: power / condition / other) could
  also use the base.

## Escape hatch

- If the 2 chart components have incompatible
  data shapes (e.g. one normalises to per-series
  max while the other normalises to a global max),
  STOP and report back. The fallback is to keep
  the 2 components separate + add a smaller
  `<TimelineLegend>` shared sub-component (the
  legend swatches are the most-duplicated 20 lines).
  The `<TimelineChart>` refactor can ship
  incrementally: first the legend, then the
  per-series normalisation, then the decade-style
  X-axis labels.
- If the "Window size" button group breaks the
  page's Server Component rendering (e.g. the
  `searchParams` prop is not properly threaded),
  STOP and report back. The fallback is to scope
  the window-size UI to a Client Component
  wrapper that updates the URL via `useRouter` +
  `useSearchParams`. The Server Component can
  still read the initial value from the URL on
  first render.
- If the vitest port for the refactored wrappers
  surfaces a regression in the chart's rendered
  output (e.g. a missing axis label or a wrong
  tooltip), revert the refactor + ship the
  "Window size" UI as a standalone plan/001
  (S effort, no refactor).
