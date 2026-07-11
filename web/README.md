# GW2Analytics Web (`web/`)

Next.js 16 frontend for the GW2Analytics monorepo — Server Components
fetch the FastAPI gateway, Client Components render AG&nbsp;Grid
Community and the API-key resolve form.

## Run

```bash
# 1. Install deps (pnpm workspace, lockfile committed)
pnpm install

# 2. Configure the gateway URL
cp .env.example .env.local   # then edit API_BASE_URL if non-default

# 3. Boot the gateway + dev server
uv run fastapi dev apps/api/src/gw2analytics_api/main.py    # port 8000
pnpm dev                                                       # port 3000
```

Open <http://localhost:3000>; the landing page links to `/fights`
and `/account`.

## Routes

| Path | Description |
|------|-------------|
| `/` | Landing page with navigation cards |
| `/account` | GW2 API key → world enrichment |
| `/upload` | `.zevtc` combat log upload with 3-step wizard |
| `/fights` | Paginated fight list grid |
| `/fights/[id]` | Fight drilldown: events, timeline, squads, skills |
| `/players` | Cross-fight player list with profession filter |
| `/players/[account_name]` | Player profile with per-fight breakdown + timeline |
| `/players/compare` | Cross-account timeline comparison (2-4 accounts) |

Plus 3 error/loading boundaries (`error.tsx`, `not-found.tsx`, `loading.tsx`) and 7 Playwright screenshot fixtures tracked at `docs/screenshots/`.

## Scripts

| Script                  | Purpose                                                                  |
|-------------------------|--------------------------------------------------------------------------|
| `pnpm dev`              | Start the Next.js dev server (auto-runs `pnpm generate:api` first).      |
| `pnpm build`            | Production build (`next build`).                                         |
| `pnpm start`            | Start the production build (`next start`).                               |
| `pnpm typecheck`        | `tsc --noEmit` against `tsconfig.json` (CI gate).                        |
| `pnpm test`             | Vitest in watch mode (interactive).                                      |
| `pnpm test:unit`        | Vitest single-run (CI gate).                                             |
| `pnpm test:e2e`         | Playwright e2e suite (headless).                                         |
| `pnpm test:e2e:headed`  | Playwright e2e suite (headed, for debugging).                            |
| `pnpm screenshots`      | Capture full-page PNGs of every route via Playwright -> `/screenshots/`. |
| `pnpm generate:api`     | Regenerate `src/lib/api/schema.d.ts` from the running gateway's OpenAPI. |

## OpenAPI regeneration

The web app's `src/lib/api.ts` derives its types from
`src/lib/api/schema.d.ts`, which is regenerated from the FastAPI
gateway's `app.openapi()` schema. Since v0.8.8, this regeneration
runs **automatically** as the first step of `pnpm dev` -- you no
longer need to remember to run it manually. To refresh without
restarting the dev server:

```bash
pnpm generate:api   # writes src/lib/api/schema.d.ts
```

**Prerequisite**: the codegen shells out to `uv run python
scripts/dump_openapi.py`, which imports the `gw2analytics_api`
package. Run `uv sync` at the repo root first if you haven't
already; without it the codegen step fails fast and
`pnpm dev` does not start the dev server.

## Visual regression

Since v0.8.9 (plan/003), a second Playwright project pixel-diffs
the 8 tracked PNGs at `docs/screenshots/` against fresh full-page
captures of the corresponding routes. A diff > 1% of the total
pixel count fails the build; on failure, the diff PNG (a red
highlight overlay on the changed pixels) is written to
`web/tests/e2e/.visual-regression-output/<baseline>` (gitignored)
and uploaded as a CI build artifact.

**When a UI refactor is intentional**, refresh the 8 tracked PNGs
and commit the updated files:

```bash
pnpm screenshots --persist   # captures + copies into docs/screenshots/
```

**When a CI failure surfaces**, inspect the diff PNG at
`web/tests/e2e/.visual-regression-output/<baseline>` to confirm
whether the change is intentional. The diff PNG is a red overlay
on the changed pixels; a small handful of red pixels (e.g. an
anti-aliasing edge) is typically tolerable noise, while a large
solid red region indicates a real UI regression.

**The visual-regression suite is gated on PRs only** (not on
every push to `main`) via
`if: github.event_name == 'pull_request'` in
`.github/workflows/ci.yml`. The default `pnpm exec playwright test`
invocation (the "Playwright E2E tests" step) skips the
visual-regression suite via the
`--project=visual-regression` filter on the `playwright.config.ts`
`projects` block, so the fast local loop stays under the ~30 s
budget. CI runs the visual-regression suite explicitly via the
"Visual regression e2e (PR only)" step.

The 1% diff threshold is a tunable (the `DIFF_THRESHOLD` const at
the top of `web/tests/e2e/visual-regression.spec.ts`); a future
cycle could lower it to 0.5% for stricter diffing (catches
font-rendering drift across Node versions).

## Architecture

- **Server Components** fetch directly from `process.env.API_BASE_URL`
  (see `src/lib/api.ts`). Avoids the client waterfall and ensures
  the initial response is fully populated.
- **Client Components** wrap interactive parts (AG&nbsp;Grid,
  form state) with `"use client"` at the top.
- **CORS** is wide-open on the gateway in local dev (`allow_origins=["*"]`,
  `allow_headers=["*"]`); tighten before public deploy.
- **Auth**: `/account` posts the GW2 API key as `Authorization: Bearer
  <key>` directly to the gateway. For production, route this through
  a Next.js API route or BFF so the key never touches the browser.
