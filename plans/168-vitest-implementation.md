# Plan 168 — v0.10.27-pre — vitest M-effort migration recipe (closes plan 165)

**Source:** Decomposition of `plans/165-v01025-fight-events-page-test-migration.md`
into a concrete 5-bullet execution recipe. The original plan 165
describes the intent; this plan 168 carries the actual LoC and
file-by-file breakpoints so a future executor doesn't rebuild the
plan from scratch.
**Severity:** MED (CI gate; closes 1 carryforward file on the
master audit vitest failure backlog as observed at HEAD `1813881`).
**Effort:** M (~110 LoC + 1 NEW helper file).
**Drift base:** `e250623`.

## Carryforward vs. surfaced-failure correction

The master audit (pre-`1813881`) cited 6 carryforward vitest failures
in `fight-events-page*` `.test.tsx`. At the post-pull head `e250623`
only `web/tests/app/fight-events-page.test.tsx` exists;
`fight-events-page-error.test.tsx` is `[FILE_DOES_NOT_EXIST]` (the
file was never created, OR was renamed in a cycle that wasn't
landed). The actual CURRENT-DEBT is smaller than the audit's 6
because it conflates pre-existing files + nominal ones cited from
stale plan/audit context.

For this plan, the executor MUST verify the actual fail-cluster
at HEAD before starting implementation:

```bash
pnpm vitest run web/tests/app/fight-events-page.test.tsx 2>&1 | tail -30
```

If the resulting failure count differs from the audit's "6", adjust
the bullet scope accordingly (the recipe below covers 1 file +
6 mockable section-bodies + 1 NEW helper; the LoC is bounded by
section, not by file-count).

## 5-bullet recipe

### Bullet 1 — Add the `renderWithSession` helper

**NEW file:** `web/tests/app/_helpers/renderWithSession.tsx` (~30 LoC).

Responsibilities:
- Pre-warm `fetchCached` cache + seed the initial fetch dispatch
  table (matching the existing `mockFightFetch` pattern in
  `web/tests/app/fight-events-page.test.tsx`).
- Inject the initial route via `mockRouter` (Next.js App Router
  shim — `useRouter`/`usePathname` return the seeded values per
  `web/tests/setup.ts`'s `vi.mock("next/navigation")` precedent).
- Reset `globalThis.fetch` between tests (in addition to vitest's
  per-file reset; the existing `fetchCached` mock state leaks
  across tests if not explicitly cleared).

Skeleton:

```tsx
import type { ReactElement } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { vi } from "vitest";

export interface SessionOptions extends Omit<RenderOptions, "wrapper"> {
  initialRoute?: string;
  initialFetchMocks?: () => void; // the per-URL dispatch setup
}

export function renderWithSession(
  ui: ReactElement,
  { initialRoute = "/", initialFetchMocks }: SessionOptions = {},
) {
  vi.mocked(vi.fn()).mockClear?.();
  initialFetchMocks?.();
  // The page.tsx Server Component reads the route from `usePathname`,
  // so seed the mock router here. setup.ts's existing `vi.mock("next/navigation")`
  // already mocks the module — we patch the implementation per-test.
  vi.doMock("next/navigation", async () => {
    const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
    return { ...actual, usePathname: () => initialRoute };
  });
  return render(ui);
}
```

### Bullet 2 — Migrate `web/tests/app/fight-events-page.test.tsx`

The existing test file uses a `async (importActual)` mock pattern
on `@/lib/fetchCached` + inline `mockFightFetch({ events: POPULATED_PAYLOAD })`
before each test. The migration:

- Drop the per-test `vi.mocked(fetchCached).mockImplementation(async ...)`
  block in the `mockFightFetch` helper. Replace with a one-liner
  that delegates to `initialFetchMocks`.
- Replace `render(tree)` calls with `renderWithSession(tree, { initialFetchMocks: () => mockFightFetch() })`
  for each test (~11 test bodies × ~5 LoC each = ~55 LoC delta).

### Bullet 3 — Spot-fix the verified carryforward failure classes

Inspect the ``pnpm vitest run web/tests/app/fight-events-page.test.tsx``
output AT EXECUTION TIME before scoping. The referenced audit (the
master debt backlog pre-`1813881`) cited 6 failure classes, but the
``fight-events-page-error.test.tsx`` file returns
``[FILE_DOES_NOT_EXIST]`` at the post-pull HEAD. The actual fail-cluster
is likely smaller (1-2 classes) and addresses:

- Server Component boundary mismatch (``fetchCached` state hydrates on
  client only; the helper seeds initial state per test).
- ``fetchCached`` lifecycle race (helper clears between tests).

Address each verified failure in order of cheapest-to-fix first
(mocks wiring → lifecycle race → hydration boundary → cascade contract).
Re-run ``pnpm vitest run`` after each cluster is fixed to confirm
the count drops; defer the closing commit until ``pnpm vitest run``
returns 0 failing tests on the ``fight-events-page*`` glob.

### Bullet 4 — Add a regression-guard test

**NEW file:** `web/tests/app/fight-events-page-hydration.test.tsx`
(~20 LoC). Single test that mounts `FightEventsPage` with the
helper seeded for the populated path, asserts the rendered HTML
matches the expected hydration-boundary contract, and serves as
a future regression net for the same failure class.

### Bullet 5 — Final clean-up + cycle-close commit

```bash
pnpm vitest run web/tests/app/fight-events-page.test.tsx  web/tests/app/fight-events-page-hydration.test.tsx 2>&1 | tail -20
uv run ruff check libs apps  # still green
pnpm tsc --noEmit --skipLibCheck  # still green
git commit -m 'test(web): migrate fight-events-page to renderWithSession helper (closes plan 165 carryforward)'
```

## Acceptance criterion

`pnpm vitest run web/tests/app/fight-events-page*` returns
**0 failing tests** + master audit's vitest failure row is removed
on the next audit pass.

## Execution budget

Total ~110 LoC across 2 NEW files + 1 MODIFIED file. Single
mimo-half cycle (XS budget). Operator handoff: see `plans/167`
under "Wave 3 — v0.10.27-pre".
