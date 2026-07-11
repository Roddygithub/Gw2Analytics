# Plan 057 — v0.9.18: `web/.env.example` ↔ `web/src/lib/env.ts` contract drift

## Drift base

`44ea862`. Drift cleanup only — additive, no migration.

## Surface

`web/.env.example`,
`web/src/lib/env.ts` (per plan 033's `_resolveApiBaseUrl` production
fail-fast contract),
`web/src/app/layout.tsx` (for the belt-and-braces fail-fast assertion
per plan 033).

## Finding

`web/.env.example` documents exactly one variable:

```
# Required: the gw2analytics_api FastAPI gateway base URL.
API_BASE_URL=http://localhost:8000
```

Plan 033 (v0.9.9) added the production fail-fast contract
(`NODE_ENV === "production" && !API_BASE_URL` raises) and the
optional `NEXT_PUBLIC_API_BASE_URL` client-side alias. Both are
absent from `.env.example`:

1. **Production fail-fast contract undocumented** — an
   operator deploying to production who reads `.env.example`
   and copies it verbatim sees no warning that a missing
   `API_BASE_URL` in production crashes the app at boot.
2. **`NEXT_PUBLIC_API_BASE_URL` alias undocumented** — the
   canonical Next.js pattern for client-side use is the
   `NEXT_PUBLIC_*` prefix. Plan 033 added the alias but
   `.env.example` doesn't mention it.
3. **`NODE_ENV` semantics undocumented** — Next.js sets
   `NODE_ENV=production` at build time + `NODE_ENV=development`
   in `pnpm dev`; the operator needs to know the
   `NODE_ENV` value the app will see at boot.
4. **The `?tz=` query param is consumed by `env.ts` but
   unrelated to `API_BASE_URL`** — not a finding (the
   `?tz=` is a per-request param, not an env var).

## Fix

Rewrite `web/.env.example` to document the full contract:

```
[TEMPLATE]
# GW2Analytics web frontend env contract.
# Copy to web/.env.local and edit. web/.env.local is gitignored.

# ---------------------------------------------------------------------------
# API_BASE_URL: the gw2analytics_api FastAPI gateway base URL.
# ---------------------------------------------------------------------------
# The frontend reads this at module-load time via @/lib/env.
#
# Local dev (docker compose up -d):
API_BASE_URL=http://localhost:8000
#
# Production: REQUIRED. If unset when NODE_ENV=production, the app
# fails fast at boot (the _resolveApiBaseUrl helper in @/lib/env
# raises a clear remediation message). The previous behaviour
# (silent localhost fallback) was a documented v0.9.9 audit
# finding (plan 033).
#
# Production example:
# API_BASE_URL=https://api.gw2analytics.example.com
#
# Optional alias: NEXT_PUBLIC_API_BASE_URL is read by Client
# Components (the App Router's "use client" boundary). Set
# to the same value as API_BASE_URL. If unset, the Client
# Component falls back to the build-time-inlined NEXT_PUBLIC_*
# value (Next.js inlines NEXT_PUBLIC_* at build time, so the
# alias must be set at BUILD time, not at runtime). Most
# deployments can omit it and rely on API_BASE_URL server-side.
# NEXT_PUBLIC_API_BASE_URL=https://api.gw2analytics.example.com

# ---------------------------------------------------------------------------
# NODE_ENV: set by Next.js automatically; do not override.
# ---------------------------------------------------------------------------
# - pnpm dev: NODE_ENV=development
# - pnpm build: NODE_ENV=production (inlined into the bundle)
# - pnpm start: NODE_ENV=production (read from the build artifact)
#
# The _resolveApiBaseUrl fail-fast checks this value; do not
# override it in .env.local.

# ---------------------------------------------------------------------------
# The ?tz= query param (per plan 001) is a per-request override
# for the player-timeline day-bucketing timezone. Not an env var;
# see web/src/lib/env.ts for the supported IANA TZ strings.
# ---------------------------------------------------------------------------
```

## Why not also add a `.env.test` for vitest

Out of scope. The vitest tests run with the env vars set per-test
(plan 031's `AbortSignal.timeout` test sets up its own mock server;
plan 033's `env.ts` tests pass `NODE_ENV=test` via
`@testing-library/react`'s test setup). A `.env.test` would conflict
with the test-suite's per-test env-var isolation.

## Risks

- The `web/.env.local` (the per-developer override file) is
  gitignored; the `.env.example` change does not affect
  existing developers' local setups. The change is purely
  documentation.
- An operator who copied the OLD `.env.example` before the
  plan ships will have the same `.env.local` (no `NODE_ENV`
  override needed; Next.js sets it automatically). The
  production fail-fast contract is the same regardless of
  what `.env.example` says — the documentation change just
  makes the contract discoverable.
- The `[TEMPLATE]` header line is a visual marker (the
  README's onboarding section says "copy `.env.example` to
  `.env.local`"). Adding a `[TEMPLATE]` line at the top is
  the canonical Next.js / Vercel pattern for distinguishing
  the template from the real env file.

## Tests

1. `test_env_example_documents_api_base_url` — read
   `web/.env.example`; assert `API_BASE_URL` is documented
   (either as a comment or as a value).
2. `test_env_example_documents_node_env_semantics` — read
   `web/.env.example`; assert the NODE_ENV section is
   present.
3. `test_env_example_documents_next_public_alias` — read
   `web/.env.example`; assert `NEXT_PUBLIC_API_BASE_URL`
   is mentioned.
4. `test_env_example_documents_production_fail_fast` —
   read `web/.env.example`; assert the "production REQUIRED"
   wording is present.
5. `test_env_example_has_template_header` — read
   `web/.env.example`; assert the first line is `[TEMPLATE]`
   (or equivalent marker).

## Rejected alternatives

- **Add a runtime check that `.env.local` was generated from
  `.env.example`**: out of scope. The `.env.local` is the
  canonical "local override" file; its content is
  per-developer, not a contract.
- **Add a `web/.env.production` (committed) with the
  production defaults**: tempting (defines the production
  contract in the repo). But the production values are
  operator-specific (the production domain + the
  cert paths); a committed file would either be a
  template (same as `.env.example`) or a leak (committed
  real values). The current `.env.example` is the canonical
  template.
- **Move the contract to a `web/docs/env.md`**: out of scope.
  The README's `## Quick start` section + `.env.example`
  itself is the canonical discovery path for the env
  contract. A separate doc adds a discovery step.
- **Generate `.env.example` from a Zod schema at build time**:
  over-engineered. The `.env.example` is a 30-line file
  maintained by hand; a Zod schema would add a build-time
  dep for a 1-time-per-release update.
