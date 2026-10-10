# Security Policy

## Supported versions

| Version | Supported          |
|---------|-------------------|
| `main` | Active development |
| Latest tagged release | Security fixes when practical |
| Older tags | No guaranteed support |

## Reporting a vulnerability

**Do NOT open a public issue.** Use GitHub's Security Advisories:
`https://github.com/Roddygithub/Gw2Analytics/security/advisories`

See the Disclosure policy below for the full process.

---

## Security posture

### ✅ In place

| Layer | Control | Detail |
|-------|---------|--------|
| **TLS** | Let's Encrypt auto-TLS | Caddy reverse proxy (Caddyfile) |
| **HSTS** | 2-year, includeSubDomains, preload | Caddyfile + next.config.ts |
| **CSP** | Strict 'self' + 'unsafe-inline' (styles) | Caddyfile + next.config.ts |
| **Clickjacking** | `frame-ancestors 'none'` | Caddyfile + next.config.ts |
| **MIME sniffing** | `X-Content-Type-Options: nosniff` | Caddyfile + next.config.ts |
| **Referrer** | `strict-origin-when-cross-origin` | Caddyfile + next.config.ts |
| **CORS** | Default `http://localhost:3000`, configurable | `config.py` (`CORS_ALLOWED_ORIGINS`) |
| **Request body** | 100 MiB cap | Caddyfile (`request_body max_size`) + API (`MAX_UPLOAD_SIZE_BYTES`) |
| **Secrets at rest** | Fernet envelope encryption | `crypto.py` (`SECRETS_KEK`) |
| **Docker non-root** | API + Web run as `appuser` (not root) | Dockerfiles |
| **Docker privileges** | No `--privileged`, no extra capabilities | `docker-compose.prod.yml` |
| **Dependency audit** | pip-audit + pnpm audit on HIGH+ | CI workflow (`ci.yml`) |
| **Schema guard** | Alembic version check at startup | `schema_guard.py` |
| **Secure defaults** | CORS localhost only, no debug mode | `config.py` |
| **Rate limiting** | SlowAPI: 5/min uploads, 30/min public API routes, 100/min default | `limiter.py`, routes |

### ⚠️ Needs attention (production deployment)

| Item | Risk | Action |
|------|------|--------|
| **Database password** | Default `gw2analytics` | Change in `.env.prod` |
| **S3 secret key** | Placeholder `change-me-prod-secret-key` | Generate real key |
| **Fernet KEK** | Test key committed | Generate via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| **Domain** | `{placeholder.tld}` in Caddyfile | Replace with real domain |
| **CORS** | Defaults to `localhost:3000` | Set `CORS_ALLOWED_ORIGINS` to real domain |

### ❌ Missing

| Item | Impact | Priority |
|------|--------|----------|
| **API authentication** | Uploads and analytics reads are anonymous by design; `/api/v1/account` requires a GW2 API key. | Medium |
| **Audit logging** | No structured access/error logs beyond Uvicorn defaults | Low |

### 🔍 CI security gates

All gates run on every push to `main` and every PR:

| Gate | Tool | Failure mode |
|------|------|-------------|
| Python lint | ruff check | Hard fail |
| Python format | ruff format --check | Hard fail |
| Python types | mypy (144 source files) | Hard fail |
| Python vulns | pip-audit (OSV, HIGH+) | Hard fail |
| Node vulns | pnpm audit (HIGH+) | Hard fail |
| Schema drift | alembic head vs DB | Hard fail |
| API client drift | openapi-typescript diff | Hard fail |
| TypeScript types | tsc --noEmit | Hard fail |
| E2E tests | Playwright (chromium) | Hard fail |
| Visual regression | Playwright (PR only) | Hard fail |
| Unit tests | pytest + vitest | Hard fail |

---

## Disclosure policy

1. Reporter emails maintainer with vulnerability details.
2. Maintainer acknowledges within 48 hours.
3. Fix is developed in a private fork.
4. Coordinated release: patch + advisory published simultaneously.
5. Reporter credited in release notes (unless anonymity requested).

**Contact**: See repository owner for current contact information.
