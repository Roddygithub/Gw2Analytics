# Plan 103 (v0.9.33) — `lib/env.ts` `NEXT_PUBLIC_API_BASE_URL` canonical + production fail-fast

## Files touched
- `web/src/lib/env.ts` (replace `process.env.API_BASE_URL` literal with `process.env.NEXT_PUBLIC_API_BASE_URL`; drop the silent `"http://localhost:8000"` fallback; add production fail-fast guard)
- `web/.env.example` (update the env-contract docstring to match the canonical var name — extends plan 057 v0.9.18 env-contract section)
- `web/src/app/page.tsx` + 6 next pages (verify they consume `displayedApiBaseUrl` from `lib/env.ts`; the alias is still required for the footer display)
- `web/tests/lib/env.test.ts` (NEW tests covering the canonical env var + the production fail-fast guard)

## Findings (audit)

- `web/src/lib/env.ts` line 15 declares `const API_BASE_URL = process.env.API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000"`.
- Two distinct issues:
  - **Naming convention**: `process.env.API_BASE_URL` is NOT a Next.js canonical env var. Next.js's bundler substitutes ANY env var starting with `NEXT_PUBLIC_*` into the client bundle. A plain `API_BASE_URL` (without the `NEXT_PUBLIC_` prefix) is server-only at build time. The current code works because `lib/api.ts` is consumed by Server-Component-only callers (Server Components run at request time on the server, where ALL env vars are available). The intent is clean: server-only fetches.
  - BUT the `displayedApiBaseUrl` is exported for UI components (the landing hero footer uses it for display). Those UI components may be Server or Client Components. If a future Client Component reads `displayedApiBaseUrl`, the value would be `undefined` at runtime because `API_BASE_URL` is not in the client bundle.
  - The Next.js canonical solution is `NEXT_PUBLIC_API_BASE_URL` — works in BOTH server (full env) AND client (bundler-substituted). This is the canonical convention; `plan 033 v0.9.7` referenced the change but the actual code wiring never landed.
  - **Silent localhost fallback**: the `?? "http://localhost:8000"` is a dev-friendly default. In a production deploy where the operator forgot to wire the env var, the build would silently bake in `"http://localhost:8000"` (because the env var is read at build time for the client bundle). The Next.js app would render + the fetches would all fail with cryptic 5xx upstream errors — the root cause being a missing env var is hard to debug post-deploy.
- The current production-protective check is missing entirely: there's no `NODE_ENV === "production" && !API_BASE_URL` guard.
- The `displayedApiBaseUrl` export is referenced in `web/src/app/page.tsx`'s landing hero footer (per the docstring at line 4). The footer reads the value at render time and renders it. If the footer is a Client Component (a `use client` boundary or it imports from a Client Component), the value would NOT reach the client because it's a plain `API_BASE_URL` (without `NEXT_PUBLIC_`).

## Fix

1. `web/src/lib/env.ts` — replace:

   ```typescript
   const API_BASE_URL =
     process.env.API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

   export { API_BASE_URL };

   export const displayedApiBaseUrl = API_BASE_URL;
   ```

   with:

   ```typescript
   /**
    * The single canonical env var name for the API base URL.
    *
    * The ``NEXT_PUBLIC_`` prefix is REQUIRED: Next.js's bundler
    * inlines env vars starting with ``NEXT_PUBLIC_*`` into the
    * client bundle, so the value reaches BOTH server-rendered
    * (Server Component) and client-rendered code paths.
    * Non-``NEXT_PUBLIC_`` env vars are stripped from the client
    * bundle (a plain ``API_BASE_URL`` would be ``undefined`` in
    * any code that runs after hydration).
    *
    * Set in ``.env.local`` (gitignored, dev) + ``.env.production``
    * (committed) + the production deploy's env vars. The
    * ``scripts/dump_openapi.py`` introspection check (per plan
    * 058 v0.9.18) verifies the env var is documented in
    * ``.env.example``.
    */
   const RAW_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

   if (
     process.env.NODE_ENV === "production" &&
     (RAW_API_BASE_URL === undefined || RAW_API_BASE_URL === "")
   ) {
     // Production: fail loud at module load. The Next.js
     // build/SSR startup surfaces the message immediately;
     // a silently-misconfigured production deploy would
     // otherwise bake in the localhost fallback.
     throw new Error(
       "NEXT_PUBLIC_API_BASE_URL is required in production. " +
         "Set it in .env.production or the deploy env (e.g. " +
         "Vercel project env vars).",
     );
   }

   /**
    * Trimmed API base URL (no trailing slash). The default
    * fallback is appropriate for local development; in
    * production the fail-fast guard above runs first.
    */
   export const API_BASE_URL: string =
     RAW_API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

   /**
    * User-facing display string for the gateway base URL.
    *
    * Same value as :data:`API_BASE_URL`; exported as a stable
    * named symbol so SSR components and the ``displayed`` footer
    * cannot drift from the trimmed URL the fetcher actually
    * uses.
    */
   export const displayedApiBaseUrl = API_BASE_URL;
   ```

