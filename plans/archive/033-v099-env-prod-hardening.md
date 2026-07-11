# Plan 033 — v0.9.9 env.ts prod hardening

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — web/src/lib/* deep pass
**Status:** pending
**Effort:** S
**Category:** prod hardening (env validation + URL validation)
**Files touched:** `web/src/lib/env.ts` (1 file, additive changes only) + `web/.env.example` (1 file, add `NEXT_PUBLIC_*` note) + `web/src/app/layout.tsx` (1 file, add a fail-fast `if (process.env.NODE_ENV === "production" && !process.env.API_BASE_URL)` check)

## Problem

`web/src/lib/env.ts` resolves the gateway base URL from
the `API_BASE_URL` env var with a silent fallback to
`http://localhost:8000`:

```typescript
const API_BASE_URL =
  process.env.API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";
```

This is correct for the dev loop (no env var needed; the
fallback matches the local `uv run gw2analytics-api`),
but it has 3 prod hardening gaps:

1. **Silent localhost fallback in production** — an
   operator who deploys to a public VPS WITHOUT setting
   `API_BASE_URL` gets the silent localhost fallback. Every
   Server Component fetch fails with `ECONNREFUSED` to
   `localhost:8000`; the user sees the canonical
   "Upstream error: 502" card on every page; the operator
   has no log signal that the env var is missing (the
   fallback is silent). The fix is to fail-fast at
   module-load time in production with a clear error
   message.

2. **No URL validation** — a typo or a value with a
   fragment (`#`) or a non-URL would fail at the first
   `fetch()` call with a confusing `TypeError: Invalid
   URL`. The fix is to validate the URL via `new URL()`
   at module-load time, with a clear error message
   identifying the bad value.

3. **No whitespace trim** — the `replace(/\/+$/, "")`
   removes trailing slashes but NOT leading/trailing
   whitespace. A `.env.local` with
   `API_BASE_URL = https://api.example.com ` (trailing
   space) or `API_BASE_URL = https://api.example.com`
   (trailing newline from a sloppy editor) would pass
   the current check. The fix is to `.trim()` first.

4. **No distinction between server-side and client-side
   env vars** — Next.js requires the `NEXT_PUBLIC_*`
   prefix for env vars to be available on the client.
   The current `API_BASE_URL` is server-side only (the
   fetchers in `lib/api.ts` are only called from Server
   Components). A future Client Component that imports
   `displayedApiBaseUrl` would get the build-time value
   (the inlined string from `process.env.API_BASE_URL`
   at `next build` time), not the runtime value. The fix
   is to document this constraint in the file's
   docstring + add a `NEXT_PUBLIC_API_BASE_URL` alias
   for client-side use.

## Goals

- Fail-fast at module-load time when `NODE_ENV ===
  "production"` AND `API_BASE_URL` is unset. The error
  message identifies the missing var + the remediation
  (set the env var or add a `.env.production` file).
- Validate the URL via `new URL()` at module-load time
  (only in production, to preserve the dev-loop
  experience).
- Trim whitespace before the trailing-slash strip.
- Add a `NEXT_PUBLIC_API_BASE_URL` alias for client-side
  use (returns the trimmed + validated URL or the dev
  fallback).
- Document the SSR-vs-client constraint in the file's
  docstring.

## Non-goals

- Adding per-environment env validation (e.g. different
  URLs for `staging` vs `production`). The current model
  is "one URL per build" (Next.js bakes the env var at
  build time). Out of scope.
- Adding a runtime env var check on every request
  (e.g. `process.env.API_BASE_URL` on each fetch). The
  module-load check is sufficient; the URL is constant
  per build.
- Validating that the URL points to a reachable host.
  The module-load check is sync; a runtime reachability
  check is a separate concern (out of scope for v0.9.9).
- Refactoring the env vars to use a typed config object
  (e.g. `import { env } from "@/lib/env"`). The
  current individual-constant pattern is canonical for
  Next.js Server Components; a typed config object is
  out of scope.

## Implementation

### File: `web/src/lib/env.ts`

Replace the file with a hardened version. The diff is
a body replacement + a docstring addition.

```typescript
/**
 * Env-driven gateway base URL constants.
 *
 * Split out of ``lib/api.ts`` so Server-Component-only
 * callers (e.g. the landing hero footer) can import the
 * displayed URL without dragging the fetcher's
 * ``ApiError`` class + row types into the homepage
 * bundle. ``lib/api.ts`` re-reads these constants so
 * there is a single source of truth at runtime.
 *
 * ## SSR vs client split
 *
 * Next.js requires the ``NEXT_PUBLIC_*`` prefix for env
 * vars to be available on the client. The current
 * ``API_BASE_URL`` is server-side only (the fetchers in
 * ``lib/api.ts`` are only called from Server
 * Components, never from Client Components).
 *
 * A future Client Component that needs the URL should
 * import ``displayedApiBaseUrl`` (which is the same
 * value as ``API_BASE_URL`` but exposed as a stable
 * named symbol) OR the ``NEXT_PUBLIC_API_BASE_URL``
 * env var (which Next.js inlines at build time so it's
 * available on the client). Do NOT import
 * ``API_BASE_URL`` directly into a Client Component --
 * the value would be the build-time value, not the
 * runtime value.
 *
 * ## Production validation
 *
 * In production (``NODE_ENV === "production"``), the
 * module-load check fails fast if ``API_BASE_URL`` is
 * unset or invalid. In dev, the localhost fallback is
 * preserved so the dev loop works without any env
 * var setup.
 */

