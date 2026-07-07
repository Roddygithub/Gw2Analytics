# Plan 003 — Visual regression suite expansion: 4 more tracked PNGs

## Context

The v0.8.9 plan/003 (commit `27e1340`) shipped a visual
regression spec that pixel-diffs 8 tracked PNGs at
`docs/screenshots/` against fresh full-page captures
of the corresponding routes. The 8 PNGs are:

- `01-landing.png` (the `/` route)
- `02-account.png` (the `/account` route)
- `03-upload.png` (the `/upload` route)
- `04-fights.png` (the `/fights` route)
- `05-players.png` (the `/players` route)
- `06-player-profile-with-timeline.png` (the
  `/players/TestAccount.1234` route)
- `07-player-empty-timeline.png` (a fixture-edge-state
  render against `/players/empty-history.5678`)
- `08-fight-drilldown.png` (a fixture-edge-state
  render against `/fights/fixture-fight-001`)

The 8 PNGs cover the "default state" of each route but
miss several important UI states that v0.8.9 shipped:

- `/fights/[id]` with a **second fixture fight** (a
  different shape than `fixture-fight-001`)
- `/players` with a **sort applied** (e.g. `?sort=damage`)
  — surfaces the AG Grid sort affordance
- `/fights/[id]` with the **per-fight timeline** in
  view (the v0.8.9 plan/002 added the section; the
  existing `08-fight-drilldown.png` doesn't have it
  because the section ships later in the v0.8.9 cycle)
