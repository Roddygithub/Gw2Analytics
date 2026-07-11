# Plan 071 — v0.9.23: `pageerror` listener pattern extraction (3 e2e specs duplicate the same boilerplate)

## Drift base

`44ea862`. Refactor only — additive, no migration. The
test behaviour is unchanged byte-for-byte.

## Surface

NEW `web/tests/e2e/_helpers.ts` (the shared helper module),
`web/tests/e2e/landing.spec.ts` (refactored to consume the helper),
`web/tests/e2e/account.spec.ts` (refactored to consume the helper),
`web/tests/e2e/upload.spec.ts` (refactored to consume the helper).

## Finding

The same 4-line `pageerror` listener pattern is duplicated
verbatim in 3 e2e specs:

```ts
const pageErrors: string[] = [];
page.on("pageerror", (e) => pageErrors.push(e.message));
// ... test body (page.goto + assertions) ...
expect(pageErrors).toEqual([]);
```

The 3 specs:
- `landing.spec.ts` (the root path)
- `account.spec.ts` (the API key form)
- `upload.spec.ts` (the .zevtc upload form)

A future maintainer who:
- Adds a 4th spec with the same `pageerror` check — must
  copy-paste the 4 lines again.
- Modifies the error-collection pattern in one spec (e.g.,
  adds `console.error` filtering for known-benign warnings)
  — must mirror the change in the other 2 specs.
- Discovers a bug in the pattern (e.g., the listener must
  be added BEFORE `page.goto`, not after) — must fix 3
  sites instead of 1.

The pattern is the canonical "no uncaught exceptions during
page load" assertion. The docstring comments at each site
explain WHY (dev-mode React hydration warnings fire on
`console.error`; `pageerror` is the precise signal for
uncaught exceptions). The pattern is correct; it's just
duplicated.

## Fix

1. **NEW `web/tests/e2e/_helpers.ts`** with the shared
   helper:

   ```ts
   import type { Page } from "@playwright/test";
   import { expect } from "@playwright/test";

   /**
    * Capture uncaught exceptions during a test body, assert
    * the list is empty at the end.
    *
    * The pattern uses ``pageerror`` (not ``console.error``)
    * because the latter also fires on dev-mode React
    * hydration warnings, which are benign and would
    * false-positive the check.
    *
    * Usage:
    *
    *     test("...", async ({ page }) => {
    *       const assertNoErrors = captureNoUncaughtExceptions(page);
    *       const response = await page.goto("/");
    *       // ... assertions ...
    *       assertNoErrors();
    *     });
    *
    * The listener is added synchronously (BEFORE the test
    * body runs) so the very first ``page.goto`` is covered.
    * The returned closure is called at the END of the test
    * body (AFTER the assertions) so any uncaught exception
    * during the page load is captured.
    *
    * The ``_helpers.ts`` filename (leading underscore) marks
    * the file as a Playwright helper module that should NOT
    * be picked up by the ``include: ["tests/**/*.test.{ts,tsx}"]``
    * glob in vitest (the glob is scoped to the vitest setup,
    * not the Playwright config -- but the underscore is a
    * canonical "internal helper" marker that prevents
    * future test runners from picking it up by accident).
    */
   export function captureNoUncaughtExceptions(
     page: Page,
   ): () => void {
     const errors: string[] = [];
     page.on("pageerror", (e: Error) => errors.push(e.message));
     return () => {
       expect(errors, "no uncaught exceptions during page load").toEqual([]);
     };
   }
   ```

2. **Refactor `landing.spec.ts`** to use the helper:

   ```ts
   import { test, expect } from "@playwright/test";
   import { captureNoUncaughtExceptions } from "./_helpers";

   test.describe("/ (v0.4.0-web landing)", () => {
     test("renders the brand strip + 4 navigation cards", async ({ page }) => {
       const assertNoErrors = captureNoUncaughtExceptions(page);

       const response = await page.goto("/");
       expect(response?.status()).toBe(200);

       await expect(
         page.getByRole("heading", { name: "GW2Analytics", level: 1 }),
       ).toBeVisible();
       await expect(page.getByRole("link", { name: /Browse fights/ })).toBeVisible();
       // ... rest of the assertions ...

       assertNoErrors();
     });
   });
   ```

3. **Same refactor for `account.spec.ts`** (the
   `assertNoErrors()` call goes at the end of the test body,
   before the existing `expect(pageErrors).toEqual([])` line
   is removed).

4. **Same refactor for `upload.spec.ts`**.

## Why the closure return (not a side-effecting call)

The `captureNoUncaughtExceptions(page)` call sets up the
listener and returns a closure. The closure is called at
the END of the test body. This pattern:
- Forces the developer to think about WHEN to assert
  (assertion happens at the end, after all page loads).
