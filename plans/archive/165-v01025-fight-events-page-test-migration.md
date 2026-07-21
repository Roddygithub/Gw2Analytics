# Plan 165 — v0.10.25+ — Migrate `fight-events-page` vitest failures to modern fixtures

**Source:** Carryforward from `plans/AUDIT-2026-07-13-PROJECT-WIDE.md`
master-debt backlog (vitest failures, 6 pre-existing on
`web/tests/app/fight-events-page*.test.tsx`).
**Severity:** MED (CI gate; documented as carryforward in v0.10.18 release notes).
**Effort:** **M** (state-hydrate refactor + Server Component boundary fix).
**Drift base:** `1813881` (origin/main HEAD).

## Symptom

`pnpm vitest run web/tests/app/fight-events-page.test.tsx \
                 web/tests/app/fight-events-page-error.test.tsx`
produces 6 carryforward failures (per master audit). Pre-existing in
v0.10.18 release notes; Wave 7 (combat-readout UI) flagged them as
UNRELATED TO Wave 7 and carry-forward. They survive the E2E-JOURNEY
PR (which doesn't touch these surfaces).

## Two failure clusters

### Cluster A — Server Component boundary mismatch

Tests use `screen.getByRole(...)` assertions on data that only renders
client-side via the React PlayerSearchBar (the search bar hydrates
ON THE CLIENT only — the SSR pass renders the static shell). The
tests assert client-state DOM that the SSR pass never produced.

**Root cause:** the fixtures mock the player data shape but don't
mock the *hydration boundary*.

### Cluster B — `fetchCached` lifecycle race

The tests assert behaviour around the `fetchCached` TTL window
(per `web/src/lib/fetchCached.ts`); the current fixtures
`waitFor` race conditions where the cache flush happens AFTER
the assertion evaluates.

## Fix

### Stage 1 — Modernize fixtures (M)

Replace the per-test raw `vi.mock("next/navigation", ...)` blocks
with `web/tests/setup.ts`-style global mocks + a `renderWithSession`
helper that mounts the page inside a pre-warmed cache fixture.

```ts
// web/tests/app/_helpers/renderWithSession.ts  (NEW)
export function renderWithSession(
  ui: ReactElement,
  options: {
    initialRoute?: string;
    initialPlayers?: PlayerOut[];
    initialFights?: FightOut[];
  } = {},
) {
  // Pre-warm the fetchCached cache + inject initial route + set
  // the global navigation mock state.
  return render(ui, options);
}
```

### Stage 2 — Adapter `fight-events-page` test calls

For each of the 6 failing tests in
`web/tests/app/fight-events-page*.test.tsx`, replace the inline
`vi.mock + render + await waitFor` pattern with the new helper.
Expected result: 6 tests pass.

### Stage 3 — Add a regression-guard test

A new `web/tests/app/fight-events-page-hydration.test.tsx` mounts
the page explicitly testing the hydration-boundary contract so the
failure class doesn't recur.

## Effort rationale (M)

- Stage 1: S (1 helper file + setup wiring)
- Stage 2: M (6 test files × ~10 LoC each = ~60 LoC +
  per-test fixture review)
- Stage 3: S (1 regression guard)

## Suggested priority

Land AFTER plan 161 (section isolation — adjacent to the
fight-detail work which is also test-debt for the same area)
and BEFORE plan 164's vitest checks need a clean e2e fixture surface.

## Acceptance criterion

`pnpm vitest run web/tests/app/fight-events-page*` returns
0 failing tests + the master audit's "vitest failures" row is
removed on next pass.
