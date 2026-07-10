# advisor-plan 008 — Caddyfile security headers (supersedes plans/108)

## Problem

`Caddyfile` ships as a 16-line bare reverse proxy. No HSTS, no CSP, no X-Frame-Options, no X-Content-Type-Options, no Referrer-Policy. README §"Highlights" + CHANGELOG v0.10.0 already CLAIM these were added (drift introduced around plan 108 / v0.9.3.5 — only partially carried through). An operator who copies the shipped file as-is gets an unhardened reverse proxy.

## Context

- `Caddyfile:1-16` — verbatim current content (read during audit):
  ```caddyfile
  (common) {
      encode gzip zstd
  }
  api.placeholder.tld {
      import common
      reverse_proxy localhost:8000
  }
  placeholder.tld {
      import common
      reverse_proxy localhost:3000
  }
  ```
- `README.md` §"Highlights" v0.10.0 line: "Caddyfile security headers (HSTS + CSP + frame-ancestors)" — the drift this plan fixes.
- `CONTRIBUTING.md` does NOT mention Caddyfile.
- Precedent: `plans/108-v0935-caddyfile-security-headers-cors-2host-split.md` was attempted at v0.9.3.5; the resulting file is bare, so either plan 108 was reverted or never landed fully. Treat this plan as a fresh execution that supersedes 108.

## Approach

Harden the existing `(common)` block with Caddy-native `header` directives. Replace the literal `placeholder.tld` hostnames with Caddy placeholder-snippets so an operator edits the suffix once. Add a top-of-file documentation block.

## Files

**In scope**: `Caddyfile` only (full rewrite).
**Out of scope**: `web/next.config.ts` (handled by plan 011 — Next.js `headers()` fallback as defense-in-depth); `apps/api/src/gw2analytics_api/main.py` CORS (already env-driven).

## Steps

1. Replace `(common) { encode gzip zstd }` with:
   ```
   (common) {
       encode gzip zstd
       header {
           Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
           X-Content-Type-Options "nosniff"
           Referrer-Policy "strict-origin-when-cross-origin"
           # CSP: 'self' + 'unsafe-inline' for SSR styles + data: for fonts
           Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
       }
   }
   ```
2. Replace `api.placeholder.tld` with `api.{placeholder.tld}` and `placeholder.tld` with `{placeholder.tld}` (Caddy placeholder snippets). Document at top: "Replace `placeholder.tld` with your real domain; the wildcard `{placeholder.tld}` matches `*.example.tld`."
3. Add a top-of-file comment block explaining: (a) the `placeholder.tld` substitution convention, (b) the security policy rationale, (c) the operator-side verification command `curl -I https://<your.tld>`.

## Verification

- `grep -nE 'Strict-Transport-Security|frame-ancestors|nosniff|Referrer-Policy|\{placeholder\}' Caddyfile` → matches ≥ 4.
- `grep -nE '\bplaceholder\.tld\b' Caddyfile` → must return 0 (literal hostnames gone).
- Operator-side (not CI):
  ```
  caddy validate --config Caddyfile --adapter native
  caddy run --config Caddyfile   # local preview
  curl -I http://localhost:80 | grep -iE 'strict-transport|content-security|x-content-type|referrer-policy'
  ```
  → 4 header lines expected.

## Test plan

- Add a CI step `validate-caddyfile` in `.github/workflows/ci.yml` that runs `docker run --rm -v $(pwd)/Caddyfile:/etc/caddy/Caddyfile caddy:2 caddy validate --config /etc/caddy/Caddyfile --adapter native` ONLY when `Caddyfile` is in the PR's diff (`paths` filter). Failure exits non-zero.
- Skippable locally via `[skip caddy]` in the commit message (use `git log --pretty=%B -1 | grep -i '\[skip caddy\]'` guard).

## Done criteria

- `Caddyfile` has all 4 header directives + uses `{placeholder.tld}` wildcard snippet.
- `caddy validate` returns 0 from the new CI step.
- `grep 'placeholder.tld' Caddyfile` returns 0.
- Operator-side `curl -I` returns the 4 header lines on the deployed host.

## Maintenance note

- CSP `script-src 'self'` will block any future inline `<script>` injected into the Next.js app — coordinate relaxations with plan 011 (they must agree on the policy).
- `Strict-Transport-Security max-age=63072000` (2 years) locks HTTPS for 2 years if the operator commits; ensure the operator can revert HTTPS within the max-age window before applying.
- HSTS preload list submission is operator's responsibility (don't auto-submit; the operator must verify domain ownership + reachability on https://hstspreload.org first).

## Escape hatch

- If the operator already runs Caddy with their own config, OR fronts with Cloudflare (which sets HSTS itself), do NOT force-merge this plan. Document it in `docs/prod-hardening.md` §"Reverse proxy" as the recommended shape and stop.
- If a future operator pushes a CSP relaxation (inline script), document the inline-script location + the relaxation rationale in the COMMIT MESSAGE of the file that adds it — CSP drift is invisible otherwise.
