# Plan 072 — v0.9.23: extract `VISUAL_REGRESSION_CASES` + `BASELINE_DIR` + `DIFF_OUTPUT_DIR` from `visual-regression.spec.ts` to a shared module

## Drift base

`44ea862`. Refactor only — additive, no migration. The
test behaviour is unchanged byte-for-byte.

## Surface

NEW `web/tests/e2e/_visual_regression.ts` (the shared
constants module),
`web/tests/e2e/visual-regression.spec.ts` (refactored to
import the constants).

## Finding

`visual-regression.spec.ts` (~220 lines) defines 3
module-level constants inline:

```ts
const DIFF_THRESHOLD = 0.01;

const VISUAL_REGRESSION_CASES: ReadonlyArray<{
  readonly name: string;
  readonly route: string;
  readonly baseline: string;
}> = [
  { name: "landing", route: "/", baseline: "01-landing.png" },
  { name: "account", route: "/account", baseline: "02-account.png" },
  // ... 6 more cases ...
];

const BASELINE_DIR = join(process.cwd(), "..", "docs", "screenshots");
const DIFF_OUTPUT_DIR = join(process.cwd(), "tests", "e2e", ".visual-regression-output");
```

The constants are:
- **`VISUAL_REGRESSION_CASES`** — the 8 (route, baseline)
  pairs. The list is the canonical source of truth for
  "which routes ship a tracked PNG". A future maintainer
  who adds a 9th route must update this list (and the
  `docs/screenshots/` directory + the
  `web/scripts/screenshots.mjs` PAGES array — 3 sites).
- **`BASELINE_DIR`** — the path to the tracked PNGs. A
  future maintainer who moves the screenshots directory
  (e.g., to `web/tests/e2e/__screenshots__/`) must update
  this path.
- **`DIFF_OUTPUT_DIR`** — the path to the failure-output
  diff PNGs. A future maintainer who renames or moves
  this directory must update this path.

The 3 constants are inline in the spec file. A future
maintainer who wants to ADD a 9th case must:
1. Add the entry to `VISUAL_REGRESSION_CASES`.
2. Add the route to the `PAGES` array in
   `web/scripts/screenshots.mjs` (per v0.9.6 plan 058).
3. Add the entry to `CONTRIBUTING.md` §"When to refresh
   the baselines" (per the 8 PNGs documentation).
4. Commit the new PNG to `docs/screenshots/`.
5. Refresh the baseline via `pnpm screenshots --persist`.

The 3 sites (1 + 2 + 3) are spread across 3 files. The
spec file's `VISUAL_REGRESSION_CASES` is 1 of the 3
"where the 8 routes are listed" sites.

Extracting the constants to a shared module:
- Makes the "where the 8 routes are listed" site a
  single import (the spec imports from
  `_visual_regression.ts`).
- Reduces the spec file from ~220 lines to ~150 lines
  (constants + setup + test body).
- Allows a future tool (e.g., a CI lint check that
  asserts the spec's cases + the screenshot script's
  PAGES are in sync) to import the cases from a single
  source.

## Fix