2. `web/.env.example` — update the documented env var name (the file already mentions `API_BASE_URL` per `plan 057`; rename to `NEXT_PUBLIC_API_BASE_URL` and add the production-required note):

   ```bash
   # Gateway origin. Required in production; defaults to
   # http://localhost:8000 in dev. The Next.js bundler
   # inlines the NEXT_PUBLIC_* prefix into the client bundle so
   # the value reaches Server Components + Client Components alike.
   NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
   ```

3. NO change to `lib/api.ts` — the canonical import `{API_BASE_URL}` from `./env` is unchanged because the export name is preserved.

## Tests (5, NEW file `web/tests/lib/env.test.ts`)

- `test_api_base_url_resolves_next_public_prefix_in_dev` — set `process.env.NEXT_PUBLIC_API_BASE_URL = "https://test/"` + `process.env.NODE_ENV = "development"` BEFORE importing env; assert `API_BASE_URL === "https://test"` (trailing slash trimmed).
- `test_api_base_url_falls_back_to_localhost_in_dev_when_env_unset` — set `process.env.NEXT_PUBLIC_API_BASE_URL = undefined` + `NODE_ENV = "development"`, assert `API_BASE_URL === "http://localhost:8000"` (the dev-default fallback still works).
- `test_api_base_url_throws_in_production_when_env_unset` — set `process.env.NEXT_PUBLIC_API_BASE_URL = undefined` + `NODE_ENV = "production"`, assert that IMPORTING env throws an `Error` whose message contains `"NEXT_PUBLIC_API_BASE_URL is required in production"`.
- `test_api_base_url_throws_in_production_when_env_empty_string` — `NEXT_PUBLIC_API_BASE_URL = ""` + `NODE_ENV = "production"`, same throw (catches the "env var set to empty string" footgun).
- `test_displayed_api_base_url_mirrors_api_base_url` — after each test above, `displayedApiBaseUrl === API_BASE_URL` (the stable-named-symbol invariant holds across env mutations).

## Rejected alternatives

- **Keep `API_BASE_URL` (non-`NEXT_PUBLIC_`) and add a separate `displayedApiBaseUrl` reading `NEXT_PUBLIC_API_BASE_URL`** — splits the source of truth across 2 env vars; mis-configuration sets one without the other. The unified single-var approach is cleaner. REJECTED.
- **Drop the silent `"http://localhost:8000"` fallback entirely (require the env var in dev too)** — breaks local-dev DX (every contributor would need to create a `.env.local` just to run `pnpm dev`). The dev fallback + production fail-fast is the canonical Next.js pattern. REJECTED.
- **Add a runtime warning instead of throwing in production** — silent warnings vs loud throws; the production-misconfig foot-gun deserves the loud fail. Runtime warning would be silently logged in the operator's hosting platform, often ignored. REJECTED.
- **Read the env var from `window.__NEXT_DATA__` in a separate `useEnvBrowser()` hook** — couples the env resolution to a React lifecycle; the build-time env-substituted approach is simpler. REJECTED.
- **Use a `getEnv()` function called at request-time** — defeats the purpose of build-time env substitution for client-bundled values. REJECTED.

## Dependency graph

- Independent: touches `lib/env.ts` + `web/.env.example` only. The downstream `lib/api.ts` consumes `API_BASE_URL` (named import); the export name is preserved.
- Parallel-safe with plans 101 / 102.
- Pattern-aligns with `plan 033 v0.9.7` (which originally proposed the `NEXT_PUBLIC_*` rename). This plan DOES what plan 033 documented as "to do".
- Pattern-aligns with `plan 057 v0.9.18` (the env-contract documentation pass). This plan doesn't touch `web/.env.example` extensively — the 1-line change there is enough to keep the docs in sync.
