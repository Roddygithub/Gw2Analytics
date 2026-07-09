# Plan 043 — v0.9.13 vitest `afterEach(cleanup)` in `setup.ts`

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — test suite patterns deep pass
**Status:** pending
**Effort:** S
**Category:** test reliability (DOM leakage between tests)
**Files touched:** `web/tests/setup.ts` (1 file, additive change only) + `web/tests/components/*.test.tsx` (additions to existing test files to assert the cleanup is wired)

## Problem

`web/tests/setup.ts` is the canonical vitest setup file
(auto-loaded by `vitest.config.ts` per the project
convention). The file configures:
- `vi.mock(...)` for 10+ components (so the page-level
  tests don't drag AG Grid + react-router into jsdom).
- `vi.mock("next/link", ...)` and `vi.mock("next/font/google", ...)`
  for the same reason.
- `vi.mock("@/lib/env", ...)` to provide a deterministic
  `API_BASE_URL`.

The setup is missing the canonical `@testing-library/react`
cleanup hook:

```typescript
// The canonical vitest + @testing-library/react setup
// pattern, as documented at
// https://testing-library.com/docs/react-testing-library/api#cleanup.
import { cleanup } from "@testing-library/react";
afterEach(cleanup);
```

Without this hook, every component-level test that uses
`render` from `@testing-library/react` leaves its DOM
nodes mounted in `document.body`. The next test starts
with a polluted DOM (a previous test's rendered nodes
+ the new test's rendered nodes). For the 7 component-
level test files in `web/tests/components/`:

- `web/tests/components/window-size-selector.test.tsx`
- `web/tests/components/target-filter.test.tsx`
- `web/tests/components/player-search-bar.test.tsx`
- `web/tests/components/player-timeline-chart.test.tsx`
- `web/tests/components/player-timeline-section.test.tsx`
- `web/tests/components/per-fight-timeline-chart.test.tsx`
- `web/tests/components/ProfessionFilter.test.tsx`

…each `render(...)` call adds nodes to `document.body`.
After 5 tests, the body has 5x the expected nodes. A
test that asserts "the dropdown has exactly 3 options"
finds 15 options (3 from the current render + 12 from
the previous 4). The assertions are wrong.

### Severity

- **Test reliability**: MED — the DOM leakage
  silently corrupts the test assertions. A test that
  passes today may fail tomorrow when a previous test
  renders a different DOM tree (e.g. a new component
  is added to the test suite). The failure is non-
  deterministic (depends on test execution order).
- **DX**: MED — the failure message is cryptic
  ("expected 3 options, found 15") and the operator
  has to read the test ordering to figure out the
  cause.

### Affected callers

- All 7 component-level test files in
  `web/tests/components/`.
- Any future test that uses `render` from
  `@testing-library/react`.

## Goals

- Add `import { cleanup } from "@testing-library/react";
  afterEach(cleanup);` to `web/tests/setup.ts` so the
  global cleanup hook is wired for every test.
- Add a regression test that asserts the cleanup is
  wired (e.g. a test that renders 2 components in
  sequence and asserts the second test's DOM is
  pristine).

## Non-goals

- Migrating from `@testing-library/react` to a
  different testing library. The current library is
  the canonical React testing pattern; the
  `afterEach(cleanup)` hook is the canonical
  integration point.
- Adding a global `beforeEach` for DOM setup (e.g.
  resetting the URL, clearing localStorage). Out of
  scope (the current tests don't need it; a future
  test that does can add a focused `beforeEach`).
- Refactoring the per-component test files to share
  a common test wrapper. Out of scope (the
  cleanup hook is the minimal fix).

## Implementation

### File: `web/tests/setup.ts`

Add the cleanup hook at the top of the file (after the
existing imports, before the `vi.mock` calls so the
cleanup is wired before any test runs).

```typescript
import * as React from "react";
import { cleanup } from "@testing-library/react";
import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

// v0.9.13 plan 043: wire the canonical
// @testing-library/react cleanup hook so the DOM
// is reset between tests. Without this hook, every
// component-level test that uses ``render`` leaves
// its DOM nodes mounted in ``document.body``; the
// next test starts with a polluted DOM (the
// previous test's nodes + the new test's nodes),
// silently corrupting ``getByRole`` / ``querySelectorAll``
// assertions that count elements.
//
// The hook is global (runs after every test in the
// suite, including the page-level Server Component
// tests in ``web/tests/app/`` that do NOT use
// ``render``; for those, the cleanup is a no-op).
//
// See: https://testing-library.com/docs/react-testing-library/api#cleanup.
afterEach(() => {
  cleanup();
});

// ... (existing vi.mock calls unchanged) ...
```

### File: `web/tests/components/cleanup.test.tsx` (NEW)

A regression test that asserts the cleanup is wired.
The test renders 2 components in sequence; without the
cleanup, the second render's DOM is polluted by the
first.

```typescript
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

describe("vitest setup cleanup (plan 043)", () => {
  it("cleans up the DOM between tests", () => {
    // First render: a component with a unique data-testid.
    const First = () => <div data-testid="first">first</div>;
    render(<First />);
    expect(screen.getByTestId("first")).toBeTruthy();
    // After the test, the cleanup hook removes the
    // rendered DOM. The next test's render is pristine.
  });

  it("does not see the previous test's DOM", () => {
    // Second render: a different component. Without
    // the cleanup, the ``first`` div from the previous
    // test would still be in ``document.body`` and
    // ``screen.queryByTestId("first")`` would return
    // the previous test's node.
    const Second = () => <div data-testid="second">second</div>;
    render(<Second />);
    expect(screen.queryByTestId("first")).toBeNull();
    expect(screen.getByTestId("second")).toBeTruthy();
  });
});
```

## Test plan

1. **2 new tests** in the new
   `web/tests/components/cleanup.test.tsx` file
   assert (a) the first render's DOM is removed
   after the test, (b) the second render's DOM
   is pristine.
2. **All existing tests pass** — the cleanup hook
   is a no-op for tests that don't use `render`
   (the page-level Server Component tests).
3. **`pnpm exec vitest run`** exits 0.
4. **`pnpm exec tsc --noEmit`** is clean.

## Acceptance criteria

- [ ] `web/tests/setup.ts` has the
      `afterEach(cleanup)` hook wired.
- [ ] 2 new regression tests in
      `web/tests/components/cleanup.test.tsx` pass.
- [ ] All existing tests pass (the cleanup hook is
      a no-op for non-`render` tests).
- [ ] `tsc --noEmit` is clean.
- [ ] No production code paths change (the
      cleanup hook is test-only).

## Out-of-scope / deferred

- **Migrating from `@testing-library/react` to a
  different testing library**: out of scope (the
  current library is canonical; the
  `afterEach(cleanup)` hook is the canonical
  integration point).
- **Adding a global `beforeEach` for DOM setup**:
  out of scope (the current tests don't need it).
- **Refactoring the per-component test files to
  share a common test wrapper**: out of scope (the
  cleanup hook is the minimal fix).

## Maintenance notes

- **The `cleanup` function is a no-op for tests
  that don't use `render`**. The page-level Server
  Component tests in `web/tests/app/` use
  `renderToString` (or similar) but not `render`;
  the cleanup hook is a no-op for them. Adding the
  hook globally is safe.
- **The `cleanup` function is idempotent**: calling
  it multiple times in the same test is safe. The
  global `afterEach` hook calls it once per test;
  a future per-test `afterEach` would compose
  correctly.
- **The cleanup hook is the canonical
  `@testing-library/react` + vitest pattern**. The
  `@testing-library/react` v13+ auto-registers the
  cleanup hook when imported; the v12- era
  required the explicit `afterEach(cleanup)`. The
  project uses `@testing-library/react` v13+ (per
  the `web/package.json`); the explicit hook is
  defensive against a downgrade.
- **The regression test is order-dependent**:
  `it("does not see the previous test's DOM")` must
  run AFTER `it("cleans up the DOM between tests")`
  to assert the cleanup. Vitest runs tests in file
  order by default, so the regression test is
  reliable.
