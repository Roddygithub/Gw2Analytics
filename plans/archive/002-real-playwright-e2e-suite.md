# Plan 002 — Close the remaining gaps in the Playwright e2e suite

## Context

The original v0.8.8 audit (stamped at `fe99cb7`) framed this plan as a greenfield build of a Playwright e2e suite, based on the false assumption that the only Playwright code in the repo was `web/scripts/screenshots.mjs` (a visual capture script, not a test suite).

**Recon at the start of execution revealed the suite is already largely in place**, shipped in three prior cycles:

- **v0.7.1 / v0.7.2 (commits `7d7f010`, `2616844`):** `web/tests/e2e/fights.spec.ts` + `web/tests/e2e/players.spec.ts` + `web/tests/e2e/mock-server.mjs` (a 212-line Node HTTP server serving 6 endpoint fixtures: `GET /fights`, `GET /players`, `GET /players/{name}`, `GET /players/{name}/timeline`, `GET /fights/{id}/events`, `GET /fights/{id}/squads`, `GET /fights/{id}/skills`).
- **v0.8.0 (commit `bd1af6e`):** `web/tests/e2e/players-timeline.spec.ts` (covers `/players/[account_name]/timeline`).
- **v0.7.1:** `web/playwright.config.ts` (full 3,376-byte config with two `webServer` blocks — mock-server on `:8080` + Next.js on `:3000`, with a CI/local switch that boots the real API in CI and the mock locally).
- **CI:** `.github/workflows/ci.yml` already runs `pnpm exec playwright install --with-deps chromium` + `pnpm exec playwright test` as a job step.

**Remaining gaps** (the only things this plan now does):

1. **3 routes have no spec yet:** `/` (landing), `/account`, `/upload`.
2. **2 mock endpoints are missing from `mock-server.mjs`:** `GET /api/v1/account` (the page's only upstream call) and `POST /api/v1/uploads` (the form's submit target).
3. **No spec asserts "no console errors"** — the existing 3 specs only check HTTP status + DOM presence. Worth adding to the new specs as a free win.

## Goal

Close the remaining coverage gaps so every top-level web route has a Playwright spec that asserts HTTP 200 from the API behind it, key DOM elements are present, and no console errors fire during page load. After this plan lands, every route the app exposes is regression-tested on every CI push.

## Files in scope

- **Create:** `web/tests/e2e/landing.spec.ts` — covers `/` (the index page; route-keyed screenshot is `docs/screenshots/01-landing.png`).
- **Create:** `web/tests/e2e/account.spec.ts` — covers `/account` (the account-info page; screenshot `03-account.png`).
- **Create:** `web/tests/e2e/upload.spec.ts` — covers `/upload` (the evtc file form; screenshot `02-upload.png`).
- **Modify:** `web/tests/e2e/mock-server.mjs` — add 2 endpoint fixtures:
  - `GET /api/v1/account` → returns a minimal `AccountEnrichedOut` fixture (see `apps/api/src/gw2analytics_api/schemas.py` for the schema shape; a stub with the required fields is enough — no need to match a real account).
  - `POST /api/v1/uploads` → returns a minimal `UploadOut` stub (HTTP 201; a 5-line handler that returns `{ id: "stub-upload-1", filename: "test.evtc", status: "pending" }` or whatever the schema requires).
- **Read but not modify:** `web/tests/e2e/fights.spec.ts`, `players.spec.ts`, `players-timeline.spec.ts`, `web/playwright.config.ts` — confirm patterns to mirror; do not refactor in this plan (they work).

## Files explicitly out of scope

- Vitest config / specs (`pnpm test:unit`) — different runner, already at 70+ cases.
- `libs/gw2_*/tests` Python tests — different ecosystem.
- `apps/api/tests/test_uploads_e2e.py` — backend e2e; separate concern.
- `web/scripts/screenshots.mjs` — capture-only, no assertions needed; do not add e2e concerns to it.
- Existing 3 e2e specs — they work; do not refactor in this plan.

## Steps

