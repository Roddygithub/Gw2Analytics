# advisor-plan 010 — Next.js error.tsx + not-found.tsx route-segment boundaries

## Problem

`web/src/app/` has NO `error.tsx` and NO `not-found.tsx` at any route segment. In Next.js 16 App Router, a thrown error in a Server Component propagates up the tree UNTIL it hits an `error.tsx` boundary or the global catch-all. With NOTHING installed, an unhandled exception renders Next.js's built-in "Application error" page — domain-unaware, not branded, doesn't link back to the dataset. The cross-account compare, per-fight drill-down, and per-fight timeline all do async Server Component fetches; a transient gateway 502 becomes a generic 500 page.

## Context

- `web/src/app/` — verified `grep -rE 'error\.tsx|not-found\.tsx|ErrorBoundary' web/src/app` → 0 matches.
- `web/src/components/TimelineChart.tsx` + `web/src/components/CrossAccountTimelineChart.tsx` are pure Client Components — won't throw on SSR.
- Server fetches in `web/src/app/fights/[id]/page.tsx:84-90` use `Promise.allSettled` to degrade gracefully WITHIN a single page, but NOTHING catches errors that escape (JSON parse failures, schema.d.ts drift → schema-mismatch fetch error).
- `web/tests/app/` has 8 vitest page tests; none assert error.tsx presence.

## Approach

Add 4 files:
1. `web/src/app/error.tsx` — top-level `Client Component` ("use client") that catches propagated throws from any Server Component below.
2. `web/src/app/not-found.tsx` — Server Component rendered when no matching route is matched.
3. `web/src/app/fights/[id]/error.tsx` — domain-aware error for the most-common gateway failure path (events blob missing/corrupt).
4. `web/src/app/players/[account_name]/error.tsx` — parallel structure for the player profile route.

Plus 2 vitest tests.

## Files

**In scope**:
- NEW `web/src/app/error.tsx`
- NEW `web/src/app/not-found.tsx`
- NEW `web/src/app/fights/[id]/error.tsx`
- NEW `web/src/app/players/[account_name]/error.tsx`
- NEW `web/tests/app/error-page.test.tsx`
- NEW `web/tests/app/not-found.test.tsx`

**Out of scope**:
- `web/src/app/layout.tsx` (INTENTIONALLY NOT an error boundary — layouts propagate errors to ROOT, handled by new top-level error.tsx).
- Future API route work (`route.ts`).

## Steps

1. Create `web/src/app/error.tsx`:
   - Top `"use client"` directive (Next.js requirement for error boundaries).
   - `useEffect` on a "Try again" button → `router.refresh()`.
   - Brand-styled with the existing `--surface`, `--accent`, `--foreground` tokens from `web/src/app/globals.css`.
   - Mirror the existing `<header>` style from `layout.tsx` for consistency.
2. Create `web/src/app/not-found.tsx`:
   - Server Component (no "use client").
   - Inherits layout from `app/layout.tsx` so the search bar in `<header>` stays visible.
   - Centered "404 · This page is not in the dataset" panel.
3. Create `web/src/app/fights/[id]/error.tsx`:
   - Wrap / supersede the existing `fetchError` rendering branch in `fights/[id]/page.tsx:108-115`.
   - Recover path: `router.replace('/fights')` after 2s (`useEffect` + `setTimeout`).
   - Display the existing formatApiError output verbatim.
4. Create `web/src/app/players/[account_name]/error.tsx` (parallel; "player profile unavailable").
5. Create vitest tests in `web/tests/app/`:
   - `error-page.test.tsx`: render `app/error.tsx` with a thrown error prop, assert the "Try again" button is present.
   - `not-found.test.tsx`: render `app/not-found.tsx`, assert the 404 heading is present.

## Verification

- `find web/src/app -name 'error.tsx' -o -name 'not-found.tsx'` → 4 files.
- `npx tsc --noEmit` (CI gate) → 0 errors.
- `pnpm test:unit` (CI gate) → all green including the 2 new tests.
- Visual smoke (operator-side):
  - Navigate to `http://localhost:3000/this-does-not-exist` → 404 page renders.
  - Force an error in a Server Component (`throw new Error('test')` temporarily) → error.tsx renders with "Try again".

## Test plan

- 2 vitest tests in `web/tests/app/` mirror the layout.test.tsx pattern (existing `tests/setup.ts` mocks).
- Server Component fetches in `fights/[id]/page.tsx` are NOT unit-tested for error.tsx (would require a Next.js server-runtime mock); the `not-found.tsx` + `error.tsx` ARE unit-tested because they take simple props.

## Done criteria

- 4 new files present in `web/src/app/` (2 top-level + 2 segment-level).
- 2 new vitest tests pass.
- TypeScript + lint + e2e + visual regression all green.

## Maintenance note

- The top-level `app/error.tsx` is a LAST RESORT — every route segment with rich content should ALSO have its own `error.tsx` so the error message is domain-aware. Plans 013+ should add `/players/compare/error.tsx`, `/account/error.tsx` etc. following the same parallel structure. Don't centralize the logic — segment errors should re-throw / log and let the top-level handle the user-facing UI.
- Don't introduce state (`useState`) inside `error.tsx` Client Components unless necessary — the boundary re-mounts on recovery and state is lost.

## Escape hatch

- If the operator wants more aggressive recovery UX (auto-redirect after 5s), tailor it in the existing `app/error.tsx`, NOT in every segment.
- If Next.js's `error.tsx` semantics change in a future release (e.g. Next.js 17), the files might need `app/global-error.tsx` instead. Defer the migration decision to the operator's next Next.js upgrade.
