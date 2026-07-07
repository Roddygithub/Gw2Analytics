# GW2Analytics

[![CI](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml)

**Status:** 149 active tests across libs + apps + web (110 pytest cases in `libs/gw2_*` + `apps/api` + 39 vitest cases in `web/`; 1 conditionally skipped real-fixture integration test in `libs/gw2_evtc_parser/tests/test_parser.py::test_real_evtc_binary_parses_with_realistic_agent_count` requires the blob at `/tmp/inner_20251002-213519`) · 10 release tags shipped (latest: `v0.7.1`) · strict CI lint-and-test + pnpm typecheck + vitest gate active.

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
| `libs/gw2_analytics`                           | Single-, multi-fight, and event-driven aggregations (`SingleFight` / `MultiFight` / `TargetDps` / `TargetHealing` / `TargetBuffRemoval` / `EventWindow` / `PlayerProfile` / `SquadRollup` / `SkillUsage`). Frozen pydantic shapes with deterministic ordering + cross-field invariants. Parser-sourced `Iterable[Event]` stream from the v0.5.0-parser wire-up.     |
| `libs/gw2_api_client`                          | Typed async httpx wrapper for the Guild Wars 2 REST API v2.                             |
| `apps/api`                                     | FastAPI gateway v0.7.0. MinIO blobs + Alembic + Postgres. Endpoints: `POST /api/v1/uploads`, `GET /api/v1/uploads/{id}`, `GET /api/v1/fights[/{id}]`, `GET /api/v1/fights/{id}/events` (per-target DPS + HPS + BPS + per-bucket event windows), `GET /api/v1/fights/{id}/squads` (v0.7.0), `GET /api/v1/fights/{id}/skills` (v0.7.0), `GET /api/v1/players` (v0.7.0), `GET /api/v1/players/{account_name:path}` (v0.7.0), `GET /api/v1/account`. **Thin: serialises `gw2_core` + composes `gw2_api_client`.** |
| `web`                                          | Next.js 16 frontend. AG Grid Community tables (`FightsGrid`, `PlayersGrid`), GW2 API key resolve via `/account`, combat-log POST via `/upload` (multiform `POST /api/v1/uploads`). Server Components SSR-fetch the gateway. OpenAPI codegen via `pnpm generate:api`. The player-centric surface (`/players` + `/players/[account_name]`) + per-fight squad + skill roll-ups ship in v0.7.1. |

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
| `v0.4.0-web`                 | `web`              | `/fights/[id]` drill-down page (per-target damage + healing + event windows) |
| `v0.4.0-tooling`             | tooling            | Workspace-aware pre-commit mypy hook (`uv run mypy --no-incremental`) |
| `v0.5.0-parser`              | `gw2_evtc_parser`  | Phase 7 v2: `Event` discriminated union + healing extraction |
| `v0.5.0-web`                 | `web`              | Phase 7 v2: window-s selector on `/fights/[id]` |
| `v0.6.0`                     | full-stack         | Phase 8: `BuffRemovalEvent` end-to-end + per-target filter + CI Postgres service |
| `v0.7.0`                     | full-stack         | Phase 9: player-centric surface (`PlayerProfileAggregator` + `SquadRollupAggregator` + `SkillUsageAggregator`) + 4 new API endpoints (`/api/v1/players`, `/api/v1/players/{account_name:path}`, `/api/v1/fights/{id}/squads`, `/api/v1/fights/{id}/skills`) + 7 new e2e tests |
| `v0.7.1`                     | `web`              | Phase 9 of web: player-centric UI (`/players` + `/players/[account_name]`) + per-fight squad + skill roll-ups (`SquadRollupsGrid` + `SkillUsageTable` + `EventWindowsChart` + `PlayerSearchBar` + `PlayersGrid`) + 4 new fetcher helpers + 13 new vitest cases |

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
✅ **Phase 8** — `BuffRemovalEvent` end-to-end (parser dual-emit contract + `TargetBuffRemovalAggregator` + `target_buff_removal` on `/fights/{id}/events` + per-target filter dropdown on `/fights/[id]`). Tagged `v0.6.0`. CI services block landed (Postgres on a fresh runner).
✅ **Phase 9 (v0.7.0 backend)** — Player-centric surface. `PlayerProfileAggregator` (cross-fight join on `account_name`, first-seen profession/elite, last-seen name, dedup on `(account_name, fight_id)`), `SquadRollupAggregator` (per-subgroup source-side roll-up), `SkillUsageAggregator` (per-skill hit count + damage/heal/strip totals). 4 new API endpoints: `GET /api/v1/players` (paginated cross-fight roll-up), `GET /api/v1/players/{account_name:path}` (full profile + per-fight breakdown), `GET /api/v1/fights/{id}/squads`, `GET /api/v1/fights/{id}/skills`. 7 new self-contained e2e tests. Tagged `v0.7.0`. The web layer (2 new pages + 4 new components + nav update) ships in v0.7.1.
✅ **Phase 9 of web (v0.7.1)** — Player-centric UI. 2 new pages (`/players` + `/players/[account_name]`) + 5 new components (`SquadRollupsGrid` for the per-subgroup roll-up, `SkillUsageTable` for the per-skill roll-up, `EventWindowsChart` for the inline SVG bar chart of the per-bucket event windows, `PlayerSearchBar` in the layout's sticky header bar, `PlayersGrid` for the paginated AG Grid). The `/fights/[id]` page now fires 3 parallel fetchers via `Promise.allSettled` (events + squads + skills) so a single fetcher failure does not blank the whole page. 13 new vitest cases. Tagged `v0.7.1`.

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
