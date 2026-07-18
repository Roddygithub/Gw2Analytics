# GW2Analytics

[![CI](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml)
[![Latest tag](https://img.shields.io/github/v/tag/Roddygithub/Gw2Analytics?sort=semver&label=latest)](https://github.com/Roddygithub/Gw2Analytics/tags)

**Modern combat analytics platform for Guild Wars 2 WvW (World vs World).**

> Independent third-party platform — no dps.report, no Elite Insights web.
> WvW combat logs (`.zevtc`) are parsed locally and stored in a stable
> internal model from which all analytics, API, and frontend derive.

## What's new in v0.10.28

- ⚡ **/fights/[id] page renders instantly** — the `/timeline/players` endpoint (10 s SSR blocker) now lazy-loads on the client after hydration via the new `LazyTabbedTimelineSection` component. The Aggregated tab still renders server-side; the Per-player tab streams in 0–10 s later without blocking the initial paint.
- 🛡️ **Duplicate fight uploads handled gracefully** — when 2 distinct uploads contain the same parsed fight, the duplicate now surfaces as `status='failed'` with the existing fight_id surfaced (`The content is already analyzed as fight <id>`) so operators can pivot to the prior successful parse via `/fights/{existing_id}`. The audit row is preserved (no DELETE).
- 🎨 **PlayerSearchBar hydration mismatch fixed** — migrated from inline `React.CSSProperties` objects to a CSS module; SSR + CSR now render identically (no more React hydration warnings on the global header search bar).
- ✅ **CI gate flipped green** — `ruff format` applied to 15 files + 10 `mypy` errors in `routes/fights/` resolved via `Sequence`/`Mapping` covariance swaps. `ruff check` + `mypy` + `tsc` all 0 errors.

See [CHANGELOG.md](./CHANGELOG.md) for the full per-commit history.

## Highlights

- 🎯 **Per-target / per-subgroup / per-skill roll-ups** on every fight — DPS, healing, and buff removals via stable pydantic aggregations with deterministic ordering + cross-field invariants.
- 📈 **Account-level historical timelines** — per-day / per-fight bucketing, linear / log Y-axis, and player-name resolution on the fight drilldown's TargetFilter.
- 🔌 **Webhook subscriptions** for parse-completion notifications — HMAC-SHA256 signed, 3-attempt retry + DLQ + replay, with SSRF block (HTTPS-only + universal private-IP gate).
- 🎭 **Heuristic role detection** — per-(fight, account) DPS / HEAL / STRIP / BOON / MIXED classification from the 3 magnitudes + spec/profession hint table.
- 📊 **Per-player timeline overlay** — one per-bucket series per player agent for multi-line chart overlays.
- 🎨 **GW2Mists-inspired frontend** — dark palette, sticky glass header, inline SVG logo, favicon, and Next.js `<Link>` navigation.
- ⚔️ **Combat-readout UI** — per-player Damage / Heal / Boons / Defense 4-table roll-up via `/fights/[id]?tab=readout`.
- 🧪 **Comprehensive multi-layer test suite** — `pytest` (libs + apps) + `vitest` (web components) + Playwright e2e (web flows), all gated and green on every PR.
- 🛡️ **Audit hardening** — Caddyfile HSTS/CSP, CI `pip-audit`/`pnpm-audit`, Next.js error boundaries, headers() defense-in-depth.
- 📦 **Pure monorepo** — `libs/gw2_core` (no I/O), `libs/gw2_evtc_parser` (replaceable Protocol), `libs/gw2_analytics` (frozen pydantic), `apps/api` (FastAPI), `web` (Next.js).

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
                                 web (Next.js)
```

| Component | Role |
| --- | --- |
| `libs/gw2_core` | Stable Pydantic models (combat + API). Single source of truth. **No I/O.** |
| `libs/gw2_evtc_parser` | Binary `.zevtc` parser behind an `EvtcParser` Protocol. V1.3 layout. |
| `libs/gw2_analytics` | Single-, multi-fight, and event-driven aggregations. Frozen pydantic shapes with deterministic ordering + cross-field invariants. |
| `libs/gw2_api_client` | Typed async httpx wrapper for the Guild Wars 2 REST API v2. |
| `apps/api` | FastAPI gateway. MinIO blobs + Alembic + Postgres. |
| `web` | Next.js frontend. AG Grid Community tables + SSR fetches. |

## API Surface

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/uploads` | Ingest a `.zevtc` log; returns 201 (parse runs in background). |
| `GET` | `/api/v1/uploads/{id}` | Upload metadata. |
| `GET` | `/api/v1/fights[/{id}]` | List fights (paginated) or fetch a single fight. |
| `GET` | `/api/v1/fights/{id}/events` | Per-target trio (DPS + healing + buff removal) + per-bucket event windows. |
| `GET` | `/api/v1/fights/{id}/squads` | Per-subgroup roll-up. |
| `GET` | `/api/v1/fights/{id}/skills` | Per-skill hit count + damage / heal / strip totals. |
| `GET` | `/api/v1/fights/{id}/readout` | Combat readout — per-player Damage / Heal / Boons / Defense 4-table roll-up. |
| `GET` | `/api/v1/fights/{id}/timeline?window_s=N` | Per-fight temporal view (3-series, `M:SS` relative time). |
| `GET` | `/api/v1/fights/{id}/timeline/players` | Per-player timeline overlay. |
| `GET` | `/api/v1/fights/{id}/players/{account}/skills` | Per-player skill roll-up + loadout. |
| `GET` | `/api/v1/players?profession=&limit=&offset=` | Cross-fight player roll-up (paginated). |
| `GET` | `/api/v1/players/{account_name:path}` | Player profile + per-fight breakdown. |
| `GET` | `/api/v1/players/{account_name:path}/timeline` | Account-level historical timeline. |
| `POST/GET/DELETE` | `/api/v1/webhooks[/{id}]` | Webhook subscription management (HTTPS-only URLs). |
| `GET` | `/api/v1/health/summary` | Operational drift probe. |
| `GET` | `/api/v1/healthz` | Liveness probe. |

## Screenshots

| Route | Capture |
| --- | --- |
| `/` | ![Landing](docs/screenshots/01-landing.png) |
| `/upload` | ![Upload flow](docs/screenshots/03-upload.png) |
| `/fights` | ![Fights grid](docs/screenshots/04-fights.png) |
| `/players` | ![Players grid](docs/screenshots/05-players.png) |
| `/players/[account_name]` | ![Player profile](docs/screenshots/06-player-profile-with-timeline.png) |
| `/fights/[id]?tab=replay` | ![Replay drilldown](docs/screenshots/08-fight-drilldown.png) |

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

# 8. Frontend
cd web
pnpm install
pnpm dev   # http://localhost:3000
```

## Development

```bash
# Run all backend checks (lint + typecheck + tests)
uv run ruff check libs apps
uv run pytest libs apps -q

# Run all frontend checks (typecheck + lint + tests)
cd web
pnpm typecheck && pnpm lint && pnpm test:unit
```

## Documentation

| File | Purpose |
| --- | --- |
| [CHANGELOG.md](./CHANGELOG.md) | Canonical per-commit history. |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Workflow conventions, branch protection rules, CI gates. |
| [docs/ROADMAP.md](./docs/ROADMAP.md) | Forward-looking candidates and technical-debt ledger. |
| [plans/README.md](./plans/README.md) | Senior-advisor audit trails and scoped cycle implementation plans. |

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for branch protection, pre-commit, code style, and test requirements.

### Principles

1. **`gw2_core` is the only contract** between layers. Everything depends on it; it depends on nothing but Pydantic.
2. **The parser is replaceable** behind the `EvtcParser` Protocol. Swap Python for Rust + PyO3 with zero churn elsewhere.
3. **The frontend never knows** about EVTC, parser internals, or DB schema — only the OpenAPI surface.
4. **Each component evolves independently** — enforced by `pyproject.toml` per lib.

## License

[MIT](LICENSE) — Copyright (c) 2024-2026 Roddy. See [`LICENSE`](./LICENSE) for the
full text. The project is independent third-party software — no affiliation
with ArenaNet or any Guild Wars 2 trademark holder. All Guild Wars 2 game
content references are nominative fair use under the GW2 content policy.
