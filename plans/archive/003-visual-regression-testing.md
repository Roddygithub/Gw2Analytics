# Plan 003 — Visual regression testing on the 8 tracked `docs/screenshots/*.png`

## Context

The v0.8.8 cycle shipped 8 tracked PNGs at `docs/screenshots/`
(commits `6fc4fcb` + the `web/scripts/screenshots.mjs --persist`
flag):

- `01-landing.png` (the `/` route)
- `02-account.png` (the `/account` route)
- `03-upload.png` (the `/upload` route)
- `04-fights.png` (the `/fights` route)
- `05-players.png` (the `/players` route)
- `06-player-profile-with-timeline.png` (the
  `/players/[account_name]` route)
- `07-player-empty-timeline.png` (a fixture-edge-state
  render against `/players/empty-history.5678`)
- `08-fight-drilldown.png` (a fixture-edge-state
  render against `/fights/fixture-fight-001`)

The PNGs are visual evidence of the app's state, but there's
**no automated check that a UI refactor doesn't change them**.
A future PR that accidentally changes the AG Grid's row height
or the per-target trio's column order would not be caught by
the existing 6 Playwright specs (which only assert HTTP status
+ DOM presence + heading visibility).

The v0.8.8 plan/002 entry considered this and explicitly
deferred it:

> **Visual regression testing**: `web/scripts/screenshots.mjs`
> already captures the 8 PNGs; a separate `playwright test`
> visual-regression job could diff them. Out of scope here —
> would need a baseline-locking strategy.

The "baseline-locking strategy" is straightforward:
`playwright.screenshot()` captures a fresh full-page PNG
to a temp file, `pixelmatch` diffs it against the checked-in
baseline at `docs/screenshots/<n>-<name>.png`, and the spec
fails if the diff is > 1% of the total pixel count. The 1%
threshold is a tunable (the `0.01` constant at the top of
the spec); future cycles can lower it to 0.5% for stricter
diffing.

`pixelmatch` is a tiny npm package (~50 KB, no native deps,
no Node version constraints beyond the project's `>=20`).
`pngjs` is a 1-file peer dep that handles the PNG read.
Both are dev-only deps; the production `web/` bundle is
unaffected.

## Goal

A new Playwright spec at
`web/tests/e2e/visual-regression.spec.ts` that pixel-diffs
each of the 8 `docs/screenshots/*.png` against a fresh
full-page capture of the corresponding route. CI fails on
a diff > 1% of the total pixel count. The spec is gated on
PRs only (not on every push to `main`) to keep CI cost
down — a fresh full-page screenshot per route is ~200-500
ms of browser time, so 8 routes is 2-4 s of additional
CI per PR.

## Files in scope

- `web/package.json`: + `pixelmatch` + `pngjs` in
  `devDependencies` (both pure-JS, no native bindings).
- `web/tests/e2e/visual-regression.spec.ts` (NEW): the
  visual regression spec. Single `test.describe("visual
  regression", ...)` block with 8 `test()` cases (one
  per PNG). Each test:
  1. Navigates to the corresponding route.
  2. Captures a fresh full-page screenshot via
     `page.screenshot({ path: tempPath, fullPage: true })`.
  3. Reads the checked-in baseline via
     `readFile(join(DOCS_DIR, `${n}-${name}.png`))`.
  4. Decodes both via `pngjs`.
  5. Diffs them via `pixelmatch(...)`.
  6. Asserts `diffPixelCount / totalPixelCount < 0.01`.
  7. On failure, writes the diff PNG to
     `web/tests/e2e/.visual-regression-output/<n>-<name>-diff.png`
     so a developer can inspect the visual diff
     (a red highlight overlay on the changed pixels).
- `web/playwright.config.ts`: no structural changes
  needed; the new spec lives under the existing
  `testDir = "tests/e2e"`. A new
  `projects: [{ name: "visual-regression", grep:
  /visual regression/, ... }]` block isolates the
  visual-regression suite so `pnpm exec playwright test`
  (the default) doesn't run it (CI runs it explicitly
  via the new step).
- `.github/workflows/ci.yml`: 1 new step in the existing
  `lint-and-test` job, gated on `if: github.event_name ==
  'pull_request'` (PRs only, not pushes to `main`):
  - `name: Visual regression e2e (PR only)`
  - `run: pnpm exec playwright test --project=visual-regression`
  - `env: MOCK_PORT: 8080`
- `web/README.md`: new `## Visual regression` section
  in the `## OpenAPI regeneration` neighbourhood
  documenting the refresh workflow:
  - "When a UI refactor is intentional, the dev runs
    `pnpm screenshots --persist` to refresh the
    8 tracked PNGs + commits the updated files."
  - "When a CI failure surfaces, the dev inspects the
    diff PNG at
    `web/tests/e2e/.visual-regression-output/<n>-<name>-diff.png`
    (gitignored) to confirm whether the change is
    intentional."