- `/account` with a **non-default timezone** (the
  v0.8.9 plan/001 added `?tz=Europe/Paris`; the
  existing `02-account.png` doesn't have it)

Each of these is a high-leverage test target: a UI
regression on any of them would not be caught by the
existing 8 PNGs. Adding 4 more PNGs is a clean S-effort
follow-up.

The visual-regression spec is data-driven (the
`VISUAL_REGRESSION_CASES` const array at the top of
`web/tests/e2e/visual-regression.spec.ts`); adding 4
more entries is a 4-line change in the array + 4
more `pnpm screenshots --persist` captures. The
spec's per-test loop picks them up automatically.

## Goal

Add 4 more tracked PNGs to `docs/screenshots/`:

- `09-fight-drilldown-populated.png` — a second
  fixture fight with a different shape (more
  agents, more events, different duration). The
  mock server already serves multiple fixture
  fights; the v0.8.9 plan/003 chose
  `fixture-fight-001` for `08-fight-drilldown.png`;
  the new PNG uses a different fixture (e.g.
  `fixture-fight-002`).
- `10-players-with-sort.png` — `/players?sort=damage`,
  surfaces the AG Grid sort affordance (the column
  header has a sort indicator + the rows are
  reordered). The sort is a client-side AG Grid
  feature; the baseline captures the post-sort
  state.
- `11-fight-with-timeline.png` — `/fights/fixture-fight-001`
  with the per-fight timeline section visible
  (the v0.8.9 plan/002 section). The existing
  `08-fight-drilldown.png` doesn't have the
  timeline; the new PNG does. This locks the
  v0.8.9 plan/002 rendering.
- `12-account-with-tz.png` — `/account?tz=Europe/Paris`,
  surfaces the v0.8.9 plan/001 timezone display.
  The existing `02-account.png` doesn't have a
  timezone param; the new PNG does.

The spec's `VISUAL_REGRESSION_CASES` array gains 4
more entries; the new PNGs are captured by
`pnpm screenshots --persist` (after extending the
`PAGES` const in `web/scripts/screenshots.mjs`).

## Files in scope

- `web/scripts/screenshots.mjs` (extend): the
  `PAGES` const gains 4 more entries with the
  routes + wait selectors + extra delays. The new
  entries follow the same `(label, route, waitFor,
  extraDelay)` shape as the existing 8.
- `web/tests/e2e/visual-regression.spec.ts`
  (extend): the `VISUAL_REGRESSION_CASES` const
  gains 4 more entries with the names + routes +
  baseline filenames. The spec's per-test loop
  picks them up automatically.
- `docs/screenshots/09-fight-drilldown-populated.png`
  (NEW, tracked): the second-fixture-fight
  capture.
- `docs/screenshots/10-players-with-sort.png`
  (NEW, tracked): the sorted-players capture.
- `docs/screenshots/11-fight-with-timeline.png`
  (NEW, tracked): the timeline-section-visible
  capture.
- `docs/screenshots/12-account-with-tz.png`
  (NEW, tracked): the timezone-displayed
  capture.
- `web/README.md` (extend): the "Screenshots"
  table in the README gains 4 more rows for the
  new PNGs. The `## Visual regression` section
  (added in v0.8.9 chore(ci+docs) commit
  `04838a9`) is unchanged (the workflow is
  identical for 8 or 12 PNGs).
- `CHANGELOG.md` (no change for this commit):
  the v0.9.0 cycle close-out commit covers the
  CHANGELOG entry.
- `web/tests/e2e/visual-regression.spec.ts`
  (no additional change): the data-driven loop
  picks up the 4 new entries automatically.

## Files explicitly out of scope

- A future "per-fixture visual regression" suite
  (one PNG per fixture; deferred to v0.9.0+; the
  current 4 additions are enough to cover the
  v0.8.9 changes).
- A future "cross-browser visual regression"
  suite (Firefox + WebKit in addition to
  Chromium; deferred until the project needs
  cross-browser coverage, which is currently
  N/A).
- A future "component-level visual regression"
  suite (component snapshots via
  `react-test-renderer` or similar; deferred to
  v0.9.0+).
- The pixelmatch threshold (the v0.8.9 chore
  commit `04838a9` lowered the per-pixel
  threshold from 0.1 to 0.05; this plan
  inherits the stricter value).

## Steps

1. **Identify the 4 new PNGs** (already done in
   the Goal section above).
2. **Extend the `PAGES` const in
   `web/scripts/screenshots.mjs`** with 4 more
   entries. Each entry has the same
   `(label, route, waitFor, extraDelay)` shape
   as the existing 8. The new entries:
   - `["09-fight-drilldown-populated",
     "/fights/fixture-fight-002",
     "svg[aria-label='Per-bucket event damage and healing']",
     800]`
   - `["10-players-with-sort",
     "/players?sort=damage",
     ".ag-root",
     1200]`
   - `["11-fight-with-timeline",
     "/fights/fixture-fight-001",
     "svg[aria-label='Per-fight timeline']",
     1500]`
   - `["12-account-with-tz",
     "/account?tz=Europe/Paris",
     null,
     200]`
3. **Extend the `VISUAL_REGRESSION_CASES` const
   in `web/tests/e2e/visual-regression.spec.ts`**
   with 4 more entries:
   - `{ name: "fight-drilldown-populated",
     route: "/fights/fixture-fight-002",
     baseline: "09-fight-drilldown-populated.png" }`
   - `{ name: "players-with-sort",
     route: "/players?sort=damage",
     baseline: "10-players-with-sort.png" }`
   - `{ name: "fight-with-timeline",
     route: "/fights/fixture-fight-001",
     baseline: "11-fight-with-timeline.png" }`
   - `{ name: "account-with-tz",
     route: "/account?tz=Europe/Paris",
     baseline: "12-account-with-tz.png" }`
4. **Capture the 4 new PNGs** by running
   `pnpm screenshots --persist` from the `web/`
   directory. The script writes the 4 PNGs to
   `screenshots/` (gitignored) + mirrors them
   into `docs/screenshots/` (tracked).
5. **Verify the spec picks up the 4 new entries**
   by running
   `pnpm exec playwright test --project=visual-regression`.
   The output should show 12 passed (the original
   8 + the new 4).
6. **Update `web/README.md`** to add 4 more rows
   to the "Screenshots" table. The table maps
   the 12 PNGs to their routes + their role
   (default state / fixture-edge-state / v0.8.9
   feature).
7. **Run the validation gates** (see Test plan's
   "Validation" subsection).

## Test plan

- **4 new visual-regression tests** in
  `web/tests/e2e/visual-regression.spec.ts` (one
  per new PNG). Each test is the same shape
  (navigate -> screenshot -> diff -> assert) as
  the existing 8. The data-driven loop picks
  them up automatically; no new test code is
  written beyond the 4 new entries in the
  `VISUAL_REGRESSION_CASES` const.
- **No new pytest cases** (no Python changes).
- **No new vitest cases** (no web-component
  changes).
- **No new e2e tests** (the visual-regression
  tests are the 4 new e2e tests; they don't
  add to the 6 pre-existing e2e tests).

## Validation

- `pnpm tsc --noEmit`: clean (TSC=0; the new
  `VISUAL_REGRESSION_CASES` entries type-check).
- `pnpm exec playwright test --project=visual-regression`:
  12 passed (PLAYWRIGHT_VR=0; the original 8
  + the new 4 = 12 PNGs all match their
  baselines).
- `pnpm exec playwright test` (default,
  no `--project=visual-regression`): 6 passed
  (PLAYWRIGHT=0; the visual-regression spec is
  filtered out by the `--project=visual-regression`
  flag, so the default suite still has the 6
  pre-existing tests + the 1 new visual-
  regression test that runs by default — wait,
  actually the visual-regression spec is
  filtered out by the `grep: /visual regression/`
  flag, so the default suite has the 6 pre-existing
  tests + 0 new tests).
- The 4 new PNGs are tracked at
  `docs/screenshots/09-fight-drilldown-populated.png`
  + `10-players-with-sort.png` +
  `11-fight-with-timeline.png` +
  `12-account-with-tz.png`.

## Done criteria

- `pnpm exec playwright test --project=visual-regression`
  passes 12/12 (the original 8 + the new 4).
- The 4 new PNGs are tracked at
  `docs/screenshots/`.
- `web/README.md`'s "Screenshots" table is
  updated to list all 12 PNGs.
- The CI step is unchanged (the
  `--project=visual-regression` filter + the
  `if: failure() && github.event_name == 'pull_request'`
  artifact upload apply to the 12-PNG suite
  exactly as they applied to the 8-PNG suite).

## Maintenance note

- The 12 PNGs are now the canonical set of
  visual-regression baselines. A future v0.9.0+
  could add 4 more (e.g. the v0.9.0 plan/002
  profession filter states, the v0.9.0 plan/001
  window-size states) to bring the total to
  16 PNGs.
- The data-driven loop in the spec handles
  arbitrary N PNGs; no code change is needed
  to add more in future plans.
- The `pnpm screenshots --persist` workflow
  (documented in CONTRIBUTING.md) handles
  arbitrary N PNGs; no script change is needed.

## Escape hatch

- If one of the 4 new PNGs is unstable across
  runs (e.g. the AG Grid sort indicator is
  sometimes drawn with a different glyph), drop
  that PNG from the suite + ship the other 3.
  The suite's value is in catching UI regressions;
  a flaky PNG is worse than no PNG.
- If the `web/scripts/screenshots.mjs` PAGES
  array grows too long (> 20 entries), extract
  the PNG list to a separate `web/scripts/screenshots.data.mjs`
  + import it in `screenshots.mjs`. Out of scope
  for v0.9.0 plan/003; defer to v0.9.0+ if
  the count grows.
- If the visual-regression spec's runtime grows
  too long (currently ~2-4 s for 8 PNGs; 12 PNGs
  would be ~3-6 s), narrow the suite to the
  8 most-leverage PNGs (drop the 4 lowest-
  leverage additions). The v0.8.9 plan/003
  noted this trade-off in its "Maintenance
  note" section.
