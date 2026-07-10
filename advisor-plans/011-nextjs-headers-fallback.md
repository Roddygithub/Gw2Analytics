# advisor-plan 011 — Next.js headers() fallback via next.config.ts

## Problem

`web/next.config.ts` ships with ONLY `allowedDevOrigins`. NO security headers via Next.js's `headers()` function. For an operator who deploys with `next start` + a non-Caddy reverse proxy (Cloudfront, ngrok, behind a corporate VPN), there is NO application-layer defense for HSTS / X-Frame-Options / Referrer-Policy. Plan 008 (Caddyfile) addresses this on Caddy; plan 011 closes the gap for the other ~70% of deployment topologies.

## Context

- `web/next.config.ts:1-16` — verbatim current content (read during audit). 12 lines, only `allowedDevOrigins`.
- Next.js docs: `headers()` function in `next.config.ts` returns a static array of header rules; route matchers support `source: '/(.*)'` for global coverage.
- Plan 008 (Caddyfile) emits the SAME headers via `header { ... }`. Plan 011 emits via Next.js. They are redundant in a Caddy-fronted deploy BUT independent in any other topology. The redundancy is intentional — defense in depth.

## Approach

Add a `headers()` block in `web/next.config.ts` that emits the SAME 4 headers as plan 008: HSTS, X-Content-Type-Options, Referrer-Policy, CSP. Mirror the CSP `'unsafe-inline'` exception for SSR styles + `frame-ancestors 'none'`. Apply globally with `source: '/(.*)'`.

## Files

**In scope**: `web/next.config.ts` only (small change).
**Out of scope**: `Caddyfile` (plan 008), `apps/api/src/gw2analytics_api/main.py` CORS (already env-driven).

## Steps

1. Replace the file body with:
   ```ts
   import type { NextConfig } from "next";

   const SECURITY_HEADERS = [
     { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
     { key: "X-Content-Type-Options", value: "nosniff" },
     { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
     { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" },
   ];

   const nextConfig: NextConfig = {
     allowedDevOrigins: ["127.0.0.1", "localhost"],
     async headers() {
       return [{
         source: "/(.*)",
         headers: SECURITY_HEADERS,
       }];
     },
   };

   export default nextConfig;
   ```

## Verification

- `cat web/next.config.ts | head -30` → see the new `headers()` function.
- `npx tsc --noEmit` → 0 errors.
- `pnpm build && pnpm start &` then `curl -I http://localhost:3000 | grep -iE 'strict-transport|content-security|x-content-type|referrer-policy'` → 4 lines expected.

## Test plan

- New vitest test in `web/tests/next-config.test.ts` (new file):
  - Mock `next config` import; verify `headers()` returns the SECURITY_HEADERS array.
  - Assert each of the 4 keys is present.
- 1 e2e smoke (operator): navigate to any page → browser DevTools Network tab → verify all 4 headers present.

## Done criteria

- `web/next.config.ts` has the `headers()` function.
- The new vitest test passes.
- TypeScript + lint + visual regression all green (no UI change).

## Maintenance note

- If the operator is on Caddy + plan 008, headers are emitted TWICE. Acceptable (browsers dedupe on identifier; both set to IDENTICAL values). If the operator changes one header's value WITHOUT the other, the LATER-emitting layer wins — keep them synchronized.
- If Next.js adds a native `headers()` helper for HSTS preload-submission (post-16.x), prefer that. Don't migrate to a custom server until Next.js 17+ is the LTS.

## Escape hatch

- If the operator is on Cloudflare in front of Next.js, Cloudflare's per-page HSTS is set in the Cloudflare dashboard; DO NOT add the application-layer header (Cloudflare's wins). Skip plan 011 in that deployment topology.
- If a future Next.js upgrade breaks `headers()`'s return shape (Next.js 17+), port the function body to the new shape but preserve the 4 header keys + the global `source: '/(.*)'` route matcher.
