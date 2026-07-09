# Plan 108 (v0.9.35) — `Caddyfile` security headers + cross-origin CORS for the 2-host split

## Files touched
- `Caddyfile` (REWRITE — add a `(security_headers)` global snippet with HSTS + X-Frame-Options + X-Content-Type-Options + Referrer-Policy + Permissions-Policy + add `header` directives on each host block; import the security snippet on both blocks)
- `Caddyfile` (add explicit `api.placeholder.tld /api/*` CORS preflight handling OR import a `(cors)` snippet)
- `docs/self-host.md` (NEW — operationally-document the Caddyfile security model; cross-link with the `next.config.ts::headers()` belt-and-braces layer from plan 056)

## Findings (audit)

- `Caddyfile` line 4: `(common) { encode gzip zstd }` — only the `encode` directive is set globally. No security headers.
- `A reverse proxy that terminates TLS for a self-hosted WvW analytics app should ship at minimum:**
  1. **`Strict-Transport-Security`** — pins HTTPS for the lifetime of the cert; the caddyfile has no HSTS.
  2. **`X-Frame-Options`** — prevents clickjacking against the AG Grid dashboard if it's ever embedded.
  3. **`X-Content-Type-Options: nosniff`** — prevents content-type sniffing on the JSON event blobs.
  4. **`Referrer-Policy: strict-origin-when-cross-origin`** — privacy hygiene on the user-agent side.
  5. **`Permissions-Policy`** — restricts browser features (camera/microphone/geolocation) the app never needs; defence-in-depth.
- The web layer (`web/next.config.ts::headers()`) per plan 056 v0.9.18 added 4 canonical headers (Belt-and-braces behind Caddy). The Caddyfile has NO matching production-side headers; the web's headers fall back to production when the Caddy layer is missing, but Caddy is the canonical reverse-proxy and should ship them too.
- The CORS situation is fine TODAY: `placeholder.tld` (the Next.js web at `:3000`) is reverse-proxied by Caddy to the SAME-ORIGIN browser client, so the browser fetches at `/api/*` (Next.js rewrites) which the Next.js server proxies to `api.placeholder.tld/api/*`. The Next.js server is the cross-origin proxy. Browsers don't see the cross-origin directly. So CORS preflight headers are added by Next.js / the API layer (`apps/api/main.py::app.add_middleware(CORSMiddleware, ...)`), not by Caddy.
- However, a future deployment where the Next.js web uses an absolute URL `https://api.placeholder.tld` (instead of relative `/api/*`) WOULD trigger cross-origin CORS preflight at the BROWSER level. Caddy needs to handle `OPTIONS /` preflight against `api.placeholder.tld` correctly WHEN the response passes through via the Caddy → `:8000` reverse proxy. The current config (just `reverse_proxy localhost:8000`) doesn't add any `Access-Control-Allow-Origin` headers — the FastAPI CORS middleware supplies them only after the OPTIONS request hits the FastAPI handler. If Caddy intercepts the OPTIONS preflight before FastAPI sees it (it shouldn't — `reverse_proxy` passes all methods), the preflight fails.
- Actually, `reverse_proxy` passes all methods by default. FastAPI's CORS middleware handles OPTIONS preflight correctly. So the Caddy-side CORS is OPTIONAL — only needed if a developer opts-in to passing `Access-Control-Allow-Origin` headers from Caddy (defence-in-depth, like the plan 056 belt-and-braces pattern).

## Fix

1. REWRITE `Caddyfile`:

   ```caddy
   # Caddy reverse-proxy for self-hosted GW2Analytics.
   # Replace *placeholder.tld with your real domain in production.

   # ----------------------------------------------------------------
   # (security_headers) snippet
   # ----------------------------------------------------------------
   # Canonical security headers. Belt-and-braces: the
   # `next.config.ts::headers()` layer (per plan 056 v0.9.18)
   # adds the same 4 headers to web responses served from
   # the Next.js server. Caddy adds them at the TLS-termination
   # boundary so even non-web responses (the API responses that
   # the browser sees via the API gateway) carry the headers.
   #
   # HSTS:
   #   - ``max-age=31536000`` pins HTTPS for 1 year.
   #   - ``includeSubDomains`` propagates to api.placeholder.tld.
   #   - ``preload`` is omitted (would add the domain to the
   #     browser preload list; an operator decision, not a default).
   (security_headers) {
       header Strict-Transport-Security "max-age=31536000; includeSubDomains"
       header X-Frame-Options "DENY"
       header X-Content-Type-Options "nosniff"
       header Referrer-Policy "strict-origin-when-cross-origin"
       header Permissions-Policy "camera=(), microphone=(), geolocation=(), interest-cohort=()"
   }

   # ----------------------------------------------------------------
   # (common) snippet: compression + security headers
   # ----------------------------------------------------------------
   (common) {
       encode gzip zstd
       import security_headers
   }

   # ----------------------------------------------------------------
   # api.placeholder.tld: reverse-proxy to the FastAPI gateway
   # ----------------------------------------------------------------
   # The CORS preflight is handled by the FastAPI app's
   # ``CORSMiddleware`` -- Caddy passes ALL methods (OPTIONS
   # included) to the upstream; the upstream's preflight logic
   # returns the Access-Control-* headers. If a developer opts
   # into absolute-URL fetching (e.g. a CORS-debugging tool
   # from a browser extension), the preflight will succeed via
   # the upstream FastAPI handler.
   api.placeholder.tld {
       import common
       reverse_proxy localhost:8000
   }

   # ----------------------------------------------------------------
   # placeholder.tld: reverse-proxy to the Next.js web
   # ----------------------------------------------------------------
   # The :3000 process is a Server Component / Client Component
   # boundary; the Next.js server proxies ``/api/*`` requests to
   # the FastAPI gateway via Caddy's ``api.placeholder.tld``
   # route. No CORS browser-side is required for the same-origin
   # ``/api/*`` path.
   placeholder.tld {
       import common
       reverse_proxy localhost:3000
   }
   ```

2. NO `docker-compose.yml` change in this plan (the API + web service definitions are intentionally NOT in the compose file per `find 1` of plan 107 — operator runs them outside of compose).

3. NEW `docs/self-host.md` — operationally document the security model:

   ```markdown
   # Self-hosting GW2Analytics

   The default deployment is a 3-process layout on a single
   VM:

   - Postgres (Docker, ``docker compose up -d postgres``)
   - MinIO (Docker, ``docker compose up -d minio``)
   - FastAPI gateway (Python, ``uv run apps/api``)
   - Next.js web (Node, ``pnpm --dir web start``)
   - Caddy (system package, reverse-proxy + TLS)

   ## TLS + security headers

   Caddy terminates TLS and adds 5 canonical security headers
   on every response (the ``(security_headers)`` snippet in
   the root ``Caddyfile``):

   - ``Strict-Transport-Security: max-age=31536000; includeSubDomains``
   - ``X-Frame-Options: DENY``
   - ``X-Content-Type-Options: nosniff``
   - ``Referrer-Policy: strict-origin-when-cross-origin``
   - ``Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()``

   ``next.config.ts`` (per plan 056 v0.9.18) adds 4 of these
   headers AGAIN on web responses for belt-and-braces. The
   Caddy layer is the canonical authority; the Next.js layer
   is the failover for direct-IP / production-debug routes.

   ## CORS

   Same-origin web traffic (``placeholder.tld/api/*`` is
   proxied through Next.js to ``api.placeholder.tld/api/*``)
   does NOT trigger browser CORS preflight. The
   ``CORSMiddleware`` in ``apps/api/main.py`` adds the
   ``Access-Control-Allow-Origin`` headers for any cross-origin
   fetch (a browser extension debugging tool, an external
   integrator hitting the API directly, etc.).
   ```

## Tests (3, NEW file `caddy/tests/test_caddyfile.py` — uses Caddy's `caddy adapt` JSON-output mode)

- `test_security_headers_snippet_emits_five_canonical_headers` — invoke `caddy adapt --config Caddyfile --pretty` (a tiny test harness); assert the resulting JSON config has 5 `header` directives matching the 5 canonical security headers (regex match on the JSON config body).
- `test_api_host_block_imports_common_snippet` — same JSON config; assert the `api.placeholder.tld` block has an `import` directive referring to the `(common)` snippet (which transitively pulls in the security headers).
- `test_web_host_block_imports_common_snippet` — same JSON config; assert the `placeholder.tld` block also imports `(common)`.

If `caddy` is not in the CI sandbox (operator probably installs it for `caddy adapt`), the test can be skipped via a `pytest.skip("caddy binary not found")` guard; the test is a developer-experience assist, not a CI gate.

## Rejected alternatives

- **Skip the Caddy-side headers and rely solely on the `next.config.ts::headers()` layer** — works for web responses but not for the FastAPI gateway responses (the analytics bulk-download endpoints, the player profile JSON endpoint). The Caddy layer is the canonical reverse-proxy; the web's belt-and-braces covers `:`3000 origins but not all paths. REJECTED.
- **Set the security headers via Caddy `reverse_proxy.header_up` / `header_down`** — fragile (sub-attribute transposition); the `header` directive is the canonical Caddy pattern. REJECTED.
- **Add Caddy-side CORS handling with the `acme_server` / `cors` snippet** — adds an additional CORS layer that conflicts with the FastAPI `CORSMiddleware`. The FastAPI middleware is the canonical CORS authority; Caddy passes OPTIONS through cleanly. REJECTED.
- **Use Caddy's response header rewrite (`header_down` on the response body matching)** — complexity creep. The `header` directive on each block is the canonical pattern. REJECTED.
- **Replace the Caddy config with `caddy-docker-proxy` for a single Docker-managed config** — couples Caddy to docker; the current pattern (system Caddy + Docker services) is the canonical self-hosting approach. REJECTED.

## Dependency graph

- Independent: touches `Caddyfile` only + NEW `docs/self-host.md` + 1 NEW test file (skipped in CI if `caddy` binary absent).
- Parallel-safe with plans 107 / 109.
- Pattern-aligns with the `plan 056 v0.9.18` belt-and-braces model (web's `headers()` async function added the same 4 headers, plus `X-DNS-Prefetch-Control`). The Caddy layer adds the 5 canonical + `Permissions-Policy`.
- Pattern-aligns with the standard Caddyfile canonical structure (a global `(snippet)` + per-host `import` directives) — the canonical clean pattern.