1. **NEW `web/tests/e2e/_visual_regression.ts`** with the
   3 constants + the `Case` type:

   ```ts
   import { join } from "node:path";

   /**
    * The 1% total-diff threshold for the visual-regression
    * suite. See CONTRIBUTING.md §"Threshold rationale" for
    * the empirical derivation.
    */
   export const DIFF_THRESHOLD = 0.01;

   /**
    * The 8 (route, baseline) pairs for the visual-regression
    * suite. The shape is:
    * - ``name``: the test title (used as the test display
    *   name + the diff output filename).
    * - ``route``: the route to navigate to.
    * - ``baseline``: the PNG filename under
    *   ``docs/screenshots/`` (the canonical tracked
    *   artifact).
    *
    * The list MUST stay in sync with:
    * 1. The PAGES array in ``web/scripts/screenshots.mjs``
    *    (the 8 cases the screenshot script captures).
    * 2. The "When to refresh the baselines" section in
    *    CONTRIBUTING.md (the 8 PNGs the doc references).
    * 3. The 8 PNGs committed under ``docs/screenshots/``.
    *
    * A CI drift check (future plan) can import this list
    * + the screenshot script's PAGES + the committed PNG
    * list to assert all 3 are in sync.
    */
   export interface VisualRegressionCase {
     readonly name: string;
     readonly route: string;
     readonly baseline: string;
   }

   export const VISUAL_REGRESSION_CASES: ReadonlyArray<VisualRegressionCase> = [
     { name: "landing", route: "/", baseline: "01-landing.png" },
     { name: "account", route: "/account", baseline: "02-account.png" },
     { name: "upload", route: "/upload", baseline: "03-upload.png" },
     { name: "fights", route: "/fights", baseline: "04-fights.png" },
     { name: "players", route: "/players", baseline: "05-players.png" },
     {
       name: "player-profile",
       route: "/players/TestAccount.1234",
       baseline: "06-player-profile-with-timeline.png",
     },
     {
       name: "player-empty-timeline",
       route: "/players/empty-history.5678",
       baseline: "07-player-empty-timeline.png",
     },
     {
       name: "fight-drilldown",
       route: "/fights/fixture-fight-001",
       baseline: "08-fight-drilldown.png",
     },
   ];

   /**
    * Path to the ``docs/screenshots/`` directory, relative
    * to the Playwright project root (``web/``). The
    * repo-root ``docs/screenshots/`` is the canonical
    * artifact store (tracked since v0.8.8); the Playwright
    * project root is ``web/`` so the relative path is
    * ``../docs/screenshots/``.
    */
   export const BASELINE_DIR = join(process.cwd(), "..", "docs", "screenshots");

   /**
    * Path to the diff PNG output directory (gitignored).
    * The directory is created lazily on the first failure;
    * on success it's left empty (or non-existent).
    */
   export const DIFF_OUTPUT_DIR = join(
     process.cwd(),
     "tests",
     "e2e",
     ".visual-regression-output",
   );
   ```

2. **Refactor `visual-regression.spec.ts`** to import the
   constants:

   ```ts
   import { promises as fs } from "node:fs";
   import { join } from "node:path";
   import { expect, test } from "@playwright/test";
   import { PNG } from "pngjs";
   import pixelmatch from "pixelmatch";
   import {
     BASELINE_DIR,
     DIFF_OUTPUT_DIR,
     DIFF_THRESHOLD,
     VISUAL_REGRESSION_CASES,
   } from "./_visual_regression";

   test.describe("visual regression (v0.8.9 plan/003)", () => {
     test.use({ viewport: { width: 1440, height: 900 } });

     for (const { name, route, baseline } of VISUAL_REGRESSION_CASES) {
       test(`${name} (${route}) matches ${baseline}`, async ({ page }) => {
         // ... rest of the test body unchanged ...
       });
     }
   });
   ```

   The spec's local `const DIFF_THRESHOLD = 0.01;` +
   `const VISUAL_REGRESSION_CASES = [...]` +
   `const BASELINE_DIR = ...; const DIFF_OUTPUT_DIR = ...;`
   are all removed (replaced by the imports).

## Why the `Case` type is exported

The `VisualRegressionCase` interface is exported so:
- A future plan (e.g., the CI drift check) can consume
  the type without redefining it.
- A future maintainer who wants to write a custom test
  (e.g., a per-case "fights" spec that tests only the
  fights routes) can import the type.

The export is forward-compat; the current spec doesn't
consume the type (it iterates the array directly).

## Why `ReadonlyArray<VisualRegressionCase>` (not `VisualRegressionCase[]`)

