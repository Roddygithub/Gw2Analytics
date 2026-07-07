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

| Path        | Role                                                                       |
|-------------|----------------------------------------------------------------------------|
| `/`         | Landing + status badge + CTAs to `/fights` and `/account`.                 |
| `/fights`   | Server Component: SSR-fetch `GET /api/v1/fights`, render AG&nbsp;Grid.     |
| `/account`  | Client Component: form that resolves a `Bearer` key against `/api/v1/account`. |

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
