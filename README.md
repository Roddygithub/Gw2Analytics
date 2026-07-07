# GW2Analytics

[![CI](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/Roddygithub/Gw2Analytics/actions/workflows/ci.yml)

**Status:** 265 active tests across libs + apps + web (195 pytest cases in `libs/gw2_*` + `apps/api` + 70 vitest cases in `web/`; 1 conditionally skipped real-fixture integration test in `libs/gw2_evtc_parser/tests/test_parser.py::test_real_evtc_binary_parses_with_realistic_agent_count` requires the blob at `/tmp/inner_20251002-213519`) · 18 release tags shipped on the remote (latest: `v0.8.7`) · strict CI lint-and-test + pnpm typecheck + vitest gate active.

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
| `apps/api`                                     | FastAPI gateway v0.8.6. MinIO blobs + Alembic + Postgres. Endpoints: `POST /api/v1/uploads`, `GET /api/v1/uploads/{id}`, `GET /api/v1/fights[/{id}]`, `GET /api/v1/fights/{id}/events` (per-target DPS + HPS + BPS + per-bucket event windows, with the per-target roll-ups carrying an optional `name` field denormalised from `OrmFightAgent` since v0.8.3), `GET /api/v1/fights/{id}/squads` (v0.7.0), `GET /api/v1/fights/{id}/skills` (v0.7.0), `GET /api/v1/players` (v0.7.0), `GET /api/v1/players/{account_name:path}` (v0.7.0), `GET /api/v1/players/{account_name:path}/timeline?limit=20&offset=0&bucket=day` (v0.8.0, per-account historical timeline with recency-first sort; v0.8.1 adds `?bucket=day` for per-day bucketing), `GET /api/v1/health/summary` (v0.8.6, operational health probe for fight-summary drift: `total_fights` / `fights_with_summaries` / `drift_count` / `drift_pct` / `status` binary), `GET /api/v1/account`. The `/players` endpoints read materialised `OrmFightPlayerSummary` rows (v0.8.4) -- latency dropped from 5-30s to ms for v0.8.4+ fights; pre-v0.8.4 fights are auto-recovered via the v0.8.5 backfill CLI (`uv run python -m gw2analytics_api.scripts.backfill_player_summaries`). **Thin: serialises `gw2_core` + composes `gw2_api_client`.** |
| `web`                                          | Next.js 16 frontend. AG Grid Community tables (`FightsGrid`, `PlayersGrid`), GW2 API key resolve via `/account`, combat-log POST via `/upload` (multiform `POST /api/v1/uploads`). Server Components SSR-fetch the gateway. OpenAPI codegen via `pnpm generate:api`. The player-centric surface (`/players` + `/players/[account_name]`) + per-fight squad + skill roll-ups ship in v0.7.1. The per-account timeline (`PlayerTimelineChart` with Linear/Log toggle since v0.8.2 + Per fight/Per day toggle since v0.8.1) + the `TargetFilter` player-name resolution (v0.8.3) ship in v0.8.x. |

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
| `v0.8.0`                     | full-stack         | Phase 9 of web: account-level historical timelines. `GET /api/v1/players/{account_name:path}/timeline?limit=20&offset=0` backend endpoint (recency-first sort, limit [1, 100], offset [0, ∞)) + `PlayerTimelineChart` (inline SVG line chart, 3 series normalized to 0-100% of per-series max) + `PlayerTimelineLegend` (3 colour swatches) + `PlayerTimelineSection` (Client Component with "Load more" pagination) + 5 new e2e tests + 11 new vitest cases |
| `v0.8.1`                     | `web` + `apps/api` | Per-day bucketing on the player timeline. `?bucket=day` query param on `GET /api/v1/players/{account_name:path}/timeline` collapses fights sharing a calendar day into one point whose `started_at` is UTC midnight + totals are the SUM of the day's fights. The `PlayerTimelineChart` X-axis auto-detects the day-aligned timestamps (zero-prop -- the chart infers day-vs-fight from the data) and renders `MM/DD` instead of `MM/DD HH:MM`. The `PlayerTimelineSection` gains a "Per fight" / "Per day" toggle. **Bonus**: fixes a pre-existing critical bug where the `services.py` started_at guard was falling through to a 1970-01-01 sentinel epoch (the timeline showed every point stacked at the leftmost edge). 4 new e2e tests + 1 new vitest case |
| `v0.8.2`                     | `web`              | Log scale Y-axis on the per-account timeline. `PlayerTimelineChart.buildTimelineLayout` gains a `scale: "linear" \| "log"` parameter (default "linear"); in log mode, the Y-axis is shared across the 3 polylines (damage + healing + strip) calibrated to the tallest series, so a 1M-damage hit and a 50-strip hit are both visible on the same chart. Decade ticks (1, 10, 100, 1k, 10k, ...) with a `formatLogTick` helper (B-suffix for 1B+ values). `PlayerTimelineSection` gains a Linear/Log toggle with `localStorage` persistence (SSR-safe via mount-only `useEffect`). 4 new vitest cases |
| `v0.8.3`                     | `web` + `apps/api` | Player name resolution on the fight drilldown's TargetFilter. The arcdps char-name (from `OrmFightAgent.name`) is denormalised into every per-target roll-up row (`target_dps` + `target_healing` + `target_buff_removal` all gain an optional `name: str \| None` field) so the dropdown can show `"HealBrand (1001)"` instead of the raw `"1001"`. Cross-roll-up consistency invariant: the same `agent_id` resolves to the same name on all 3 roll-ups (single `name_map` powers the 3 aggregators). The `TargetFilter` Client Component gains an optional `targetNameMap` prop with a `formatTargetLabel` helper (backward compat: pre-v0.8.3 wire consumers without the map keep their bare-id labels). NPCs without a registered char-name surface as `name=null` on the wire and fall back to the bare id in the UI. 9 new analytics tests + 3 new e2e assertions + 3 new frontend tests |
| `v0.8.4`                     | `apps/api`         | Per-(fight, account) summary materialisation. New `OrmFightPlayerSummary` table + `OrmFightPlayerSummary` mapped model + `_persist_player_summaries` helper called from `process_parse` (best-effort `try/except SQLAlchemyError` -- a transient DB hiccup doesn't break the upload; the slow-path fallback serves the data). The `/players` endpoints read the materialised rows via a single SQL aggregation -- latency dropped from 5-30s to ms for v0.8.4+ fights. The pre-v0.8.4 slow path (`_compute_contributions`) is preserved as a backward-compat fallback for historical uploads. 1 new alembic migration (`0005_fight_player_summaries.py`) + 1 extended e2e test + 1 new e2e test |
| `v0.8.5`                     | `apps/api`         | Backfill player summaries for pre-v0.8.4 fights. New `backfill.py` library (`run_backfill(db, *, fight_id, limit, dry_run) -> (backfilled, skipped, failed)`) with single-SQL `NOT EXISTS` discovery + per-fight commit (tight failure isolation) + `(S3Error, OSError, SQLAlchemyError, ValidationError)` per-fight catch. New `scripts/backfill_player_summaries.py` CLI with `--limit` / `--dry-run` / `--fight-id` flags; exit code 1 on partial-success. New shared `_fixtures.py` extracted from `test_uploads_e2e.py` (~150 lines of duplication eliminated). 3 new e2e tests + 1 skipped |
| `v0.8.6`                     | `apps/api`         | Operational health probe for fight-summary drift. New `GET /api/v1/health/summary` endpoint + `summary_drift(db) -> SummaryDrift` library function (single SQL round-trip with 2 subqueries; `DISTINCT fight_id` is required because a single fight has multiple summary rows). Response: `total_fights` / `fights_with_summaries` / `drift_count` / `drift_pct` / `status: Literal["ok", "drift"]`. Unauthenticated by design (matches `/healthz` -- external monitoring systems typically don't carry credentials). Closes the operational observability gap: the v0.8.4 best-effort materialise + v0.8.5 per-fight catch both silently swallow errors, so an operator previously had no easy way to detect fast-path degradation. 3 new e2e tests |
| `v0.8.7`                     | `apps/api`         | Wire the v0.8.6 health probe into CI as a regression gate + 5 hermetic unit tests. New `gw2analytics_api.scripts.health_gate` module (moved from the top-level `apps/api/ci_health_gate.py` after the v0.8.7 follow-up commit -- the canonical location is alongside the existing v0.8.5 backfill CLI, and the move lets the pre-commit mypy hook resolve the import without any `mypy_path` work-around) with 2 CLI modes: `--save-baseline PATH` (capture pre-e2e probe to JSON) + `--check-delta PATH` (compare post-e2e probe to baseline; fail on `drift_count` delta >= `MAX_DRIFT_DELTA = 2`). In-process TestClient (no uvicorn boot, no port binding, < 1 s on a CI runner); `cast(SummaryDrift, ...)` for mypy-friendly typing; `Path.open()` for PEP-736. The v0.8.6 probe's strict-binary `status` field would false-positive on the e2e suite's deliberate drift (the `test_health_summary_surfaces_drift_after_summary_deletion` test deletes summary rows); the **delta check** is baseline-agnostic and catches a v0.8.4 materialise regression (+2 delta) without false-positiving the legitimate e2e drift (+1 delta). 3 new CI steps in `.github/workflows/ci.yml` (baseline BEFORE pytest, delta check AFTER pytest, cleanup with `if: always()`); the CI invocation is now `python -m gw2analytics_api.scripts.health_gate ...` (workspace install makes the module globally importable). 5 new hermetic unit tests in `apps/api/tests/test_ci_health_gate.py` (save baseline file, check-delta pass / fail / boundary, no-args debug mode) + `_make_drift` helper that pins the rounding formula. 3 code-reviewer rounds (142-144, 147) APPROVED |

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
✅ **Phase 9 of web (v0.8.0)** — Account-level historical timelines. New backend endpoint `GET /api/v1/players/{account_name:path}/timeline?limit=20&offset=0` (recency-first sort, limit [1, 100], offset [0, ∞), 404 on unknown player, 422 on out-of-range query params). The web layer adds `PlayerTimelineChart` (inline SVG line chart, 3 series normalized to 0-100% of per-series max so the smaller-magnitude strip line is visible alongside damage + healing; SVG-native `<title>` tooltip on the group surfaces the absolute values on hover) + `PlayerTimelineLegend` (3 colour swatches) + `PlayerTimelineSection` (Client Component owning the "Load more" pagination state). The `/players/[account_name]` page always renders the section (synthetic-empty `PlayerTimeline` on the 404 path) so the analyst sees the empty-state panel instead of a silent absence. 5 new e2e tests + 11 new vitest cases. Tagged `v0.8.0`.
✅ **Phase 9 of web (v0.8.1)** — Per-day bucketing on the player timeline. `?bucket=day` query param on the timeline endpoint collapses fights sharing a calendar day into one point whose `started_at` is UTC midnight and whose 3 totals are the SUM of the day's fights. The `PlayerTimelineChart` X-axis auto-detects the day-aligned timestamps (zero-prop: `time.getUTCHours() === 0 && ...`) and renders `MM/DD` instead of `MM/DD HH:MM`; the `PlayerTimelineSection` gains a "Per fight" / "Per day" toggle. **Bonus fix**: a critical pre-existing bug in `services.py` where the `started_at` guard was falling through to the 1970-01-01 sentinel epoch was discovered during the v0.8.1 wire-up and fixed (now unconditionally `datetime.now(UTC)` with a docstring that explains the trap so a future refactor doesn't reintroduce it). The v0.8.0 timeline previously showed every point stacked at the leftmost edge; the timeline is now usable. 4 new e2e tests + 1 new vitest case. Tagged `v0.8.1`.
✅ **Phase 9 of web (v0.8.2)** — Log scale Y-axis on the per-account timeline. `PlayerTimelineChart.buildTimelineLayout` gains a `scale: "linear" \| "log"` parameter (default "linear"); in log mode, the Y-axis is shared across the 3 polylines (damage + healing + strip) calibrated to the tallest series, so a 1M-damage hit and a 50-strip hit are both visible on the same chart (the original ROADMAP XS item: "Cas où damage = 1M dwarf strip = 50 reste illisible même après normalisation"). Decade ticks (1, 10, 100, 1k, 10k, ...) capped at 8 with a `formatLogTick` helper (0, 1, 10, 100, 1k, 1.5k, 1M, 1.5M, 1B). `PlayerTimelineSection` gains a Linear/Log toggle with `localStorage` persistence (SSR-safe via mount-only `useEffect` to avoid hydration mismatches). 4 new vitest cases. Tagged `v0.8.2`.
✅ **Phase 9 of web (v0.8.3)** — Player name resolution on the fight drilldown's TargetFilter. The arcdps char-name (from `OrmFightAgent.name`) is denormalised into every per-target roll-up row (`target_dps` + `target_healing` + `target_buff_removal` all gain an optional `name: str \| None` field via a single `name_map` built by the route and passed to all 3 aggregators) so the dropdown can show `"HealBrand (1001)"` instead of the raw `"1001"`. Closes the long-standing tech-debt item "Display player name in the TargetFilter dropdown (currently shows raw agent_ids)" documented since the v0.6.0 release. Cross-roll-up consistency invariant: the same `agent_id` resolves to the same name on all 3 roll-ups (a single `name_map` powers the 3 aggregators). NPCs without a registered char-name surface as `name=null` on the wire and fall back to the bare id in the UI. 9 new analytics tests + 3 new e2e assertions + 3 new frontend tests. Tagged `v0.8.3`.
✅ **v0.8.4** — apps/api: per-(fight, account) summary materialisation. New `OrmFightPlayerSummary` table + mapped model + `_persist_player_summaries` helper called from `process_parse` (best-effort `try/except SQLAlchemyError` -- a transient DB hiccup doesn't break the upload; the slow-path fallback serves the data on the read side). The `/players` endpoints (`GET /players`, `GET /players/{account_name:path}`, `GET /players/{account_name:path}/timeline`) now read the materialised rows via a single SQL aggregation -- latency dropped from 5-30s to ms for v0.8.4+ fights. The pre-v0.8.4 slow path (`_compute_contributions`) is preserved as a backward-compat fallback for historical uploads. 1 new alembic migration (`0005_fight_player_summaries.py`) + 1 extended e2e test + 1 new e2e test. Tagged `v0.8.4` (changelog-only, not yet on the remote).
✅ **v0.8.5** — apps/api: backfill player summaries for pre-v0.8.4 fights. New `backfill.py` library (`run_backfill(db, *, fight_id, limit, dry_run) -> (backfilled, skipped, failed)`) with single-SQL `NOT EXISTS` discovery + per-fight commit (tight failure isolation) + `(S3Error, OSError, SQLAlchemyError, ValidationError)` per-fight catch. New `scripts/backfill_player_summaries.py` CLI (`uv run python -m gw2analytics_api.scripts.backfill_player_summaries --limit 1000`) with `--limit` / `--dry-run` / `--fight-id` flags; exit code 1 on partial-success so cron / CI can detect + alert. New shared `_fixtures.py` extracted from `test_uploads_e2e.py` (~150 lines of duplication eliminated). 3 new e2e tests + 1 skipped. Tagged `v0.8.5` (changelog-only, not yet on the remote).
✅ **v0.8.6** — apps/api: operational health probe for fight-summary drift. New `GET /api/v1/health/summary` endpoint + `summary_drift(db) -> SummaryDrift` library function (single SQL round-trip with 2 subqueries; `DISTINCT fight_id` is required because a single fight has multiple summary rows). Response: `total_fights` / `fights_with_summaries` / `drift_count` / `drift_pct` / `status: Literal["ok", "drift"]`. Unauthenticated by design (matches `/healthz` -- external monitoring systems typically don't carry credentials, and the data is operational, not sensitive). Closes the operational observability gap: the v0.8.4 best-effort materialise + v0.8.5 per-fight catch both silently swallow errors, so an operator previously had no easy way to detect fast-path degradation. 3 new e2e tests. Tagged `v0.8.6` (changelog-only, not yet on the remote).
✅ **v0.8.7** — apps/api: wire the v0.8.6 health probe into CI as a regression gate + 5 hermetic unit tests. New `gw2analytics_api.scripts.health_gate` module (originally `apps/api/ci_health_gate.py` at the gate commit; moved into the `src/` tree in the v0.8.7 follow-up commit so the pre-commit mypy hook + the workspace install can resolve the import without any `mypy_path` work-around) with 2 CLI modes: `--save-baseline PATH` (capture pre-e2e probe to JSON) + `--check-delta PATH` (compare post-e2e probe to baseline; fail on `drift_count` delta >= `MAX_DRIFT_DELTA = 2`). In-process TestClient (no uvicorn boot, no port binding, < 1 s on a CI runner); `cast(SummaryDrift, ...)` for mypy-friendly typing; `Path.open()` for PEP-736. The v0.8.6 probe's strict-binary `status` field would false-positive on the e2e suite's deliberate drift (the `test_health_summary_surfaces_drift_after_summary_deletion` test deletes summary rows); the **delta check** is baseline-agnostic and catches a v0.8.4 materialise regression (+2 delta) without false-positiving the legitimate e2e drift (+1 delta). The off-by-one fix (`>=` vs `>`) is critical: with `>` and `MAX=2`, a single-fight regression would pass. 3 new CI steps in `.github/workflows/ci.yml` (baseline BEFORE pytest, delta check AFTER pytest, cleanup with `if: always()`); the CI invocation is now `python -m gw2analytics_api.scripts.health_gate ...` (workspace install makes the module globally importable). 5 new hermetic unit tests in `apps/api/tests/test_ci_health_gate.py` (the gate is now an automated regression check, not just a CI step): 5 cases covering `_save_baseline`, `_check_delta` (3 boundary tests: delta == MAX fails, delta == MAX-1 passes, zero delta passes), and `main` no-args debug. 3 code-reviewer rounds (142-144, 147) APPROVED + round 146 thinker recommendation that drove the script move. Tagged `v0.8.7` (changelog-only, not yet on the remote).

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