## Files explicitly out of scope

- The existing 6 Playwright specs (the visual-regression
  spec is a 7th; doesn't touch the others).
- The mock-server (the visual-regression spec uses
  the real Next.js dev server + the real mock-server
  fixtures, not a new mock-server endpoint).
- `libs/gw2_analytics` (no Python changes).
- A future "per-component visual regression" suite
  (component-level snapshots via `react-test-renderer`
  or similar; deferred to v0.9.0+).
- A future "cross-browser visual regression" suite
  (Firefox + WebKit in addition to Chromium; deferred
  until the project needs cross-browser coverage,
  which is currently N/A since the v0.4.0-web
  decision was "Chromium-only for E2E").

## Steps

1. **Read `web/playwright.config.ts`** to confirm the
   testDir + webServer setup + the `projects` block
   pattern. The existing config has a single default
   project; the new visual-regression project is a
   sibling with a `grep` filter so the default
   `pnpm exec playwright test` doesn't run the
   visual-regression suite (CI runs it explicitly).
2. **Add `pixelmatch` + `pngjs` to
   `web/package.json` `devDependencies`** via
   `pnpm add -D pixelmatch pngjs`. The exact
   versions are `^7.1.0` (pixelmatch) + `^7.0.0`
   (pngjs); the project's `pnpm-lock.yaml` is
   regenerated.
3. **Add `.visual-regression-output/` to
   `web/.gitignore`**: the diff PNGs are written
   on failure only; gitignore them so they don't
   pollute `git status`.
4. **Create `web/tests/e2e/visual-regression.spec.ts`**:
   - Single `test.describe("visual regression",
     ...)` block.
   - 8 `test()` cases (one per PNG), each with the
     same shape (navigate -> screenshot -> diff ->
     assert). The cases are generated by a
     `VISUAL_REGRESSION_CASES` const array
     (the canonical pattern from the v0.8.0
     player-timeline tests):
     ```ts
     const VISUAL_REGRESSION_CASES: ReadonlyArray<{
       readonly name: string;  // "landing"
       readonly route: string; // "/"
       readonly baseline: string; // "01-landing.png"
     }> = [
       { name: "landing",          route: "/",                              baseline: "01-landing.png" },
       { name: "account",          route: "/account",                       baseline: "02-account.png" },
       { name: "upload",           route: "/upload",                        baseline: "03-upload.png" },
       { name: "fights",           route: "/fights",                        baseline: "04-fights.png" },
       { name: "players",          route: "/players",                       baseline: "05-players.png" },
       { name: "player-profile",   route: "/players/TestAccount.1234",      baseline: "06-player-profile-with-timeline.png" },
       { name: "player-empty",     route: "/players/empty-history.5678",    baseline: "07-player-empty-timeline.png" },
       { name: "fight-drilldown",  route: "/fights/fixture-fight-001",      baseline: "08-fight-drilldown.png" },
     ];
     ```
   - Each test: navigate to the route, screenshot to a
     temp file, read the baseline from
     `web/docs/screenshots/<baseline>`, diff via
     `pixelmatch`, assert `diffPixelCount /
     totalPixelCount < 0.01`. On failure, write the
     diff PNG to
     `web/tests/e2e/.visual-regression-output/<baseline>`
     (gitignored) so a developer can inspect.
5. **Add the new `projects` block to
   `web/playwright.config.ts`** with a
   `grep: /visual regression/` filter. The existing
   default project keeps its current shape (no grep
   filter).
6. **Add the new CI step to
   `.github/workflows/ci.yml`**: a new
   `Visual regression e2e (PR only)` step in the
   existing `lint-and-test` job, gated on
   `if: github.event_name == 'pull_request'`. The
   command is `pnpm exec playwright test
   --project=visual-regression`. The step does NOT
   fail the build on its own (the spec's internal
   assertions fail the build on > 1% diff; the
   step just runs the suite).
7. **Document the refresh workflow in `web/README.md`**
   in a new `## Visual regression` section. The
   section is short (~15 lines): 1 paragraph on
   the diff threshold + 1 paragraph on the refresh
   workflow + 1 paragraph on the diff PNG output.
8. **Add `.visual-regression-output/` to
   `web/.gitignore`** in the existing
   `tests/e2e/...` gitignore block.
9. **Run the validation gates** (see Test plan's
   "Validation" subsection). The first run should
   pass with diff = 0% (the v0.8.8 PNGs are
   byte-identical to what the new spec captures).
   If a diff > 0% surfaces, the v0.8.8 PNGs may
   be stale (e.g. font-rendering drift between
   the v0.8.8 capture host + the v0.8.9 spec
   host); refresh via `pnpm screenshots --persist`
   and commit the updated PNGs as a follow-up
   commit before merging this plan.

## Test plan

- **8 new Playwright tests in
  `web/tests/e2e/visual-regression.spec.ts`**
  (one per PNG). Each test is the same shape
  (navigate -> screenshot -> diff -> assert)
  parameterised by the `VISUAL_REGRESSION_CASES`
  const. The first run passes with diff = 0%;
  subsequent runs fail on a > 1% diff.
- **No new e2e tests in the existing 6 specs**:
  the visual-regression spec is a 7th spec
  under a new `projects` block; doesn't touch
  the others.
- **No new pytest cases** (no Python changes).
- **No new vitest cases** (no web-component
  changes).

## Validation

- `pnpm install --frozen-lockfile` (web/): the
  lockfile + the new `pixelmatch` + `pngjs` deps
  resolve cleanly.
- `pnpm tsc --noEmit` (web/): clean (TSC=0;
  the new spec's `import` statements type-check).
- `pnpm test:unit` (web/): clean (VITEST=0;
  the 70+ pre-existing cases still pass; the
  visual-regression spec is a Playwright spec,
  not a vitest case).
- `pnpm exec playwright test --project=visual-regression`:
  8 passed (PLAYWRIGHT=0; diff = 0% for all 8
  routes; the v0.8.8 PNGs are byte-identical to
  what the new spec captures).
- `pnpm exec playwright test --project=visual-regression`
  on a deliberate UI refactor (e.g. bumping
  the AG Grid row height by 2 px): the spec
  correctly fails on the affected PNG (e.g.
  `04-fights.png` + `05-players.png`); the
  other 6 PNGs pass. The diff PNG at
  `web/tests/e2e/.visual-regression-output/04-fights.png`
  surfaces the visual diff for the developer.
- The CI step is gated on PRs only
  (`if: github.event_name == 'pull_request'`),
  so pushes to `main` do NOT run the visual
  regression suite.

## Done criteria

- The visual-regression spec passes against the
  v0.8.8 baselines (diff = 0% for all 8 routes).
- A deliberate UI refactor (e.g. row height
  bump) fails the spec on the affected PNGs
  (e.g. 04-fights.png + 05-players.png).
- The CI step is gated on PRs only.
- The refresh workflow (`pnpm screenshots
  --persist`) is documented in `web/README.md`'s
  new `## Visual regression` section.
- The diff PNG output directory
  (`web/tests/e2e/.visual-regression-output/`)
  is gitignored.
- 8 new Playwright tests pass; the 6
  pre-existing tests + 70+ vitest cases still
  pass (no regression).

## Maintenance note

- The 1% threshold is a tunable (the `0.01`
  constant at the top of the spec). A future
  cycle could lower it to 0.5% for stricter
  diffing (catches font-rendering drift across
  Node versions).
- The spec is gated on PRs only to keep CI
  cost down. If CI cost becomes a concern, the
  spec could be further narrowed to "only the
  4 PNGs that are most likely to regress"
  (e.g. drop the 2 fixture-edge-state PNGs).
- The 8 baselines are tracked at
  `docs/screenshots/`. A future v0.9.0 could
  add a "visual regression dashboard" page
  that displays the latest captured PNGs +
  the diff-vs-baseline percentage for each
  route (a thin Server Component that reads
  from a CI artifact store). Out of scope
  for v0.8.9.

## Escape hatch

- If `pixelmatch` or `pngjs` is unavailable on
  the project's Node version, STOP and report
  back. Both packages target `node >= 18`; the
  project's `web/package.json` `engines.node` is
  `>=20`. The fallback is a hand-rolled
  pixel-diff via the canvas API or via a
  third-party alternative like
  `looks-same` (~3 MB, native deps); the
  fallback is heavier than the primary path.
- If the v0.8.8 baselines are not
  byte-identical to the new spec's captures
  on the first run (e.g. font-rendering drift
  between the v0.8.8 capture host + the v0.8.9
  spec host), the spec will fail on a
  > 0% diff. The recovery is to refresh the
  baselines via `pnpm screenshots --persist`
  and commit the updated PNGs as a follow-up
  commit before merging this plan. The first
  commit of this plan should not also refresh
  the baselines (that would conflate "ship the
  visual-regression spec" with "refresh the
  baselines" — two separate concerns).
- If the diff PNG output directory
  (`web/tests/e2e/.visual-regression-output/`)
  grows too large on a CI failure (e.g. an
  AG Grid refactor changes all 8 PNGs), add
  a cleanup step to the CI job:
  `if: always() && ! failure()` (cleanup only
  on success — preserve the diff PNGs on
  failure for developer inspection).
