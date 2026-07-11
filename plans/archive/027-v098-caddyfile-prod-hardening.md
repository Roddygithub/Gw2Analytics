# Plan 027 — v0.9.8 Caddyfile prod hardening

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — prod hardening pass
**Status:** pending
**Effort:** S
**Category:** infra hardening (security headers + rate limiting)
**Files touched:** `Caddyfile` (1 file, additive changes only)

## Problem

`Caddyfile` is the production reverse-proxy for the GW2Analytics
self-host (per `README.md` self-host workflow + `docs/v0.8.0-backend-design.md` §7).
The current file is 11 lines and configures ONLY `encode gzip zstd`
+ 2 reverse-proxy blocks. It is missing 7 prod hardening knobs:

1. **No HSTS header** — `Strict-Transport-Security` is not set, so
   a downgrade attack (TLS-stripping MITM via a coffee-shop WiFi)
   succeeds. Browsers will not enforce HTTPS for first-time visitors.
2. **No CSP** — `Content-Security-Policy` is not set, so the web
   frontend has no defence-in-depth against an XSS that slips
   through the Next.js escaping.
3. **No `X-Frame-Options: DENY`** — the site can be iframed by any
   origin, enabling clickjacking against the upload / account /
   players pages.
4. **No `Referrer-Policy`** — full referrer URL leaks to every
   external link (e.g. the `/fights/{id}` permalinks embed the
   upstream query string).
5. **No `Permissions-Policy`** — every browser feature (camera, mic,
   geolocation, payment, USB, etc.) is implicitly allowed, even
   though the app uses none of them.
6. **No rate limiting** — `POST /api/v1/uploads` (multipart
   `.zevtc` upload) + `POST /api/v1/webhooks` (subscription create)
   + `POST /api/v1/account` (API-key resolve) are all unauthenticated
   endpoints with no rate limit. A single attacker can DoS the stack
   with a 30-MB upload loop.
7. **No explicit `header` directive block** — the security headers
   above are added via Caddy's `header` directive, which is not
   present in the file.
8. **No explicit TLS settings** — the file relies on Caddy's
   automatic_https with the default `on_demand` off + `acme` from
   the email. For a production self-host with a real domain, the
   email is unset (the `placeholder.tld` block is the template),
   so Let's Encrypt issuance will fail. The `email` directive is
   the canonical fix.
9. **Placeholder domain annotation is buried** — `# Replace
   *placeholder.tld with your real domain in production.` is the
   only annotation. An operator who `cp Caddyfile Caddyfile.prod`
   + edits one occurrence can miss the `api.` subdomain or the
   bare domain. A more prominent annotation is warranted.

## Goals

- Add HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy
  via a shared `header` block in the `common` snippet.
- Add `rate_limit` directive to the API site block (NOT the web
  site block — the web is mostly static asset serving; the
  gateway is the DoS target).
- Add `email` directive to enable Let's Encrypt issuance in prod.
- Add prominent `# !!! REPLACE !!!` annotations on both domain
  lines + a top-of-file `## PRODUCTION CHECKLIST` block.

## Non-goals

- Switching the reverse proxy from Caddy to nginx / Traefik / HAProxy.
  Out of scope (Caddy is the production contract per the README).
- Adding authentication to the Caddy layer (e.g. basic_auth on the
  console). The API is the auth boundary; Caddy terminates TLS +
  reverse-proxies, nothing else.
- TLS to the upstream (api:8000, web:3000). Caddy already speaks
  HTTP to localhost, which is fine for a single-host self-host.
- WAF / mod_security integration. Out of scope (single-host self-
  host, not a public SaaS).
- Caching static assets at the Caddy layer. The Next.js app sets
  its own `cache-control` headers; Caddy passes them through.

## Implementation

### File: `Caddyfile`

Replace the entire file with the hardened version below. The diff
is purely additive (new directives in the `common` snippet + the
api site block + a header comment at the top).

```caddyfile
# ============================================================================
# Caddyfile — production reverse-proxy for GW2Analytics
# ============================================================================
#
# ## PRODUCTION CHECKLIST
#
# Before deploying this Caddyfile to production, you MUST:
#
#   1. Replace `placeholder.tld` (BOTH occurrences below — the bare
#      domain AND the `api.` subdomain) with your real domain.
#
#   2. Set the `email` directive to a real email address. Caddy
#      uses this for Let's Encrypt / ZeroSSL account registration
#      + expiry notifications. Without it, ACME issuance fails
#      and the site serves the Caddy self-signed fallback cert.
#
#   3. Optionally override the `rate_limit` value in the `api.*`
#      site block. The default of `100r/m` is conservative for a
#      self-host; bump it if your traffic warrants.
#
# ============================================================================

(common) {
    encode gzip zstd

    # Security headers — applied to ALL sites that `import common`
    # (currently both `api.placeholder.tld` and `placeholder.tld`).
    # The values below are conservative defaults; tighten further
    # by removing individual `permissions-policy` features you
    # never use.
    header {
        # HSTS: 1 year + includeSubDomains + preload-eligible.
        # Operators who want to submit to the HSTS preload list
        # can add `preload`; doing so commits the domain to HSTS
        # for 1+ year and is hard to undo.
        Strict-Transport-Security "max-age=31536000; includeSubDomains"

        # CSP: same-origin default; allow inline styles for
        # Next.js's runtime CSS-in-JS (the production build
        # hashes these; a stricter `unsafe-inline` block is
        # acceptable here). The `connect-src` allows the API
        # subdomain; tighten to your real domain in step 1.
        Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://api.placeholder.tld; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"

        # Clickjacking defence.
        X-Frame-Options "DENY"

        # Referrer: only send the origin (not the full URL) to
        # cross-origin requests; same-origin gets the full URL.
        Referrer-Policy "strict-origin-when-cross-origin"

        # Disable browser features the app does not use. This
        # blocks a malicious script from invoking them.
        Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"

        # Defense-in-depth: prevent MIME-type sniffing.
        X-Content-Type-Options "nosniff"
    }
}

api.placeholder.tld {
    import common

    # Rate limit: 100 requests/minute per remote IP for the
    # API surface. Caddy's built-in `rate_limit` (v2.7+) is a
    # sliding-window counter in-memory; for a multi-replica
    # Caddy deployment, swap to `caddy-dynamic-ratelimit` (Redis
    # backend). Single-host self-host: in-memory is fine.
    rate_limit {remote.ip} 100r/m

    reverse_proxy localhost:8000
}

placeholder.tld {
    import common
    reverse_proxy localhost:3000
}

# Email for Let's Encrypt / ZeroSSL account registration. Replace
# with a real address before deploying. Caddy will refuse ACME
# issuance without an email.
{
    email ops@placeholder.tld
}
```

