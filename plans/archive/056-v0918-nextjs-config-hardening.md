# Plan 056 — v0.9.18: `web/next.config.ts` hardening (placeholder → production config)

## Drift base

`44ea862`. Drift cleanup only — additive, no migration (Next.js
reads `next.config.ts` on every build; no schema migration needed).

## Surface

`web/next.config.ts` (currently a placeholder: `{ /* config options here */ }`),
`web/Dockerfile` (if present; for the `output: 'standalone'` integration).

## Finding

`web/next.config.ts` is a 3-line placeholder:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
```

The repo's Caddy reverse proxy (covered in plan 027) provides the
primary security headers (HSTS, CSP, X-Frame-Options, etc.), but
the Next.js config has 4 production-readiness gaps that the
Caddy layer does NOT cover:

1. **`poweredByHeader` defaults to `true`** — every HTTP
   response from the Next.js server includes
   `X-Powered-By: Next.js`, leaking the framework version to
   any client (a reconnaissance aid for an attacker). The
   `next.config.ts` must set `poweredByHeader: false`.
2. **`compress` is `true` by default** — but should be
   explicit (defence against a future Next.js default change
   + clarity for the reader).
3. **`output` is `undefined`** — Next.js 15+ defaults to
   bundling a full `node_modules/` for the standalone output
   but the production Docker build (if/when added) needs
   `output: 'standalone'` to copy only the required
   `node_modules` subset (saves ~200 MB in the image).
4. **`images.remotePatterns` is `[]`** — `next/image` (if
   used) cannot load external images. The current pages
   don't use `next/image` (all icons are inline SVG); this
   is a forward-compat knob.
5. **`headers()` async function absent** — Next.js-level
   security headers are a belt-and-braces second line of
   defence behind Caddy. The canonical Next.js 16 pattern
   is the `headers()` function in `next.config.ts` returning
   the 4 headers Caddy already sets (HSTS, X-Frame-Options,
   X-Content-Type-Options, Referrer-Policy); the duplication
   is intentional (defence-in-depth: a misconfigured Caddy
   in a self-hosted deployment still has the Next.js layer
   covering the basics).

## Fix

1. Replace the placeholder with the canonical Next.js 16
   production config:

   ```typescript
   import type { NextConfig } from "next";

   const SECURITY_HEADERS = [
     { key: "X-Frame-Options", value: "DENY" },
     { key: "X-Content-Type-Options", value: "nosniff" },
     { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
     { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
   ] as const;

   const nextConfig: NextConfig = {
     poweredByHeader: false,
     compress: true,
     output: "standalone",
     images: {
       remotePatterns: [
         // Empty list today; the canonical use case is the
         // arcdps wiki's image CDN (community.arcdps.com) for
         // skill icons. Future plans can add the entry.
       ],
     },
     async headers() {
       return [
         {
           source: "/:path*",
           headers: SECURITY_HEADERS,
         },
       ];
     },
     eslint: {
       // The CI runs `pnpm lint` (or `pnpm typecheck`); the
       // build must not skip lint silently.
       ignoreDuringBuilds: false,
     },
     typescript: {
       ignoreBuildErrors: false,
     },
   };

   export default nextConfig;
   ```

2. `web/Dockerfile` (if/when added) uses the `output: 'standalone'`
   pattern: `COPY --from=builder /app/web/.next/standalone /app`
   + `COPY --from=builder /app/web/.next/static /app/.next/static`
   + `COPY --from=builder /app/web/public /app/public`. The
   Dockerfile is out of scope for this plan (no Dockerfile
   today); the `output: 'standalone'` flag is forward-compat.

3. The `headers()` function returns the 4 canonical headers
   (HSTS + X-Frame-Options + X-Content-Type-Options +
   Referrer-Policy). CSP and Permissions-Policy stay in the
   Caddy layer (plan 027) because they need the per-request
   nonce for `script-src` which the Next.js `headers()`
   function does not have access to.

4. The `images.remotePatterns` is an empty list with a
   forward-compat comment (the canonical use case is the
   arcdps wiki image CDN).

## Why duplicate Caddy's headers (defence-in-depth)

Caddy is the primary reverse proxy; Next.js is a fallback. If
an operator deploys without Caddy (e.g., a local dev tunnel,
a custom Cloudflare worker in front of Next.js, an emergency
`pnpm dev` behind a permissive LB), the Next.js-level headers
still cover the 4 canonical ones. The duplication is
intentional; Caddy's headers take precedence in the response
chain (Caddy sets the headers on the way out, before the
response body).

## Risks

- The HSTS header (`max-age=63072000; preload`) is
  2-year-with-preload. Per the HSTS preload list requirements,
  the `preload` directive is permanent. The plan's HSTS value
  matches the v0.9.8 plan 027 Caddy config; the two must
  stay in sync. A future plan can centralize the HSTS value
  in a shared `headers-constants.ts` if drift becomes a
  problem.
- The 4 headers may conflict with a future per-page header
  override (e.g., a `<meta>` tag in `app/layout.tsx` setting
  `X-Frame-Options: SAMEORIGIN` for an iframe-embed feature).
  The current pages don't have per-page overrides; the
  pattern is well-defined.
- The `output: 'standalone'` change is a build-output
  change; CI's `pnpm build` step continues to produce the
  `.next/standalone/` directory, which is the canonical
  Next.js 16 build artifact. A consumer of the build
  artifact (if any) needs to be updated to read from
  `.next/standalone/` instead of `.next/`.

## Tests

1. `test_powered_by_header_is_false` — `import nextConfig from
   "@/next.config"; assert nextConfig.poweredByHeader === false`.
2. `test_compress_is_true` — `assert nextConfig.compress === true`.
3. `test_output_is_standalone` — `assert nextConfig.output === "standalone"`.
4. `test_security_headers_include_canonical_four` — call
   `await nextConfig.headers()`; assert the 4 headers are
   present in the response.
5. `test_eslint_does_not_ignore_during_build` — `assert
   nextConfig.eslint?.ignoreDuringBuilds === false`.
6. `test_typescript_does_not_ignore_build_errors` — `assert
   nextConfig.typescript?.ignoreBuildErrors === false`.
7. `test_security_headers_match_caddy_config` — read the
   `Caddyfile`, extract the 4 header values, assert the
   Next.js `headers()` returns the SAME values. Belt-and-braces
   sync test.

## Rejected alternatives

- **Set all 7+ security headers in Next.js (HSTS + CSP +
  X-Frame-Options + X-Content-Type-Options + Referrer-Policy +
  Permissions-Policy + COOP/COEP)**: tempting (defence-in-depth
  on every header). The CSP header requires per-request nonces
  for `script-src` which the Next.js `headers()` async
  function does not have access to. Caddy is the only layer
  that can inject the nonce. The 4 "stateless" headers (HSTS +
  X-Frame-Options + X-Content-Type-Options + Referrer-Policy)
  are safe to duplicate in Next.js.
- **Drop the Next.js `headers()` function (rely on Caddy
  alone)**: tempting (less duplication). A self-hosted
  deployment without Caddy (e.g., a Cloudflare worker in
  front of Next.js) loses the canonical 4 headers. The
  duplication is the canonical defence-in-depth pattern.
- **Use `experimental.serverActions.allowedOrigins` for
  Server Actions CSRF**: out of scope. The current pages
  don't use Server Actions (all data fetching is via the
  FastAPI gateway + AG Grid client-side calls). A future
  plan can add the config when Server Actions are
  introduced.
- **Use Next.js's `middleware.ts` to inject headers**:
  tempting (more flexible). But `middleware.ts` runs on
  every request (a performance cost); the `headers()`
  function in `next.config.ts` is the canonical
  performance-friendly path.
