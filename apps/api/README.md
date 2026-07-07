# `apps/api` — GW2Analytics FastAPI gateway

The HTTP surface for the GW2Analytics monorepo. This package is a **thin
adapter** — it serializes [`gw2_core`](../libs/gw2_core) models in/out of
HTTP, persists uploads + parsed fights to Postgres via Alembic + SQLAlchemy,
stores `.zevtc` blobs in MinIO (S3 protocol), and composes
[`gw2_api_client`](../libs/gw2_api_client) for the upstream Guild Wars 2
v2 REST API.

No business logic lives here — aggregation lives in
[`gw2_analytics`](../libs/gw2_analytics) and parsing lives in
[`gw2_evtc_parser`](../libs/gw2_evtc_parser).

## Endpoints

| Method | Path                               | Auth                | Purpose                                         |
|--------|------------------------------------|---------------------|-------------------------------------------------|
| `GET`  | `/healthz`                         | —                   | Liveness probe                                  |
| `POST` | `/api/v1/uploads`                  | —                   | Ingest a `.zevtc` blob → enqueue parse          |
| `GET`  | `/api/v1/uploads/{id}`             | —                   | Inspect an upload row (sha256 + status + fight) |
| `GET`  | `/api/v1/fights`                   | —                   | Paginated list of parsed fights                 |
| `GET`  | `/api/v1/fights/{id}`              | —                   | One parsed fight with agents + skills           |
| `GET`  | `/api/v1/account`                  | `Bearer <GW2_API_KEY>` | Resolve the authenticated account to a `(world_id, world_name, world_population)` triple |

Full OpenAPI spec served at `/openapi.json` and `/docs` once the server is
up. The `web/` frontend regenerates its typed client (`schema.d.ts`) from
this spec via `pnpm generate:api` (no live uvicorn needed; uses
`app.openapi()` in-process via `web/scripts/dump_openapi.py`).

## Local bring-up

See the root `README.md` Quickstart for the end-to-end bring-up (infra,
env, alembic, fastapi). Quickstart steps 4-8 cover this package.

## Postgres dependency for the e2e test

The unconditional e2e suite in `tests/test_uploads_e2e.py` exercises the
full POST → GET uploads → GET fights chain against a **real** Postgres
on every pytest run. The test runs unconditionally against any environment
with a Postgres reachable at the `DATABASE_URL` declared in
`[tool.pytest_env]` / `.env`.

| Environment          | Bring up                                                          |
|----------------------|-------------------------------------------------------------------|
| Local dev            | `docker compose up -d gw2a-postgres` (already in `docker compose up -d`) |
| GitHub Actions CI    | `lint-and-test` job spins up a `postgres:16-alpine` service on `localhost:5432` (credentials match `pytest_env`) |
| Ad-hoc prod-shaped   | Any reachable Postgres ≥ 14 will do — Alembic baseline migration is API-version-agnostic |

If a test name is mentioned elsewhere in the docs and gets renamed (the
contract — POST → GET uploads → GET fights chain — is what matters, not
the function identifier), update the contract description, not the
function name in prose.

If a developer runs `pytest` without a reachable Postgres, the e2e test
**raises** (not skips) — that's the intended loud signal.

## Layout

```
apps/api/
├── pyproject.toml          # 0.2.0 — depends on gw2_api_client>=0.1.0
├── alembic.ini             # script_location = alembic (relative to apps/api)
├── alembic/                # Alembic migration scripts + env.py
│   ├── env.py
│   └── versions/
│       ├── 0001_v0_5_baseline.py
│       ├── 0002_agent_identity_columns.py
│       └── 0003_fight_skills.py
├── src/gw2analytics_api/
│   ├── __init__.py         # re-exports __version__ + app
│   ├── __main__.py         # `python -m gw2analytics_api` entry
│   ├── main.py             # FastAPI app + middleware + include_router + FastApiMCP
│   ├── config.py           # env-driven Settings (no hardcoded credentials)
│   ├── database.py         # SQLAlchemy engine + get_session dependency
│   ├── storage.py          # MinIO client + put_zevtc helper
│   ├── services.py         # process_parse background task
│   ├── models.py           # ORM models for fights / agents / skills / uploads
│   ├── schemas.py          # Pydantic v2 response/request schemas
│   └── routes/
│       ├── uploads.py      # POST /api/v1/uploads + GET /api/v1/uploads/{id}
│       ├── fights.py       # GET /api/v1/fights + GET /api/v1/fights/{id}
│       └── account.py      # GET /api/v1/account (Bearer-protected)
└── tests/
    ├── test_healthz.py
    ├── test_uploads_e2e.py # 2 e2e tests (Postgres-required)
    ├── test_account.py     # 11 respx-mocked tests
    └── test_config.py      # 9 regression tests for Settings env parser
```

## Conventions

- Routes import no FastAPI primitives directly — each lives in its own
  `routes/<name>.py` and exposes a single `router` object that
  `main.py` `include_router()`s.
- HTTP boundary does **not** translate domain models directly — every
  response is a Pydantic v2 schema (`schemas.py`) that maps ORM rows
  with `from_attributes=True` so the SQL layer evolves independently.
- Auth errors are surfaced with `WWW-Authenticate: Bearer` headers
  (see `routes/account.py::_bearer`).
- CORS is **env-driven** via `CORS_ALLOWED_ORIGINS` (comma-separated
  origins, with `*` as the wide-open shortcut for local dev). Default
  in dev = `["*"]`; tighten to the real domain list in production.
