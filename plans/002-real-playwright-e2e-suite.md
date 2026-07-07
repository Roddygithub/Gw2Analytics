# Plan 002 — Build a real Playwright e2e suite on top of `screenshots.mjs`

## Context

The repo's `pnpm test:e2e` script invokes `playwright test` (Playwright config exists at `web/playwright.config.ts` per the `.gitignore` Playwright block comment), but the only Playwright code in the repo today is `web/scripts/screenshots.mjs` — a visual capture script, not a test suite.

**Gap:** there are zero real e2e tests. CI runs `pnpm test:unit` (Vitest, 70 cases) + `pnpm typecheck` (tsc) + `uv run pytest` (190 cases) but nothing asserts "the GW2Analytics web app actually renders these routes and gets a 200 from the API behind them."

This plan converts the existing screenshots.mjs into a true test suite with assertions, moving from "capture + upload" to "capture + assert + diff".

## Goal

A new `web/tests/e2e/` directory containing Playwright spec files that exercise each top-level route:
- assert HTTP 200 from the API for each route's upstream call,
- assert key DOM elements are present (e.g., AG Grid root, form input, timeline SVG),
- assert no console errors during page load.

The existing `web/scripts/screenshots.mjs` becomes a thin capture-only script — the assertions move into the Playwright spec files.

## Files in scope

- **Create:** `web/tests/e2e/landing.spec.ts`
- **Create:** `web/tests/e2e/account.spec.ts`
- **Create:** `web/tests/e2e/upload.spec.ts`
- **Create:** `web/tests/e2e/fights.spec.ts`
- **Create:** `web/tests/e2e/players.spec.ts`
- **Create:** `web/tests/e2e/player-profile.spec.ts`
- **Update:** `web/scripts/screenshots.mjs` — strip out the per-page assertion logic (none currently); keep the capture loop; add a smoke check at the top that verifies the Playwright API is reachable (`process.exit(1)` if not).
- **Update:** `web/playwright.config.ts` (read first; possibly already configures `tests/e2e/`; otherwise add the testDir).
- **Update:** `.github/workflows/ci.yml` — add a `pnpm test:e2e` step AFTER the existing `pnpm test:unit` step (gated on a `test-e2e` job that boots the API + Next.js dev server in the same job).

## Files explicitly out of scope

- Vitest config / specs (different runner; not touched)
- `libs/gw2_*/tests` Python tests (different ecosystem)
- `apps/api/tests/test_uploads_e2e.py` (different scope — backend e2e)

## Steps

1. **Read the current `web/playwright.config.ts` to understand the existing config shape** (devices, baseURL, reporters, testDir). If `testDir` is not `tests/e2e/`, set it; otherwise reuse.
2. **For each of the 6 spec files, mirror the structure of the existing `web/scripts/screenshots.mjs`'s `PAGES` array but split into per-route files:**
   ```ts
   import { test, expect } from "@playwright/test";

   test("landing renders + no console errors", async ({ page }) => {
     const errors: string[] = [];
     page.on("pageerror", (e) => errors.push(e.message));
     const resp = await page.goto("/");
     expect(resp?.status()).toBe(200);
     await expect(page.getByRole("heading", { name: /GW2 Analytics/i })).toBeVisible();
     expect(errors).toEqual([]);
   });
   ```
3. **Add an `--upstream-api` assertion** to each spec that does an SSR fetch probe: assert that `process.env.API_BASE_URL + '/api/v1/' + <route's expected upstream call>` returns 200 (e.g., `fights.spec.ts` asserts `GET /api/v1/fights` returns 200). This catches "the page rendered but the API behind it is down."
4. **Strip assertions from `web/scripts/screenshots.mjs`** — leave the capture loop + `import.meta.dirname` resolution, drop any future assertion code that creeps in.
5. **Add the CI step** to `.github/workflows/ci.yml` after `pnpm test:unit`:
   ```yaml
   - name: Playwright e2e
     run: pnpm test:e2e
     env:
       API_BASE_URL: http://localhost:8000
     # Boot order: previous step `uv run fastapi dev ...` + `pnpm dev` in background
   ```
6. **Update `web/README.md` Scripts table** to add `pnpm test:e2e` as a real entry (already exists in package.json but the doc still references it as "headless" only).

## Test plan

- The plan IS the test plan. Each spec is a regression assertion. CI runs `pnpm test:e2e` on every push; a failure means a route regressed (UI or upstream API).

## Done criteria

- `pnpm test:e2e` exits 0 from repo root (boots stack locally + runs all 6 specs).
- All 6 specs have at least one assertion beyond just `page.goto`.
- CI step is green on the next push.
- `web/scripts/screenshots.mjs` is capture-only (no `expect`/`assert` imports).

## Maintenance note

- When a new route is added (e.g., `/fights/[id]/<new-tab>`), add a corresponding spec.
- Specs must be hermetic — never depend on the network for anything except the dev stack + the upstream API; no external services.
- If a spec incidentally captures a screenshot for visual debug, gate it behind `test.only(...)` or a `--debug` flag — never on every CI run.

## Escape hatch

If `web/playwright.config.ts` does NOT exist (despite the .gitignore comment claiming it does), STOP and confirm — the implication of .gitignore comments referring to non-existent files should itself be a docs fix.

If `tests/e2e/` already exists with content, STOP — do not duplicate. Inherit the existing structure.