1. **Read `web/tests/e2e/fights.spec.ts` and `players.spec.ts` end-to-end** to internalize the existing assertion patterns (`expect(...).toBe(200)`, AG Grid root, no-network invariants). The new specs must mirror this style for consistency.
2. **Read `web/tests/e2e/mock-server.mjs` to find the right place to add the 2 new endpoint handlers** (it routes by method+path; new endpoints slot in next to the existing 6).
3. **Read `apps/api/src/gw2analytics_api/schemas.py` to find the exact `AccountEnrichedOut` + `UploadOut` schemas** — generate minimal stub fixtures that match the response_model so the mock server is shape-true (the e2e tests don't validate the full schema, but a TypeError at parse time in the client is a wasted debug cycle).
4. **Create `web/tests/e2e/landing.spec.ts`:**
   ```ts
   import { test, expect } from "@playwright/test";

   test("landing renders + upstream probe + no console errors", async ({ page }) => {
     const errors: string[] = [];
     page.on("pageerror", (e) => errors.push(e.message));
     const resp = await page.goto("/");
     expect(resp?.status()).toBe(200);
     await expect(page.getByRole("heading", { name: /GW2 Analytics/i })).toBeVisible();
     expect(errors).toEqual([]);
   });
   ```
5. **Create `web/tests/e2e/account.spec.ts`** — mirrors the landing spec; asserts `/account` renders + a heading is visible + the upstream `GET /api/v1/account` returns 200 (probed via a `page.request.get(...)` call before the page.goto, since the page's data fetch is server-side, not browser-side).
6. **Create `web/tests/e2e/upload.spec.ts`** — asserts `/upload` renders + the `<input type="file">` is present + the form's submit button is present; does NOT actually upload a file (would require a real `.evtc` fixture blob; deferred to a separate plan if needed). The new `POST /api/v1/uploads` mock endpoint is added so the upload form's submit button is non-stuck when a future test exercises it.
7. **Add the 2 mock endpoints to `web/tests/e2e/mock-server.mjs`** — slot them into the existing route table; keep the file's existing style.
8. **Validate locally:** `cd web && pnpm exec playwright test` must exit 0 with the 3 new specs added. (No new browser install needed; CI already does `pnpm exec playwright install --with-deps chromium`.)
9. **Push and confirm CI is green** on the next run.

## Test plan

The plan IS the test plan. Each new spec is a regression assertion. CI runs `pnpm exec playwright test` on every push; a failure means a route regressed (UI or upstream API).

## Done criteria

- `web/tests/e2e/` contains 6 spec files (3 existing + 3 new), all passing in CI.
- `web/tests/e2e/mock-server.mjs` serves 8 endpoint fixtures (6 existing + 2 new).
- Every top-level web route (`/`, `/account`, `/upload`, `/fights`, `/fights/[id]`, `/players`, `/players/[account_name]`, `/players/[account_name]/timeline`) has at least one Playwright spec.
- The new specs assert "no console errors" in addition to HTTP status + DOM presence (the existing 3 specs do not — left as a non-blocking followup if it ever matters).
- CI step `pnpm exec playwright test` is green on the next push.

## Maintenance note

- When a new route is added, add a corresponding spec in the same commit. The pattern is now established.
- Specs must be hermetic — never depend on the network for anything except the dev stack + the mock server; no external services.
- If a spec incidentally captures a screenshot for visual debug, gate it behind `test.only(...)` or a `--debug` flag — never on every CI run.

## Considered and deferred

- **Refactoring the 3 existing specs to add the "no console errors" assertion:** the existing 3 specs are working and battle-tested; adding the assertion in a followup commit is safer than a drive-by refactor in this plan. Trivial to do as a single one-line followup after this plan ships.
- **Capturing a real `.evtc` file fixture and asserting a successful upload round-trip:** requires a non-trivial fixture blob + a real-API CI run (the mock would return 201 but not exercise the actual upload parser). Better as a dedicated plan in a later cycle.
- **Visual regression testing (pixel diff against `docs/screenshots/*.png`):** `web/scripts/screenshots.mjs` already captures the 8 PNGs; a separate `playwright test` visual-regression job could diff them. Out of scope here — would need a baseline-locking strategy.
