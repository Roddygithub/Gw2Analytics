# GW2Analytics

[![CI](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml)

**Status:** 101 active tests across libs + apps + web (89 pytest cases in `libs/gw2_*` + `apps/api` + 12 vitest cases in `web/`; 1 conditionally skipped real-fixture integration test in `libs/gw2_evtc_parser/tests/test_parser.py::test_real_evtc_binary_parses_with_realistic_agent_count` requires the blob at `/tmp/inner_20251002-213519`) · 8 release tags shipped (incl. `v0.3.0`) · strict CI lint-and-test + pnpm typecheck + vitest gate active.

Modern combat analytics platform for **Guild Wars 2 WvW** (World vs World).

> Independent of any third-party service (no dps.report, Elite Insights web, etc.).
> WvW combat logs (`.zevtc`) are parsed locally and stored in a stable
> internal model from which all analytics, API, and frontend derive.

---

## Architecture & Component Status

```
                              gw2_evtc_parser
                                     │
                                     ▼ produces
                                  gw2_core ◀──constrains── gw2_analytics
                                     │
                                     ▼
                                apps/api  ──gw2_api_client── GW2 v2
                                     │
                                     ▼
                                web (Next.js 16)
```

| Component                                      | Role                                                                                    |
|------------------------------------------------|-----------------------------------------------------------------------------------------|
| `libs/gw2_core`                                | Stable Pydantic models (combat + API). Single source of truth. **No I/O.**              |
| `libs/gw2_evtc_parser`                         | Binary `.zevtc` parser behind an `EvtcParser` Protocol. V1.3 layout.                    |
| `libs/gw2_analytics`                           | Single-, multi-fight, and event-driven aggregations (`SingleFight` / `MultiFight` / `TargetDps` / `EventWindow`). Frozen pydantic shapes with deterministic ordering + cross-field invariants. **Synthetic `Iterable[Event]` input today; parser-sourced stream lands in Phase 7.**     |
| `libs/gw2_api_client`                          | Typed async httpx wrapper for the Guild Wars 2 REST API v2.                             |
| `apps/api`                                     | FastAPI gateway v0.3.0. MinIO blobs + Alembic + Postgres. Endpoints: `POST /api/v1/uploads`, `GET /api/v1/uploads/{id}`, `GET /api/v1/fights[/{id}]`, `GET /api/v1/fights/{id}/events` (Phase 6 stub), `GET /api/v1/account`. **Thin: serialises `gw2_core` + composes `gw2_api_client`.** |
| `web`                                          | Next.js 16 frontend. AG Grid Community tables (`FightsGrid`), GW2 API key resolve via `/account`, combat-log POST via `/upload` (multiform `POST /api/v1/uploads`). Server Components SSR-fetch the gateway. OpenAPI codegen via `pnpm generate:api`. |

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

# 6. Apply the Postgres schema (creates the fights / agents / skills / uploads tables)
cd apps/api && uv run alembic upgrade head && cd ../..

# 7. Boot the API (http://localhost:8000/docs)
uv run fastapi dev apps/api/src/gw2analytics_api/main.py

# 8. Frontend (Next.js 16) — the only UI for fights + API key resolve
cd web
pnpm install
pnpm dev   # http://localhost:3000
```

---

## Release Tags

| Tag                          | Component          | Description                                                  |
|------------------------------|--------------------|--------------------------------------------------------------|
| `v0.4.0-parser`              | `gw2_evtc_parser`  | V1.3 EVTC binary parser rollout with 545-test unit suite     |
| `v0.1.0-analytics-prototype` | `gw2_analytics`    | Initial single-fight aggregation models                      |
| `v0.2.0-analytics-prototype` | `gw2_analytics`    | Multi-fight rollup support across an iterable of fights      |
| `v0.2.0-core`                | `gw2_core`         | v2 REST API data models (`AccountInfo`, `WorldInfo`, `Population`) |
| `v0.1.0-api-client`          | `gw2_api_client`   | Typed async httpx wrapper for the GW2 v2 REST API surface    |
| `v0.2.0-api`                 | `apps/api`         | `GET /api/v1/account` Bearer-protected world enrichment (Phase 5) |
| `v0.3.0-web`                 | `web`              | Client upload page + canonical `formatApiError` (Phase 5 followup) |
| `v0.3.0`                     | full-stack         | Event aggregations + CI-gate stability pass (Phase 6 + release cut) |

See [`CHANGELOG.md`](CHANGELOG.md) for the per-commit history and the linking notes between releases.

---

## Phase Status

✅ **Phase 0** — Monorepo skeleton + tooling (`uv`, `ruff`, `mypy`) + boilerplate scaffolding.
✅ **Phase 1** — `gw2_evtc_parser` V1.3 binary layout parsing behind an `EvtcParser` Protocol. Lenient on skill tables, strict on agent boundaries. Tagged `v0.4.0-parser`.
✅ **Phase 2** — FastAPI gateway + Alembic migrations + MinIO content-addressed `.zevtc` blob storage + V1.3 `gw2_core` combat schemas. Env-driven credentials via `pydantic-settings` + `pytest-env`.
✅ **Phase 3** — `gw2_analytics` aggregations. `SingleFightAggregator` + `MultiFightAggregator` with strict frozen pydantic shapes + cross-field invariant validation. Tagged `v0.1.0-analytics-prototype` and `v0.2.0-analytics-prototype`.
✅ **Phase 4** — `web/` Next.js 16 frontend scaffolded. AG Grid Community tables (`FightsGrid`), `openapi-typescript` codegen, `pnpm typecheck` step in CI. Server Components SSR-fetch the gateway through an env-driven `src/lib/api.ts` helper.
✅ **Phase 5** — `GET /api/v1/account` Bearer-protected world enrichment. Composes `AsyncGuildWars2Client.account_get` + `worlds_get([world_id])` into a deterministic ``(world_id, world_name, world_population)`` triple. Tagged `v0.2.0-api`. The web/ side surfaced ``/upload`` (multiform `POST /api/v1/uploads` envelope renderer) + a canonical `formatApiError` helper shared with `/account`; tagged `v0.3.0-web`.
✅ **Phase 6** — Event-driven aggregations + CI-gate stability. `TargetDpsAggregator` (per-target damage roll-ups with deterministic ordering + sum-preservation invariant) and `EventWindowAggregator` (1-second bucket histogram with gap zero-fill + contiguous adjacency invariant). Both accept `Iterable[Event]` from `gw2_core` 0.3.0 (`DamageEvent` / `HealingEvent` discriminated by `EventType` StrEnum). `GET /api/v1/fights/{id}/events` route exists as a Phase 6 v1 stub returning `[]`; Phase 7 will swap parser-sourced streams in. 13 new pytest tests + 4 new vitest tests lock the surfaces. Tagged `v0.3.0`.
🔄 **Phase 7** — Parser-side V1.3 event-block consumer. `libs/gw2_evtc_parser::PythonEvtcParser::parse_events(source) -> Iterator[Event]` reads the 64-byte `cbtevent` struct at the post-skill-block offset; the filter ``is_statechange == 0 && is_nondamage == 0 && val > 0`` round-trips into a ``DamageEvent``. Storage is hybrid: per-fight gzipped JSONL blob in MinIO + an ``events_blob_uri`` column on the ``fights`` Postgres table. The apps/api background parse task persists the blob after the existing fight-row insertion; ``GET /api/v1/fights/{id}/events`` decompresses on demand and feeds ``TargetDpsAggregator`` + ``EventWindowAggregator``. ``HealingEvent`` extraction (the ``val < 0`` sign-split) is a Phase 7 v2 followup.

---

## Conventions

Project rules live in [`CONTRIBUTING.md`](CONTRIBUTING.md):

- Conventional Commits v1.0.0 spec with the canonical 9-type table.
- Branch protection for `main` (linear history, no force pushes, required status checks).
- Pre-commit / CI mirror table: `trim-whitespace`, `ruff check`, `ruff format`, `mypy`, `pytest`.
- Test requirements (cross-field invariants get explicit tests, lenient edges locked at unit level, prefer `_build_*_record` helpers).
- Per-component `pyproject.toml` + per-library release tags (scheme: `vMAJOR.MINOR.PATCH-<lib>`).

### Principles

1. **`gw2_core` is the only contract** between layers. Everything depends on it; it depends on nothing but Pydantic.
2. **The parser is replaceable** behind the `EvtcParser` Protocol. Swap Python for Rust + PyO3 with zero churn elsewhere.
3. **The frontend never knows** about EVTC, parser internals, or DB schema — only the OpenAPI surface.
4. **Each component evolves independently** — enforced by `pyproject.toml` per lib.