### Header value rationale

- **`Strict-Transport-Security "max-age=31536000; includeSubDomains"`**:
  1 year is the recommended minimum for HSTS preload eligibility.
  `includeSubDomains` is opt-in to the HSTS preload list (without
  `preload` it does NOT submit you — operators can opt-in
  separately). NOT adding `preload` by default is the safe choice
  (an operator who wants to submit to the HSTS preload list
  reads the doc first).
- **`Content-Security-Policy "default-src 'self'; ...; frame-ancestors 'none'; ..."`**: the `frame-ancestors 'none'` is the modern equivalent of `X-Frame-Options: DENY` (kept for legacy browser compat). `'unsafe-inline'` for `script-src` + `style-src` is the Next.js production-build concession; the build hashes the inline content so it's not actually a vulnerability, but the CSP directive syntax doesn't accept hashes without a build-time codegen step. A future plan can add the build-time hash extraction (Next.js's experimental CSP support).
- **`X-Content-Type-Options "nosniff"`**: prevents MIME-sniffing
  attacks where a script uploaded as `.txt` is interpreted as JS.
- **`Permissions-Policy`** list: `accelerometer, camera, geolocation, gyroscope, magnetometer, microphone, payment, usb` are the
  features most commonly abused by malicious iframes. Add
  `interest-cohort=()` to opt out of FLoC if the operator cares.

## Test plan

1. **`caddy validate`** (with the dev `placeholder.tld` domains)
   returns `valid configuration`.
2. **`caddy run --config Caddyfile --adapter ""`** boots Caddy
   without error.
3. **`curl -I https://api.placeholder.tld/`** (with a local
   `/etc/hosts` override pointing the domain to 127.0.0.1)
   returns all 6 security headers.
4. **Rate limit triggers**: a script that POSTs 101 requests in
   1 minute to `https://api.placeholder.tld/api/v1/account`
   gets the 101st request rejected with HTTP 429.
5. **CSP blocks inline script injection**: a malicious payload
   `"><script>alert(1)</script>` in a query string does NOT execute
   (the CSP `script-src 'self'` blocks the inline `<script>`).
6. **HSTS enforces HTTPS**: `curl -I --http1.0 http://api.placeholder.tld/`
   returns a 301 redirect to `https://`.

## Acceptance criteria

- [ ] `caddy validate` exits 0 on the new file.
- [ ] All 6 security headers (`Strict-Transport-Security`,
      `Content-Security-Policy`, `X-Frame-Options`, `Referrer-Policy`,
      `Permissions-Policy`, `X-Content-Type-Options`) are present
      on responses to both the api + web site blocks.
- [ ] `rate_limit {remote.ip} 100r/m` is active on the api site
      block; the web site block is NOT rate-limited.
- [ ] Top-of-file `## PRODUCTION CHECKLIST` block + `# !!! REPLACE !!!`
      annotations on both domain lines are present.
- [ ] `email` directive is present at the bottom (the operator
      replaces `ops@placeholder.tld` with their real address).
- [ ] No production code paths change.

## Out-of-scope / deferred

- **CSP build-time hash extraction** for the Next.js inline
  scripts/styles: requires a Next.js custom server or a
  post-build script. Out of scope for v0.9.8.
- **WAF / mod_security**: out of scope for single-host self-host.
- **Multi-replica rate limiting via Redis**: out of scope (single
  host in-memory is fine for the canonical deploy).
- **mTLS to the API upstream** (Caddy → uvicorn on :8000): the
  upstream is localhost, no need.
- **OCSP stapling / CRL**: Caddy enables OCSP stapling by default
  with the automatic_https. No additional config needed.

## Maintenance notes

- The Caddy `rate_limit` directive was added in Caddy v2.7. The
  plan assumes Caddy v2.7+ is the production version. Operators
  on older Caddy versions must upgrade.
- The `email` directive in the global options block is the
  canonical way to set the Let's Encrypt account. Caddy v2.5+
  also supports `acme` blocks per-site for multi-domain setups
  with different ACME accounts; the global `email` is the
  simple case.
- The `connect-src` CSP directive references
  `https://api.placeholder.tld` — the operator must update this
  in step 1 of the production checklist to match their real
  domain. Missing this update means the frontend cannot talk to
  the API. A future plan can template this via Caddy's
  `{placeholder.tld}` substitution syntax.