The `ReadonlyArray<>` type marks the array as
immutable (no `.push()`, `.pop()`, etc.). The spec
iterates the array via `for...of`; a future maintainer
who tries to mutate the array (e.g., to add a case
dynamically) gets a TypeScript error. The immutability
is a forward-compat guard.

## Why the underscore on `_visual_regression.ts`

Same as `_helpers.ts` (per plan 071): the leading
underscore is a canonical "internal helper" marker that
prevents future test runners from picking it up by
accident.

## Risks

- The shared module's `join(process.cwd(), ...)` path
  construction relies on the Playwright project root
  being the CWD when the spec runs. The current
  `playwright.config.ts` sets `testDir: "./tests/e2e"`
  (the spec's CWD is `web/`); the relative `..` is
  correct. A future config change that changes the CWD
  would break the path.
- The `DIFF_THRESHOLD` is a single-source-of-truth now;
  a future maintainer who changes it in the spec without
  updating the shared module would get a TypeScript
  error (the import is `const`, not `let`). This is the
  intended behavior.
- The 8 cases are still duplicated in 3 sites
  (shared module + `screenshots.mjs::PAGES` +
  `CONTRIBUTING.md`). The plan reduces the duplication
  to 2 sites (shared module + `screenshots.mjs`); the
  CONTRIBUTING.md prose is human-curated and the drift
  check is a future plan (not v0.9.23 scope).

## Tests

1. `test_shared_module_exports_all_3_constants` — import
   `_visual_regression.ts`; assert `DIFF_THRESHOLD`,
   `VISUAL_REGRESSION_CASES`, `BASELINE_DIR`,
   `DIFF_OUTPUT_DIR` are all exported.
2. `test_cases_array_has_8_entries` — assert
   `VISUAL_REGRESSION_CASES.length === 8`.
3. `test_cases_array_is_immutable` — try to mutate the
   array (e.g., `VISUAL_REGRESSION_CASES.push(...)`);
   assert the TypeScript compiler rejects the mutation.
4. `test_baseline_dir_points_to_docs_screenshots` —
   assert `BASELINE_DIR` ends with `docs/screenshots`
   (the canonical artifact store).
5. `test_diff_output_dir_is_gitignored` — read
   `web/.gitignore`; assert the diff output dir path is
   listed.
6. `test_spec_imports_from_shared_module` — read
   `visual-regression.spec.ts`; assert the file imports
   from `./_visual_regression` AND does NOT define the
   3 constants locally.
7. `test_cases_match_screenshots_script` — import the
   screenshot script's PAGES array (via a new export
   from the script); assert the routes match
   `VISUAL_REGRESSION_CASES.map(c => c.route)`.

## Rejected alternatives

- **Move the constants to a `playwright.config.ts`
  export**: tempting (single source of truth). The
  Playwright config is the test runner's config; mixing
  test data (the 8 cases) with runner config
  (`testDir`, `use.baseURL`, etc.) is a separation of
  concerns violation.
- **Generate the cases from a YAML / JSON file**: out of
  scope (the TypeScript array is the canonical
  representation; a future plan can add a YAML
  generator if the list grows).
- **Add the CI drift check (against the screenshot
  script + CONTRIBUTING.md) as part of this plan**: out
  of scope (the drift check is a future plan; this plan
  is the shared-module extraction only).
- **Move the `pixelmatch` + `pngjs` import + the diff
  computation logic to the shared module too**:
  tempting (the spec becomes a 1-page "for-loop
  tests"). The test body is logic (not just constants);
  the body is the canonical test code that future
  maintainers will read to understand the visual-
  regression flow. Moving the body to a helper would
  make the spec unreadable.
- **Use `import.meta.dirname` (Node 20.11+) instead of
  `process.cwd()`**: tempting (the path is more
  portable). The current code uses `process.cwd()` for
  consistency with the existing `screenshots.mjs` +
  the existing Playwright config. A future plan can
  switch both to `import.meta.dirname` if portability
  becomes a concern.