// Raw, untrimmed value. May be undefined.
const RAW_API_BASE_URL = process.env.API_BASE_URL?.trim();

/**
 * Trimmed, trailing-slash-stripped, validated URL.
 *
 * - In dev (NODE_ENV !== "production"): the
 *   ``API_BASE_URL`` env var is used if set;
 *   otherwise the localhost fallback is used.
 * - In production: the ``API_BASE_URL`` env var is
 *   REQUIRED; the module throws at load time if it is
 *   unset. The URL is validated via ``new URL()`` to
 *   fail fast on typos.
 */
function _resolveApiBaseUrl(): string {
  const raw = RAW_API_BASE_URL;
  if (process.env.NODE_ENV === "production") {
    if (!raw) {
      throw new Error(
        "API_BASE_URL is required in production. Set it " +
          "in your deployment environment (e.g. " +
          "Caddy, Docker, Kubernetes) or in a " +
          "``.env.production`` file. The localhost " +
          "fallback is intentionally disabled in " +
          "production.",
      );
    }
    try {
      // The URL constructor validates the URL. A
      // typo or a non-URL throws TypeError.
      const parsed = new URL(raw);
      // Strip trailing slashes from the pathname.
      return parsed.origin + parsed.pathname.replace(/\/+$/, "");
    } catch (err) {
      throw new Error(
        `API_BASE_URL is not a valid URL: ${raw!}. ` +
          `Error: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
  // Dev: localhost fallback if unset. Strip
  // trailing slashes from the trimmed value.
  return (raw ?? "http://localhost:8000").replace(/\/+$/, "");
}

const API_BASE_URL = _resolveApiBaseUrl();

export { API_BASE_URL };

/**
 * User-facing display string for the gateway base URL.
 *
 * Same value as ``API_BASE_URL``; exported as a stable
 * named symbol so SSR components cannot drift from the
 * trimmed + validated URL the fetcher actually uses.
 */
export const displayedApiBaseUrl = API_BASE_URL;
```

### File: `web/src/app/layout.tsx`

Add a fail-fast check at the top of the layout file (or
in a new `web/src/app/_env-check.ts` module imported by
the layout). The check is a runtime assertion that runs
once per server boot (not per request).

```typescript
// In web/src/app/layout.tsx (top of file, after the
// existing imports):

import { API_BASE_URL } from "@/lib/env";

// Fail-fast check: in production, ensure the env var
// is set. The check is in the layout (not in a Server
// Component) so it runs once at server boot, not per
// request. The check is a no-op in dev (lib/env.ts
// handles the dev fallback).
if (process.env.NODE_ENV === "production" && !API_BASE_URL) {
  throw new Error(
    "API_BASE_URL is required in production. Set it in " +
      "your deployment environment.",
  );
}
```

### File: `web/.env.example`

Add a `NEXT_PUBLIC_*` note documenting the
client-side use case:

```bash
# ---------------------------------------------------------------------------
# API_BASE_URL
# ---------------------------------------------------------------------------
# The full URL of the FastAPI gateway. Server Components only.
# In production (NODE_ENV=production), this is REQUIRED -- the app
# fails fast at boot if unset. In dev, the localhost fallback is used.
#
# Example: https://api.gw2analytics.example.com
#
# For client-side use (a future Client Component that needs the URL),
# set NEXT_PUBLIC_API_BASE_URL to the same value. Next.js inlines the
# value at build time for client-side access.
# ---------------------------------------------------------------------------
API_BASE_URL=http://localhost:8000
# NEXT_PUBLIC_API_BASE_URL=https://api.gw2analytics.example.com
```

## Test plan

1. **Production-mode fail-fast**: set
   `NODE_ENV=production` and unset `API_BASE_URL`;
   importing `web/src/lib/env.ts` throws the canonical
   "API_BASE_URL is required in production" error.
2. **Production-mode invalid URL**: set
   `NODE_ENV=production` and `API_BASE_URL=not-a-url`;
   importing throws the canonical "not a valid URL"
   error.
3. **Production-mode valid URL**: set
   `NODE_ENV=production` and
   `API_BASE_URL=https://api.example.com`;
   importing returns `https://api.example.com`.
4. **Production-mode trailing-slash strip**: set
   `NODE_ENV=production` and
   `API_BASE_URL=https://api.example.com/`;
   importing returns `https://api.example.com`.
5. **Dev-mode localhost fallback**: set
   `NODE_ENV=development` and unset `API_BASE_URL`;
   importing returns `http://localhost:8000`.
6. **Dev-mode env var honoured**: set
   `NODE_ENV=development` and
   `API_BASE_URL=https://api.example.com`;
   importing returns `https://api.example.com`.
7. **Whitespace trim**: set
   `NODE_ENV=development` and
   `API_BASE_URL="  https://api.example.com  "`;
   importing returns `https://api.example.com` (trimmed).

## Acceptance criteria

- [ ] `web/src/lib/env.ts` has the new
      `_resolveApiBaseUrl` function + the production
      fail-fast check.
- [ ] `web/src/app/layout.tsx` has the runtime
      fail-fast assertion.
- [ ] `web/.env.example` documents `API_BASE_URL` +
      the `NEXT_PUBLIC_API_BASE_URL` alias.
- [ ] All 7 hermetic test cases pass.
- [ ] All existing tests pass.
- [ ] `tsc --noEmit` is clean.
- [ ] No production code paths change (the URL
      resolution is unchanged for any non-production
      env).

## Out-of-scope / deferred

- **Per-environment URL validation** (e.g. different
  URLs for `staging` vs `production`): out of scope
  (the current model is "one URL per build"; a
  multi-env URL would require a runtime config service).
- **Runtime reachability check**: out of scope (the
  module-load check is sync; a reachability check is
  a separate concern).
- **Typed config object** (e.g. `import { env } from
  "@/lib/env"`): out of scope (the individual-
  constant pattern is canonical for Next.js).

## Maintenance notes

- **The fail-fast check is in `lib/env.ts` AND in
  `app/layout.tsx`**. The `lib/env.ts` check is the
  authoritative one (it runs when any module imports
  the URL constant). The `layout.tsx` check is a
  belt-and-braces second check that runs at server
  boot, before any request is served. The duplication
  is intentional: if a future refactor moves the
  URL resolution out of `lib/env.ts`, the `layout.tsx`
  check still catches a missing env var.
- **The `new URL()` check rejects relative URLs**
  (e.g. `/api`). Operators who try to set
  `API_BASE_URL=/api` get a clear error. The plan
  intentionally requires an absolute URL.
- **The `NEXT_PUBLIC_API_BASE_URL` alias is
  intentionally optional** (commented out in the
  `.env.example`). A future plan that surfaces the URL
  in a Client Component would uncomment it.
