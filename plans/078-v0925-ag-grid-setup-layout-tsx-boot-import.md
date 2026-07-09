# Plan 078 — v0.9.25 — `ag-grid-setup.ts` registered at boot via `app/layout.tsx` import (belt-and-braces)

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Addressed finding (MED reliability + DX):** `web/src/components/ag-grid-setup.ts` is a side-effect-only module that registers `AllCommunityModule` from `ag-grid-community`. The current pattern requires each grid consumer (`FightsGrid.tsx` + `PlayersGrid.tsx` + `SquadRollupsGrid.tsx` + `TargetRollupsGrid.tsx` + `EventWindowsTable.tsx` + `SkillUsageTable.tsx`) to explicitly `import "./ag-grid-setup"` at the top of the file. Three architectural risks:

1. **Future-maintainer error**: a 7th grid component added in a future cycle that forgets the `import "./ag-grid-setup"` line silently fails — the grid renders with no built-in features (sort + filter + pagination) and the user sees an unstyled table.
2. **Module-graph ordering hazard**: TypeScript's single-evaluation guarantee is correct today, but a future `next/dynamic` lazy-import of one grid component (e.g., for code-splitting) could break the ordering (the lazy-imported grid evaluates BEFORE the eagerly-imported grid on first render, but the side-effect must fire before ANY grid renders).
3. **Tree-shake risk**: AG Grid's `ModuleRegistry.registerModules` is idempotent (the registry deduplicates by module identity), so multiple `import "./ag-grid-setup"` calls in the production bundle are safe but wasteful in terms of bundle-size analyzer noise.

The fix is to **add `import "@/components/ag-grid-setup"` to `app/layout.tsx`** (the Next.js 16 App Router root layout). The layout runs at server boot for every page (including the 6 pages that don't use AG Grid; the import is a one-line no-op). This guarantees registration before any grid component renders, AND removes the future-maintainer-can-forget risk. The existing 6 consumer-side imports stay as idempotent belt-and-braces (no churn for the existing grids).

Validated via `thinker-with-files-gemini` (2026-07-09): Option A (import in `layout.tsx`) was the recommended canonical pattern over Options B (explicit `registerGrids()` per consumer) and C (status quo). Key subtleties confirmed:
- Next.js 16 App Router's `layout.tsx` runs once per request and the side-effect fires on first import (per the TypeScript module graph).
- `ModuleRegistry.registerModules([AllCommunityModule])` is documented to be idempotent (calls after the first are no-ops because the module is already registered), so the consumer-side imports + the layout-side import coexist without runtime duplication or warning.
- The belt-and-braces design is forward-compat: a future maintainer can REMOVE the consumer-side imports in a follow-up plan once the v0.9.x cycle has fully proved the layout.tsx-import is sufficient.

## File changes

### 1 file edited (1-line addition) + 0 NEW files

**`web/src/app/layout.tsx`** — current 56-line file with this import block:

```typescript
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { PlayerSearchBar } from "@/components/PlayerSearchBar";
import "./globals.css";
```

becomes:

```typescript
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { PlayerSearchBar } from "@/components/PlayerSearchBar";
import "./globals.css";

// v0.9.25 plan 078: belt-and-braces boot-time registration of
// AG Grid's AllCommunityModule. The side-effect module
// (`@/components/ag-grid-setup.ts`) is the canonical
// registration site; importing it from the root layout guarantees
// the call happens before any grid component renders, so a future
// grid-component author cannot forget the import. The 6 existing
// consumer-side imports remain (idempotent — `registerModules`
// deduplicates by module identity).
import "@/components/ag-grid-setup";
```

Note: the import is placed AFTER `import "./globals.css"` and BEFORE the per-component imports. The exact ordinal doesn't matter for runtime correctness (module-graph evaluation is deterministic), but the placement matches the existing import-grouping convention (CSS imports + global side-effect imports → component imports).

The `metadata` export, the `RootLayout` function, the `<header>` block — none of these change.

### Test changes

**No NEW test files.** The `web/tests/app/layout.test.tsx` test (already in the suite, asserting the layout renders without errors) is sufficient as a smoke test — when `ag-grid-setup.ts` evaluates (either from the new layout import OR the existing consumer imports), the `registerModules` call runs. The test does NOT need to assert the registration directly (testing AG Grid's internals is out of scope; the canonical test is "does the grid render").

**Existing coverage**:

`web/tests/app/layout.test.tsx` (per the v0.9.7 audit + the v0.9.9 library tests) already imports the layout via `RootLayout` rendering. The new `import "@/components/ag-grid-setup"` line fires automatically during the test's component import chain. A NEW test case is added inline to the file:

| # | Test | Asserts |
|---|---|---|
| (existing) | Layout renders children | unchanged |
| (existing) | Layout uses Geist + Geist Mono fonts | unchanged |
| (NEW) | Layout import chain includes ag-grid-setup | AST inspection: parse `layout.tsx` as a TS module, find an `ImportDeclaration` whose source contains `@/components/ag-grid-setup` |

The NEW test is hermetic + AST-only (no AG Grid runtime needed). It catches the regression "future maintainer deletes the `ag-grid-setup` import from layout.tsx thinking it's redundant" (which would silently move the dependency back to the per-consumer-import-only state — a future grid-component author could then forget).

## Considered and rejected

- **Option B: explicit `registerGrids()` per consumer** — 6 call sites to update + a 7th grid added in the future needs to remember the call = the same drift risk, just renamed. Adds boilerplate.
- **Option C: keep status quo** — the future-maintainer-can-forget risk is unaddressed. The plan ships.
- **Alternative: DELETE the 6 consumer-side imports and only have the layout.tsx import** — cleaner (1 import instead of 7), but bigger diff (6 files changed instead of 1). The belt-and-braces design is forward-compat: the future cleanup can happen as a follow-up plan once v0.9.x proves the layout.tsx-import is sufficient in production.
- **Alternative: convert `ag-grid-setup.ts` to export an explicit `registerGrids()` function** that side-effect-imports it (Next.js pattern) — same as Option B; rejected.
- **Alternative: import in `app/page.tsx` (the landing page) instead of `layout.tsx`** — `page.tsx` only runs on `/`. The landing page doesn't render grids; a user navigating from `/` to `/fights/[id]` would still hit the registration for the first time inside the `/fights/[id]` route's grid import chain — the same risk being mitigated.
- **Alternative: use Next.js 16's `instrumentation.ts`** (the server-startup hook) — `instrumentation.ts` runs only on the server, but `ModuleRegistry.registerModules` must run on the CLIENT (where AG Grid hydrates the grid component). The server-side registration has no effect on the client.

## Effort

`S` — 1-line addition to `layout.tsx` + 1 NEW test case in `layout.test.tsx`. All additive. The 6 existing consumer-side `import "./ag-grid-setup"` statements are untouched. Independent of plans 077 + 079.
