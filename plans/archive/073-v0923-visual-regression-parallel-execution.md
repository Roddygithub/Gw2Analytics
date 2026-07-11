# Plan 073 — v0.9.23: enable `test.describe.parallel` for the 8 visual-regression cases

## Drift base

`44ea862`. Refactor only — additive, no migration. The
test behaviour (assertions, diff threshold, output
filenames) is unchanged; only the execution mode changes.

## Surface

`web/tests/e2e/visual-regression.spec.ts` (1-line change:
`test.describe(...)` → `test.describe.parallel(...)`).

## Finding

`visual-regression.spec.ts` uses the default
`test.describe(...)` (serial execution within the
describe block). The 8 cases are independent (different
routes + baselines; no shared state between cases), so
the serial execution is a missed wall-clock optimization.

Each case is ~200-500 ms of browser time (per the spec's
docstring: "a fresh full-page screenshot per route is
~200-500 ms of browser time"). Serial execution:
8 cases × 350 ms average = ~2.8 s per CI run.

Parallel execution: with `workers: isCI ? 2 : undefined`
(per `playwright.config.ts`), the 8 cases are split
across 2 workers = 4 cases per worker = ~1.4 s per CI
run. **Saves ~1.4 s per CI run** (50% reduction in the
visual-regression wall-clock time).

The visual-regression suite is gated to PRs only (per
CONTRIBUTING.md §"Visual regression" + the
`.github/workflows/ci.yml` "Visual regression e2e (PR
only)" step). The CI savings apply to PRs, not to
pushes to `main` (the visual-regression step is skipped
on main pushes). The dev-loop savings apply to local
runs (where the default is `workers: undefined` =
Playwright default = `os.cpus().length - 1` workers).

The 8 cases are independent: each uses a fresh
`page` (Playwright's per-test fixture), each captures
to a unique temp file (`.tmp-${baseline}`), each
diff-write to a unique diff PNG (`${baseline}`). No
shared state between cases. The `DIFF_OUTPUT_DIR` is
the same for all cases, but `mkdir` is idempotent +
`writeFile` is per-call atomic + the cleanup is
`best-effort` (the docstring notes: "the temp file is
in a gitignored directory so a stale file is
harmless").

## Fix

1. **Change `test.describe(...)` to `test.describe.parallel(...)`**
   in `visual-regression.spec.ts`:

   ```ts
   test.describe.parallel("visual regression (v0.8.9 plan/003)", () => {
     // ... existing test.use({ viewport: { width: 1440, height: 900 } });
     // ... existing for (const { name, route, baseline } of VISUAL_REGRESSION_CASES) { ... }
   });
   ```

2. **Verify the per-test fixture isolation**: Playwright
   creates a fresh `page` per test (per the canonical
   Playwright test isolation model). The `test.use({...})`
   viewport setting is also per-test. The
   `VISUAL_REGRESSION_CASES` is `ReadonlyArray<>` (per
   plan 072) so no test mutates the array. The
   `BASELINE_DIR` + `DIFF_OUTPUT_DIR` are read-only paths.
   The `pageerror` listener is not used in this spec
   (per the spec's design — visual regression tests
   don't assert on uncaught exceptions; the diff
   itself catches the regression).

3. **Verify the diff-output write is race-free**:
   - `mkdir(DIFF_OUTPUT_DIR, { recursive: true })` —
     idempotent across concurrent calls.
   - `writeFile(diffPath, PNG.sync.write(diffPng))` —
     atomic per write; the last write wins (acceptable
     because the diff PNG is a "visual debug artifact";
     the test failure message is the canonical signal,
     not the diff PNG).
   - `unlink(tempPath).catch(() => {})` — best-effort
     cleanup; the temp file is in a gitignored
     directory.

## Why `parallel` (not `serial`)

The `test.describe.serial(...)` is the opposite of
`parallel`: it forces serial execution even when the
test runner could parallelize. The default
`test.describe(...)` is serial within the block, but
cases can be parallelized across worker processes. The
`.parallel` modifier explicitly opts the block into
parallel execution within the worker's test pool.

For the visual-regression spec, `.parallel` is the
correct modifier because:
- The 8 cases are independent.
- The default Playwright worker pool (2 in CI, default
  in local) can parallelize 2-4 cases at a time.
- The `DIFF_OUTPUT_DIR` is shared but the writes are
  per-case (different filenames).

## Why not parallelize the entire spec file

Playwright runs all spec files in parallel by default
(per the `fullyParallel: true` setting in
`playwright.config.ts`). The `.parallel` modifier is for
`describe` blocks WITHIN a spec file. The visual-
regression spec is the only spec with multiple
independent cases; the other specs (fights, players,
etc.) have a small number of tests (1-8) that may have
shared setup (e.g., `beforeEach`).

## Risks

- The `DIFF_OUTPUT_DIR` is shared across all 8 cases.
  If 2 cases fail simultaneously, they both call
  `mkdir(DIFF_OUTPUT_DIR, { recursive: true })` +
  `writeFile(diffPath, ...)`. The `mkdir` is idempotent
  (no-op on existing dir). The `writeFile` is per-call
  atomic (no partial writes). The race is benign.
- The `tempPath` (`join(DIFF_OUTPUT_DIR, ".tmp-${baseline}")`)
  is unique per case (the baseline name is the unique
  key). No collision between cases.
- The Playwright `test.describe.parallel(...)` requires
  Playwright 1.18+ (per the docs). The project's
  `@playwright/test` is `^1.61.1` (per `package.json`)
  — the `^1.61.1` semver is a major-version range; the
  minimum version that satisfies `^1.61.1` is `1.61.1`.
  The `.parallel` modifier is available.
- The local dev loop's wall-clock reduction (50%) is a
  noticeable improvement for a developer iterating on
  UI changes (the visual-regression suite catches the
  changes within ~1.4 s instead of ~2.8 s).

## Tests

1. `test_spec_uses_parallel_modifier` — read
   `visual-regression.spec.ts`; assert the test uses
   `test.describe.parallel(...)` (not the default
   `test.describe(...)`).
2. `test_parallel_execution_does_not_collide_temp_files` —
   monkeypatch `process.cwd()` to return a temp dir;
   run 2 cases in parallel; assert the 2 temp files
   (`.tmp-01-landing.png` + `.tmp-02-account.png`)
   exist independently.
3. `test_parallel_execution_writes_independent_diff_pngs` —
   simulate 2 cases failing simultaneously; assert both
   diff PNGs are written to the same `DIFF_OUTPUT_DIR`
   with different filenames.
4. `test_parallel_execution_preserves_8_cases` — run
   `pnpm exec playwright test --project=visual-regression`
   (per the CI invocation); assert all 8 cases run +
   pass (the parallel mode does not skip any case).
5. `test_parallel_execution_wall_clock_improvement` —
   measure wall-clock time for the 8 cases in serial
   vs parallel; assert parallel is faster (sanity
   check on the perf claim).

## Rejected alternatives

- **Use Playwright's `--workers=N` flag** to force more
  workers: tempting (more parallelism). The CI
  invocation is `pnpm exec playwright test
  --project=visual-regression` (per the CI workflow);
  the `--workers` flag is a global config that affects
  all specs, not just visual-regression. Increasing
  workers globally may cause port conflicts (the mock
  server runs on port 8080) + browser memory pressure.
  The `.parallel` modifier is per-spec, which is the
  canonical scoping.
- **Move the 8 cases to separate spec files** (1 per
  case): tempting (independent `test.describe` blocks
  can be parallelized by Playwright's per-file model).
  The 8 separate spec files would be a maintenance
  burden (8 files to keep in sync instead of 1); the
  `.parallel` modifier achieves the same wall-clock
  reduction with a 1-line change.
- **Skip the parallel mode** (status quo is fine):
  tempting (the 2.8 s is not catastrophic). The 50%
  wall-clock reduction is a free win (no risk, no
  behavior change). The plan ships the change.
- **Add `test.describe.configure({ mode: "parallel" })`**
  at the top of the spec: equivalent to the `.parallel`
  modifier. The `.parallel` modifier is the
  per-describe-block scope; `.configure({ mode: ... })`
  is the file-scope (affects all `describe` blocks in
  the file). The visual-regression spec has 1 describe
  block; either approach is equivalent. The
  `.parallel` modifier is more explicit (per-describe
  intent).
- **Add a CI `--retries=2` for the visual-regression
  suite** (catch flaky PNGs): tempting (anti-flake).
  The `.parallel` mode + the existing `retries: isCI
  ? 2 : 0` (per `playwright.config.ts`) already retries
  2x on CI. The plan doesn't change the retry policy.