- Allows the developer to call the assertion only ONCE
  (vs passing the assertion into the test body).
- Is the canonical Playwright pattern for "setup +
  teardown" assertions (similar to `beforeEach` +
  `afterEach`).

A side-effecting alternative (e.g.,
`assertNoUncaughtExceptions(page, () => { /* body */ })`)
would be a callback-based pattern that's less idiomatic
in Playwright + TypeScript.

## Why the leading underscore on `_helpers.ts`

Playwright's test glob is `tests/**/*.spec.ts` (per
`playwright.config.ts`); the leading underscore on
`_helpers.ts` is NOT required for the current Playwright
config. The underscore IS a canonical "internal helper"
marker that:
- Prevents future test runners (e.g., a `**/*.test.ts` glob
  in a future vitest or jest config) from picking it up.
- Signals to a human reader that the file is a helper
  module, not a spec.

The underscore is forward-compat; the current Playwright
config would ignore the file regardless.

## Risks

- The helper module is private to the e2e test directory
  (lives under `web/tests/e2e/`); it's not exported from
  the package.
- The helper's `expect` import is from `@playwright/test`
  (the Playwright-flavored `expect` that supports soft
  assertions + Playwright locators); a mis-import to
  `vitest`'s `expect` would break the test runner. The
  import path is explicit (`@playwright/test`), not a
  relative import.
- The closure-return pattern means the assertion is
  called at the end of the test body, not at a specific
  line. A test that throws an exception between the
  `captureNoUncaughtExceptions` call and the
  `assertNoErrors()` call would NOT trigger the assertion
  (the closure is never reached). This is the canonical
  behavior for "no uncaught exceptions" assertions: a
  test that throws an exception is ALREADY a test failure;
  the closure's "no additional uncaught exceptions"
  assertion is redundant in that case.

## Tests

1. `test_helper_captures_no_errors_on_clean_page` — call
   `captureNoUncaughtExceptions(page)` on a page that
   navigates to `/`; call the returned closure; assert
   the test passes.
2. `test_helper_captures_errors_on_broken_page` — call
   `captureNoUncaughtExceptions(page)` on a page that
   navigates to a route that throws an uncaught exception
   (e.g., a JS error in a Server Component); call the
   returned closure; assert the test fails with the
   expected error message.
3. `test_helper_listens_before_goto` — call
   `captureNoUncaughtExceptions(page)` then
   `page.goto("/")`; assert the listener is registered
   BEFORE the navigation (verified by a spy on `page.on`).
4. `test_landing_spec_uses_helper` — read
   `landing.spec.ts`; assert the file imports
   `captureNoUncaughtExceptions` and does NOT have the
   inline `pageErrors` array.
5. `test_account_spec_uses_helper` — same for
   `account.spec.ts`.
6. `test_upload_spec_uses_helper` — same for
   `upload.spec.ts`.
7. `test_helper_module_is_in_e2e_directory` — assert
   `_helpers.ts` is at `web/tests/e2e/_helpers.ts` (not
   in a subdirectory + not at the project root).

## Rejected alternatives

- **Put the helper in a global `web/tests/_setup.ts`**
  file (the vitest setup file): tempting (shared between
  vitest + Playwright). The helper is Playwright-specific
  (uses `Page` + `expect` from `@playwright/test`);
  mixing Playwright + vitest setup would force a
  conditional import.
- **Add a `beforeEach` + `afterEach` global setup** in
  `playwright.config.ts`: tempting (auto-applies to all
  tests). The pattern is "per-test assertion, not
  per-suite" — the `afterEach` would assert the same
  thing for all tests, but the `fights.spec.ts` and
  `players.spec.ts` have tests that intentionally
  exercise error paths (e.g., a 404 page that doesn't
  throw but does render an upstream-error card). The
  global setup would false-positive those tests.
- **Use a `playwright/test` fixture pattern** (declare a
  custom fixture in a `fixtures.ts` module): more
  idiomatic for Playwright. The fixture pattern requires
  the test to destructure the custom fixture in the test
  function signature (`async ({ page, noUncaughtExceptions }) => ...`).
  The closure-return pattern is simpler and matches the
  existing call sites with a 1-line change (vs the
  fixture pattern which requires changing every test
  signature).
- **Use `console.error` instead of `pageerror`** (the
  comment notes `pageerror` is more precise than
  `console.error` because the latter also fires on
  dev-mode React hydration warnings): tempting (simpler
  listener). The current `pageerror` is the correct
  signal; the docstring documents the choice. A future
  maintainer who reads the comment will not "fix" the
  choice to `console.error`.
