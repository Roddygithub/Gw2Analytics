# GW2Analytics

Modern combat analytics platform for **Guild Wars 2 WvW** (World vs World).

> Independent of any third-party service (no dps.report, no Elite Insights web, etc.).
> WvW combat logs (`.zevtc`) are parsed locally and stored in a stable
> internal model from which all analytics, API, and frontend derive.

---

## Architecture

```
gw2_evtc_parser ──produces──▶ gw2_core ◀──consumes── gw2_analytics
                                    │
                                    ▼
                              apps/api  ◀──gw2_api_client──▶ GW2 v2
                                    │
                                    ▼
                                web (Next.js)
```

| Component | Role |
|---|---|
| `libs/gw2_core` | Stable Pydantic models. Single source of truth. No I/O. |
| `libs/gw2_evtc_parser` | Binary EVTC parser behind an `EvtcParser` Protocol. |
| `libs/gw2_analytics` | Single / multi-fight / per-player aggregations. |
| `libs/gw2_api_client` | Typed client for Guild Wars 2 REST API v2. |
| `apps/api` | FastAPI gateway. Thin: serializes `gw2_core`. |
| `web` | Next.js 15 frontend. Dense tables (gw2mists-like). |

---

## Stack

- **Backend**: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic
- **Database**: PostgreSQL 16
- **Storage**: MinIO (S3-compatible, immutable `.zevtc` blobs)
- **Cache/Queue**: Redis + Arq (background jobs)
- **Frontend**: Next.js 15, React 19, TypeScript, AG Grid Community
- **Tooling**: `uv` workspace, ruff, mypy `--strict`, pytest, pre-commit

---

## Quickstart

```bash
# 1. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install all monorepo deps including libs + apps
uv sync

# 3. Install git hooks
uv run pre-commit install

# 4. Bring up the infra (Postgres + MinIO + Redis)
docker compose up -d

# 5. Configure local app env
#    Required so the FastAPI process picks up DATABASE_URL + S3_* creds.
#    Values mirror docker-compose.yml; never commit the real .env file.
cp .env.example .env

# 6. Boot the API (http://localhost:8000/docs)
uv run fastapi dev apps/api/src/gw2analytics_api/main.py

# 7. Boot the frontend (http://localhost:3000)
cd web && pnpm dev
```

---

## Principles

1. **`gw2_core` is the only contract** between layers. Everything depends on it; it depends on nothing but Pydantic.
2. **The parser is replaceable** behind the `EvtcParser` Protocol. Swap Python for Rust + PyO3 with zero churn elsewhere.
3. **The frontend never knows** about EVTC, parser internals, or DB schema — only the OpenAPI surface.
4. **Each component evolves independently** — enforced by `pyproject.toml` per lib.

---

## Phase 0 status

✅ Monorepo skeleton + tooling + scaffolding.
🛠 Phase 1: first `EvtcParser` PartialImpl + read agents from a real `.zevtc`.

---

## Conventions

- Conventional commits (`feat:` / `fix:` / `chore:` / `refactor:` / `docs:` / `test:`)
- Squash-merged PRs, linear history
- Python: type hints mandatory (mypy `--strict`), ruff format
- TypeScript: strict mode
- See `CONTRIBUTING.md` once we add it.
