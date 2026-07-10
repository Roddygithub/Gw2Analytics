# advisor-plan 012 — Dockerfile prod + compose.prod.yml

## Problem

Zero Dockerfile anywhere in the repo. README Quickstart stops at dev (`uv run fastapi dev` + `pnpm dev`). Operators have NO image-build path; cobbling together prod involves host-installed `uv` + `pnpm` + Python 3.12 + Node 20 — fragile + non-reproducible + no multi-stage layer caching. `docker-compose.yml` has only infra services (postgres + minio + redis); no `api` or `web` service.

## Context

- `find /home/roddy/Gw2Analytics -name 'Dockerfile*'` → 0 matches (verified).
- `README.md` Quickstart stops at the dev stack.
- `docker-compose.yml` has only infra; no app services.
- `Caddyfile:1-16` is the only "deploy narrative" — plan 008 will harden it.
- `apps/api/pyproject.toml` separates `dependencies` (prod) from `dev` dep group.
- `web/package.json` already has `build` script (`next build`).

## Approach

Two multi-stage Dockerfiles (one for FastAPI gateway, one for Next.js web) + a `docker-compose.prod.yml` layering atop the existing dev compose. Apps/api uses Python 3.12-slim + `uv` runtime; web uses Next.js 16 standalone output (`output: 'standalone'`) for a minimal prod layer.

## Files

**In scope**:
- NEW `apps/api/Dockerfile`
- NEW `apps/api/.dockerignore`
- NEW `web/Dockerfile`
- NEW `web/.dockerignore`
- MODIFIED `web/next.config.ts` (add `output: 'standalone'`)
- NEW `docker-compose.prod.yml`

**Out of scope**:
- Existing `docker-compose.yml` (kept as-is for dev).
- `Caddyfile` (plan 008).

## Steps

1. Create `apps/api/Dockerfile`:
   - Stage 1 `builder`: `FROM astral/uv:python3.12-bookworm AS builder`; `WORKDIR /app`; `COPY pyproject.toml uv.lock /app/`; `uv sync --frozen --no-dev` (lockfile-resolved exact versions); `COPY apps/api/src /app/apps/api/src`; `COPY apps/api/alembic /app/apps/api/alembic`; `COPY apps/api/alembic.ini /app/apps/api/alembic.ini`.
   - Stage 2 `runtime`: `FROM python:3.12-slim`; install `libpq5` (psycopg runtime); `COPY --from=builder /app/.venv /app/.venv`; `COPY --from=builder /app/apps/api /app/apps/api`; `ENV PATH="/app/.venv/bin:$PATH"`; `WORKDIR /app/apps/api`; `CMD ["uvicorn", "gw2analytics_api.main:app", "--host", "0.0.0.0", "--port", "8000"]`.
2. Create `apps/api/.dockerignore` excluding `.venv`, `__pycache__`, `tests/`, `*.pyc`, `.env`, `.env.local`.
3. Create `web/Dockerfile`:
   - Stage 1 `builder`: `FROM node:20-bookworm-slim AS builder`; install `pnpm@9`; `WORKDIR /app`; `COPY package.json pnpm-lock.yaml /app/`; `pnpm install --frozen-lockfile`; `COPY . /app`; `pnpm build`.
   - Stage 2 `runtime`: `FROM node:20-bookworm-slim`; `COPY --from=builder /app/.next/standalone /app`; `COPY --from=builder /app/.next/static /app/.next/static`; `COPY --from=builder /app/public /app/public`; `WORKDIR /app`; `CMD ["node", "server.js"]` (Next.js standalone emits `server.js`).
4. Create `web/.dockerignore` excluding `.next`, `node_modules`, `playwright-report`, `test-results`, `.visual-regression-output`, `tests/e2e/.visual-regression-output`.
5. Modify `web/next.config.ts` to add `output: 'standalone'` inside the existing `NextConfig` object — DO NOT remove `allowedDevOrigins` or the `headers()` block from plan 011.
6. Create `docker-compose.prod.yml` with `api` + `web` services:
   ```yaml
   services:
     api:
       build: ./apps/api
       env_file: ./.env.prod
       depends_on: [postgres, minio, redis]
       restart: unless-stopped
     web:
       build: ./web
       env_file: ./.env.prod
       depends_on: [api]
       restart: unless-stopped
   ```

## Verification

- `find . -name 'Dockerfile*' -not -path '*/node_modules/*'` → 2 results.
- `docker build -t gw2analytics-api apps/api` exits 0.
- `docker build -t gw2analytics-web web` exits 0.
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` exits 0 with both app services listed.
- Image sizes: api image ≤ 400 MB; web image ≤ 250 MB (Next.js standalone is intentionally compact).

## Test plan

- A weekly scheduled CI job `.github/workflows/dockerfile-smoke.yml` that runs both `docker build` steps on `ubuntu-latest` and posts size + step duration to the GitHub Actions summary.
- The existing pytest suite still runs against the dev install path; the Dockerfile build is an INDEPENDENT regression gate (catches dependency-resolution regressions BEFORE prod).

## Done criteria

- 2 Dockerfiles + 2 .dockerignore files present.
- `web/next.config.ts` includes `output: 'standalone'`.
- `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` returns 0.
- Manual smoke: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`; hit `http://localhost:8000/api/v1/healthz` → 200.

## Maintenance note

- `uv` in the builder preserves lockfile discipline — DO NOT swap to `pip install` (would lose `--frozen` resolution).
- Next.js standalone mode bundles only the server runtime + the route handlers — `public/` assets MUST be `COPY`-ed separately (out-of-the-box Next.js standalone does NOT auto-include them).
- `.dockerignore` matters: missing `.venv` exclusion = bloated prod image with venv + tests copied in → OOM on small prod servers.

## Escape hatch

- If the operator uses Kubernetes / Nomad / ECS, skip `docker-compose.prod.yml` and adapt the Dockerfile to the target runtime (add a start-up probe for Kubernetes). Don't force docker-compose.
- If multi-arch (ARM64 + AMD64) is needed, add `docker buildx` instructions — but DO NOT block the AMD64-only case.
- If a future uv release breaks the multi-stage `uv sync --frozen` workflow, the `astral/uv` image tag `python3.12-bookworm` matches the standard Docker Hub variants list (https://hub.docker.com/r/astral/uv/tags); other valid options are `python3.12-alpine` (smaller) or `latest` (cosmetic risk). The project's `pyproject.toml` pins `ruff>=0.15.21` so the `astral/uv` image used for `uv sync --frozen` must be ≥0.5.x; the executor should verify by `docker run --rm astral/uv:python3.12-bookworm uv --version` BEFORE building..
