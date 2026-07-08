# GW2Analytics

[![CI](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml)
[![Latest tag](https://img.shields.io/github/v/tag/Roddygithub/Gw2Analytics?sort=semver&label=latest)](https://github.com/Roddygithub/Gw2Analytics/tags)

**Modern combat analytics platform for Guild Wars 2 WvW (World vs World).**

> Independent third-party platform — no dps.report, no Elite Insights web.
> WvW combat logs (`.zevtc`) are parsed locally and stored in a stable
> internal model from which all analytics, API, and frontend derive.

**Status:** Latest tagged release: `v0.8.9` · v0.9.0 + v0.9.1 + v0.9.2 close-out landed on `main` (tag pending operator ceremony) · **339 active tests** across pytest + vitest + Playwright · strict CI lint + test + typecheck + OpenAPI drift gate active.

## Highlights

- 🎯 **Per-target / per-subgroup / per-skill roll-ups** on every fight — DPS, healing, and buff removals via stable pydantic aggregations with deterministic ordering + cross-field invariants.
- 📈 **Account-level historical timelines** — per-day / per-fight bucketing, linear / log Y-axis, and player-name resolution on the fight drilldown's TargetFilter.
- 🔌 **Webhook subscriptions** for parse-completion notifications — HMAC-SHA256 signed, 3-attempt retry + DLQ + replay, with SSRF block (HTTPS-only + universal private-IP gate).
- 🧪 **339+ automated tests** across `pytest` (241), `vitest` (82), and `Playwright` e2e (16) — all green on every PR.
- 📦 **Pure monorepo** — `libs/gw2_core` (no I/O), `libs/gw2_evtc_parser` (replaceable Protocol), `libs/gw2_analytics` (frozen pydantic), `apps/api` (FastAPI), `web` (Next.js 16).

## Documentation

| File | Purpose |
| --- | --- |
| [CHANGELOG.md](./CHANGELOG.md) | Canonical per-commit history (includes unreleased `v0.9.x` cycles). |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Workflow conventions, branch protection rules, CI gates. |
| [docs/ROADMAP.md](./docs/ROADMAP.md) | Forward-looking candidates and technical-debt ledger. |
| [plans/README.md](./plans/README.md) | Senior-advisor audit trails and scoped cycle implementation plans. |
| [docs/v0.8.0-backend-design.md](./docs/v0.8.0-backend-design.md) | The webhook subscription + delivery worker design. |

## Architecture

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

| Component | Role |
| --- | --- |
| `libs/gw2_core` | Stable Pydantic models (combat + API). Single source of truth. **No I/O.** |
| `libs/gw2_evtc_parser` | Binary `.zevtc` parser behind an `EvtcParser` Protocol. V1.3 layout. |
| `libs/gw2_analytics` | Single-, multi-fight, and event-driven aggregations. Frozen pydantic shapes with deterministic ordering + cross-field invariants. |
| `libs/gw2_api_client` | Typed async httpx wrapper for the Guild Wars 2 REST API v2. |
| `apps/api` | FastAPI gateway. MinIO blobs + Alembic + Postgres. See the [API surface](#api-surface) below. |
| `web` | Next.js 16 frontend. AG Grid Community tables + SSR fetches. OpenAPI codegen via `pnpm generate:api`. |

## API surface

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/uploads` | Ingest a `.zevtc` log; returns 201 + `UploadCreatedResponse` (parse runs in background). |
| `GET` | `/api/v1/uploads/{id}` | Upload metadata. |
| `GET` | `/api/v1/fights[/{id}]` | List fights (paginated) or fetch a single fight. |
| `GET` | `/api/v1/fights/{id}/events` | Per-target trio (DPS + healing + buff removal) + per-bucket event windows. |
| `GET` | `/api/v1/fights/{id}/squads` | Per-subgroup roll-up. |
| `GET` | `/api/v1/fights/{id}/skills` | Per-skill hit count + damage / heal / strip totals. |
| `GET` | `/api/v1/fights/{id}/timeline?window_s=N` | Per-fight temporal view (3-series, `M:SS` relative time). |
| `GET` | `/api/v1/players?profession=&limit=&offset=` | Cross-fight player roll-up (paginated). |
| `GET` | `/api/v1/players/{account_name:path}` | Player profile + per-fight breakdown. |
| `GET` | `/api/v1/players/{account_name:path}/timeline?bucket=day&tz=Continent/City` | Account-level historical timeline. |
| `POST/GET/DELETE` | `/api/v1/webhooks[/{id}]` | Webhook subscription management (HTTPS-only URLs). |
| `POST` | `/api/v1/webhooks/dlq/{delivery_id}/replay` | Replay a DLQ'd delivery (atomic; row-level locked). |
| `GET` | `/api/v1/health/summary` | Operational drift probe (binary `ok` / `drift`). |
| `GET` | `/api/v1/healthz` | Liveness probe. |
| `GET` | `/api/v1/account` | Bearer-protected world enrichment (uses `gw2_api_client`). |

## Screenshots

The web's 7 routes captured via `pnpm screenshots` + [Playwright](https://playwright.dev/) (full pages, 1440×900, headless Chrome). Refresh via `pnpm screenshots --persist` after a UI change.

| Route | Capture |
| --- | --- |
| `/` | ![Landing](docs/screenshots/01-landing.png) |
| `/account` | ![Account resolve](docs/screenshots/02-account.png) |
| `/upload` | ![Upload flow](docs/screenshots/03-upload.png) |
| `/fights` | ![Fights grid](docs/screenshots/04-fights.png) |
| `/players` | ![Players grid](docs/screenshots/05-players.png) |
| `/players/[account_name]` | ![Player profile with timeline](docs/screenshots/06-player-profile-with-timeline.png) |

The script also captures 2 fixture/edge-state PNGs (committed but not displayed): `07-player-empty-timeline.png` + `08-fight-drilldown.png` — reserved for visual regression baselines.

## Quickstart

```bash
# 1. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install all monorepo deps including libs + apps
uv sync

# 3. Install git hooks
uv run pre-commit install

# 4. Bring up the infra (Postgres + MinIO)
docker compose up -d

# 5. Configure local app env (DB + S3 creds; never commit the real .env)
cp .env.example .env

# 6. Apply the Postgres schema
cd apps/api && uv run alembic upgrade head && cd ../..

# 7. Boot the API (http://localhost:8000/docs)
uv run fastapi dev apps/api/src/gw2analytics_api/main.py

# 8. Frontend (Next.js 16)
cd web
pnpm install
pnpm dev   # http://localhost:3000
```

## Release Tags

| Tag | Component | Summary |
| --- | --- | --- |
| `v0.4.0-parser` | `gw2_evtc_parser` | V1.3 EVTC binary parser rollout with 545-test unit suite |
| `v0.1.0-analytics-prototype` | `gw2_analytics` | Initial single-fight aggregation models |
| `v0.2.0-analytics-prototype` | `gw2_analytics` | Multi-fight rollup support across an iterable of fights |
| `v0.2.0-core` | `gw2_core` | v2 REST API data models (`AccountInfo`, `WorldInfo`, `Population`) |
| `v0.1.0-api-client` | `gw2_api_client` | Typed async httpx wrapper for the GW2 v2 REST API surface |
| `v0.2.0-api` | `apps/api` | `GET /api/v1/account` Bearer-protected world enrichment |
| `v0.3.0-web` | `web` | Client upload page + canonical `formatApiError` |
| `v0.3.0` | full-stack | Event aggregations + CI-gate stability pass |
| `v0.4.0-web` | `web` | `/fights/[id]` drill-down page |
| `v0.4.0-tooling` | tooling | Workspace-aware pre-commit mypy hook |
| `v0.5.0-parser` | `gw2_evtc_parser` | Phase 7 v2: `Event` discriminated union + healing extraction |
| `v0.5.0-web` | `web` | Phase 7 v2: window-s selector on `/fights/[id]` |
| `v0.6.0` | full-stack | Phase 8: `BuffRemovalEvent` end-to-end + per-target filter + CI Postgres service |
| `v0.7.0` | full-stack | Phase 9 backend: player-centric surface + 4 new API endpoints + 7 new e2e tests |
| `v0.7.1` | `web` | Phase 9 web: player-centric UI + 5 new components + 13 new vitest cases |
| `v0.8.0` | full-stack | Account-level historical timelines + 5 new e2e tests + 11 new vitest cases |
| `v0.8.1` | `web` + `apps/api` | Per-day bucketing on the player timeline + critical 1970-01-01 sentinel fix |
| `v0.8.2` | `web` | Log scale Y-axis on the per-account timeline |
| `v0.8.3` | `web` + `apps/api` | Player name resolution on the fight drilldown's TargetFilter |
| `v0.8.4` | `apps/api` | Per-(fight, account) summary materialisation (5-30s → ms latency) |
| `v0.8.5` | `apps/api` | Backfill player summaries for pre-v0.8.4 fights |
| `v0.8.6` | `apps/api` | Operational health probe for fight-summary drift |
| `v0.8.7` | `apps/api` | Wire the v0.8.6 health probe into CI as a regression gate |
| `v0.8.8` | `web` + planning | Visual documentation in README + auto-codegen on `pnpm dev` + advisor audit |
| `v0.8.9` | `apps/api` + `web` | Per-account timeline `?tz=Continent/City` + per-fight timeline section |

See [CHANGELOG.md](./CHANGELOG.md) for the per-commit history.

<details>
<summary>Phase history (Phase 0 → v0.8.9)</summary>

### Phase 0 → v0.8.9

✅ **Phase 0** — Monorepo skeleton + tooling (`uv`, `ruff`, `mypy`) + boilerplate scaffolding.
✅ **Phase 1** — `gw2_evtc_parser` V1.3 binary layout parsing behind an `EvtcParser` Protocol. Tagged `v0.4.0-parser`.
✅ **Phase 2** — FastAPI gateway + Alembic migrations + MinIO content-addressed `.zevtc` blob storage + V1.3 `gw2_core` combat schemas. Env-driven credentials via `pydantic-settings` + `pytest-env`.
✅ **Phase 3** — `gw2_analytics` aggregations. `SingleFightAggregator` + `MultiFightAggregator` with strict frozen pydantic shapes + cross-field invariant validation. Tagged `v0.1.0-analytics-prototype` and `v0.2.0-analytics-prototype`.
✅ **Phase 4** — `web/` Next.js 16 frontend scaffolded. AG Grid Community tables (`FightsGrid`), `openapi-typescript` codegen, `pnpm typecheck` step in CI. Server Components SSR-fetch the gateway through an env-driven `src/lib/api.ts` helper.
✅ **Phase 5** — `GET /api/v1/account` Bearer-protected world enrichment. Tagged `v0.2.0-api`. The web/ side surfaced ``/upload``; tagged `v0.3.0-web`.
✅ **Phase 6** — Event-driven aggregations + CI-gate stability. `TargetDpsAggregator` + `EventWindowAggregator`. Tagged `v0.3.0`.
🔄 **Phase 7** — Parser-side V1.3 event-block consumer.
✅ **Phase 8** — `BuffRemovalEvent` end-to-end. Tagged `v0.6.0`. CI services block landed (Postgres on a fresh runner).
✅ **Phase 9 (v0.7.0 backend)** — Player-centric surface. Tagged `v0.7.0`. The web layer ships in v0.7.1.
✅ **Phase 9 of web (v0.7.1)** — Player-centric UI. Tagged `v0.7.1`.
✅ **Phase 9 of web (v0.8.0)** — Account-level historical timelines. Tagged `v0.8.0`.
✅ **Phase 9 of web (v0.8.1)** — Per-day bucketing on the player timeline. Tagged `v0.8.1`.
✅ **Phase 9 of web (v0.8.2)** — Log scale Y-axis on the per-account timeline. Tagged `v0.8.2`.
✅ **Phase 9 of web (v0.8.3)** — Player name resolution on the fight drilldown's TargetFilter. Tagged `v0.8.3`.
✅ **v0.8.4** — apps/api: per-(fight, account) summary materialisation.
✅ **v0.8.5** — apps/api: backfill player summaries for pre-v0.8.4 fights.
✅ **v0.8.6** — apps/api: operational health probe for fight-summary drift.
✅ **v0.8.7** — apps/api: wire the v0.8.6 health probe into CI as a regression gate.
✅ **v0.8.8** — `web` + planning: visual documentation in README + auto-codegen on `pnpm dev`.
✅ **v0.8.9** — `apps/api` + `web`: per-account timeline `?tz=Continent/City` + per-fight timeline section.

</details>

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for branch protection, pre-commit, code style, and test requirements.

### Principles

1. **`gw2_core` is the only contract** between layers. Everything depends on it; it depends on nothing but Pydantic.
2. **The parser is replaceable** behind the `EvtcParser` Protocol. Swap Python for Rust + PyO3 with zero churn elsewhere.
3. **The frontend never knows** about EVTC, parser internals, or DB schema — only the OpenAPI surface.
4. **Each component evolves independently** — enforced by `pyproject.toml` per lib.

## License

All rights reserved. License TBD.
