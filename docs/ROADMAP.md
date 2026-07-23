# Roadmap

**Status:** Living document. Last refreshed AT v0.14.2 cycle
close-out (2026-07-22) — Plan 173 COMPLETE (14 boon uptimes +
presence % + 14 outgoing boons in Combat Readout, grouped bar
columns, 2 hermetic backend tests, E2E mock server + Playwright test).

This file is the **single source of truth** for "what's left to do" on
the project. It supersedes any ad-hoc "what's next" list in the README
or the CHANGELOG. It is meant to be edited at every release tag so
that the next session can pick up exactly where the previous one left
off.

---## Current state (post-Plan-173 v0.14.2)

**Plan 173 COMPLETE** — 1 feature release, Combat Readout enriched with per-player boon uptimes, outgoing boons, and presence percentage. **WAVE-8** (v0.11.0→v0.11.4, 8/8 Event subclasses dispatched) was already complete prior.

| Subclass | Dispatch | Shipped |
|---|---|---|
| StunBreakEvent | byte 56 (statechange) | Tour 6 → v0.11.0 |
| BarrierEvent | byte 38 (statechange) | v0.11.0 |
| DeathEvent | byte 4 (statechange) | v0.11.0 |
| DownEvent | byte 5 (statechange) | v0.11.0 |
| CCEvent | byte 35 (BreakbarPercent) | v0.11.1 |
| BlockEvent | _result=3 (CBTR_BLOCK) | v0.11.0 parser.py |
| DodgeEvent | _result=4 (CBTR_EVADE) | v0.11.0 parser.py |
| InterruptEvent | _result=5 (CBTR_INTERRUPT) | v0.11.0 parser.py |
| ConditionRemoveEvent | buff_id→is_condition() | v0.11.4 aggregator |

**Skills DB catalog**: 4,610 skills from GW2 /v2/skills API,
eager-loaded in API lifespan.

**E2E verified** (2026-07-21, real WvW log): blocks=1, interrupts=2
populated from arcdps data through parser→aggregator→readout endpoint.

**Forward-blockers resolved**: Skills DB ✅, 8/8 dispatch ✅,
ConditionRemoveEvent ✅, buff ID lookup table ✅.

**Remaining**: Phase 6 v2 parser-stream (dps_power/condi split,
barrier_ps, time_downed_ms), F17 frontend verification with real data.

- **Latest tag:** v0.14.2
- **Test surface:** pytest ~500+ / vitest 391 / Playwright 28
- **Architecture:** gw2_evtc_parser → gw2_core → gw2_analytics →
  apps/api (FastAPI) + gw2_api_client → web (Next.js 16)
  + libs/gw2_skills (catalog) + libs/gw2_core/_buff_ids.py (buff ID lookup)

---

## 1. v1.0 candidates (designed, not yet implemented)

| Item | Source | Effort | Why now |
|---|---|---|---|
| ~~**Skill build analyser** — parse the loadout from the EVTC header, show per-skill DPS contribution~~ SHIPPED v0.10.22 | `docs/v0.8.0-web-design.md` §6 | **M** (matched) | Built on `SkillUsageTable` from v0.7.1. SHIPPED: see "v0.10.22 cycle shipts" entry below. |
| **Real-time DPS meter** — WebSocket-based live DPS display during a parse in progress | `docs/v0.8.0-web-design.md` §6 | **XL** | Auth + reconnect + partial-parse handling. Own dedicated cycle. |
| ~~**Combat readout (4 tables: Damage / Heal / Boons / Defense)**~~ PARTIAL-Wave-5-SCAFFOLD (dispatcher + route + 12-member union ships; remaining: parser Phase 6 v2 + Skills DB v0.11.0 + web AG Grid) | `docs/v0.9.0-combat-readout-design.md` | **XL+** (Wave 5 brought it from "0% shipped" to "library+route tagged") | The user spec from the brainstorming sessions. Wave 5 SCAFFOLD closes 2 of 6 forward-blockers + SCAFFOLD-unblocks 2 more (Phase 6 v2 parser + Skills DB); remaining: Phase 6 v2 parser-stream switch + Skills DB catalog full fill-out + Web AG Grid tables. **Longest cycle, highest analyst value.** |


> **v0.10.19 mimo-half cycle attempt**: 6 iterations on `conftest.py`'s `_disable_dotenv_for_tests` autouse fixture exhausted the signature-budget against pydantic-settings actual call style; 3 residual failures persisted out of the 11 K-cluster per `CHANGELOG [0.10.19]`. Forward-defer to v0.10.20 per `plans/AUDIT-2026-07-12-cd6e9ad.md` §2. NO production-code regression; bucket K = Test-Substrate Mismatch.
### 1.1 Historical cycle shipts (archival)

Shipped features are documented in CHANGELOG.md. Key milestones:

- **v0.9.0**: Webhooks backend (foundational + API + single-attempt worker)
- **v0.10.0**: Cross-account comparison
- **v0.10.13**: Event dispatch streaming, LRU cache, webhook DLQ replay
- **v0.10.14**: BFF Playwright e2e, fetchCached helper, ARQ CI gate
- **v0.10.15**: Exception narrowing, per-section error chips
- **v0.10.17**: Replay UI (F18), vitest specs, fetchCached isolation tests
- **v0.10.18**: Replay UI Playwright e2e, README parity sync
- **v0.10.22**: Skill build analyser (Tour 4)
- **v0.10.23-pre**: Wave 2-4 SCAFFOLD (9-member Event union, 4 per-player aggregators)
- **v0.11.0→v0.11.4**: WAVE-8 complete (8/8 dispatch, Skills DB, ConditionRemoveEvent)

### 1.2 Next deliverables (post-WAVE-8)

1. **F17 frontend verification** — rebuild Docker with v0.11.4, upload
   real WvW logs, verify SCAFFOLD-zero columns (deaths, dodges, blocks,
   interrupts, barrier_total, cleanses) populate correctly.
2. ~~**Phase 6 v2 parser-stream switch**~~ — SHIPPED v0.12.1-v0.12.4.
3. ~~**Combat readout frontend**~~ — SHIPPED v0.10.25-v0.14.2. The 4
   AG Grid Client Components now display live data with Plan 173
   enrichments (uptime grouped bars, outgoing boons, presence %).

## 2. Tech debt / performance (signaled in the CHANGELOG, never resolved)

| Item | Source | Effort | Impact |
|---|---|---|---|
| **Rust + PyO3 parser binding** | `CONTRIBUTING.md` ("anticipated but not in scope") | **XL** | The `EvtcParser` Protocol is already in place for the swap. Pure perf wins (10-100x). Long-term investment, not a v1.0 priority. |

### 2.1 Items removed since v0.8.0 / v0.8.9 release cycle (for archival)

The following items previously listed in §2 shipped or were
deliberately retired and are archival here for future audits; do
not re-add without a fresh "Why now" rationale (§5 anti-drift
notes).

**Shipped items (no re-add):**- **Backend "webhooks" (retry + DLQ + replay = v0.9.1)** — shipped v0.9.1 cycle. 7 file changes: alembic migration `0007_webhook_retry.py` (2 new columns on `webhook_deliveries`: `next_attempt_at` indexed for polling + `payload` JSONB for byte-for-byte HMAC fidelity) + `models.py` edit (2 columns appended to `OrmWebhookDelivery`) + `webhook_dispatch.py` edit (seeds `payload` + sets `next_attempt_at` on initial dispatch) + new `workers/webhook_scheduler.py` (~180 lines: polling worker with exponential backoff + atomic DLQ promotion + `asyncio.to_thread` for non-blocking DB + crash-resilient lifespan loop) + `routes/webhooks.py` edit (new `POST /dlq/{delivery_id}/replay` endpoint + `WebhookDeliveryReplayOut` schema + `WebhookDeliveryOut` schema + 3-case 404 logic) + `apps/api/src/gw2analytics_api/main.py` lifespan integration (5s poll interval) + `schemas.py` edit (2 new classes appended). Per design doc §5. Tests + secret-at-rest encryption are explicit v0.9.1.1 followups.


- **Materialise `fight_player_summaries` table** — shipped v0.8.4
  (new `OrmFightPlayerSummary` table + `_persist_player_summaries`
  helper + `_compute_contributions` slow-path fallback for
  pre-v0.8.4 fights). Latency dropped from 5-30s to ms.
- **Resolve player names in `TargetFilter`** — shipped v0.8.3
  (`name_map: dict[int, str | None] | None` parameter on the 3
  per-target aggregators; format `"HealBrand (1001)"` in the
  dropdown). Backward compatible — pre-v0.8.3 wire consumers without
  the map keep their bare-id labels.
- **Log scale on the `PlayerTimelineChart` Y-axis** — shipped v0.8.2
  (`scale: "linear" | "log"` parameter on `buildTimelineLayout`; the
  Linear/Log toggle persists in `localStorage`).
- **Redis service in `docker-compose.yml` (zombie)** — shipped
  v0.9.0 close-out. The unused `redis:7-alpine` service + the
  matching `REDIS_URL=redis://localhost:6379/0` from `.env.example`
  (root + `apps/api/.env.example`) + the Quickstart comment
  `# 4. Bring up the infra (Postgres + MinIO + Redis)` were all
  removed in one batch; `docker compose up -d` now brings up only
  Postgres + MinIO. Pre-flight grep across `apps/`, `libs/`, `web/`
  confirmed no functional consumer (`import redis`, no `Settings.redis_url`,
  no Redis URL in any `pyproject.toml`).
- **DST boundary tests for `?tz=` (v0.8.9 followup)** — shipped
  v0.9.0 close-out. Two e2e tests added to
  `apps/api/tests/test_uploads_e2e.py`:
  `test_player_timeline_tz_europe_paris_dst_spring_forward` +
  `test_player_timeline_tz_america_new_york_dst_fall_back`. Each seeds
  1 fight + pins `started_at` to a UTC instant that straddles the
  DST wall-clock boundary (EU 2024-03-31 01:30 UTC post-jump, US
  2024-11-03 06:30 UTC post-fall-back), asserts the day-bucketed
  point lands on the correct Paris / NY calendar day AND the
  local-midnight invariant holds (00:00:00 Paris / NY local at
  the day-bucketed point). Pairs with the 4 winter-only v0.8.9
  tests for full calendar coverage.
- **Visual regression baseline dimension drift** — shipped v0.9.0
  close-out (CHANGELOG `### Fixed (web e2e - VR hydration)`). The
  hydration sentinel `"stable-scroll"` + `waitForFunction` over
  scrollHeight > 900 / stable 500ms was restored in
  `web/scripts/screenshots.mjs` after commit `882edff`'s over-
  aggressive trim dropped the guard. Host-only
  `pnpm screenshots --persist` re-run is a separate work item that
  materialises the corrected 5 dynamic-page baselines at 1440×3196
  (post-hydration); not blocking v0.9.0 close-out (the code fix is
  shipped).

**Retired items (deliberately dropped per §5 anti-drift protocol):**

- **DRY refactor of `_compute_contributions`** — RETIRED during
  v0.9.0 close-out. The CHANGELOG v0.7.0 entry that introduced the
  `noqa: PLR0912` trade-off establishes the rationale that
  NEVERTHELESS argues against the split: "_compute_contributions
  is a single-pass walk over the heterogeneous event stream, so
  splitting it into smaller helpers would scatter the hot loop
  across multiple call sites without making it easier to reason
  about._" That trade-off survives post-v0.8.4 (the v0.8.4
  materialisation pushed the function to slow-path for pre-v0.8.4
  fights, but the single-pass semantic is unchanged -- splitting
  the body into helpers would risk duplicating the per-event branch
  logic across helpers without a corresponding legibility win).
  Per §4 "Re-estimate" + §5 "delete if >2 releases without a Why
  now update": the entry sat in the table for v0.7.0 through
  v0.9.0 (8+ releases) without a meaningful "Why now" justification
  beyond the original v0.7.0 conditional. The maintainer's reviewer
  (the v0.9.0 close-out audit) re-read the v0.7.0 trade-off rationale
  and concluded: do not refactor, drop the entry. Future readers
  who feel the urge to split this function: read the v0.7.0
  rationale first; the split is a regression risk, not an
  improvement.

---

## 3. Strategic items (v1.0+)

- **Multi-tenant scoping** on the webhooks + the gateway
  (single-tenant is the current assumption).
- **Mobile-first redesign** of `/fights/[id]` (desktop is the
  canonical analyst surface today).
- ~~**GraphQL subscription channel** (alternative to webhooks for
  live dashboards).~~ **DECIDED: not planned.** The webhook system
  (v0.9.1) covers push notifications via HMAC-signed HTTP callbacks.
  Any future GraphQL proposal must demonstrate a concrete user
  requirement that webhooks cannot satisfy. See `docs/adr/001-graphql-subscription-channel.md`.
- ~~**PNG / SVG export of the timeline**~~ **SHIPPED v0.15.1** (CSV
  is already covered by `CsvDownloadButton`). The v0.15.1 cycle added
  `📐 SVG` + `📸 PNG` buttons inside `TimelineMiniChart`; SVG is a
  direct ``XMLSerializer`` capture, PNG rasterises the same SVG onto a
  hidden ``<canvas>`` at 2x scale. No new dependency. See CHANGELOG
  ``[0.15.1]`` for the full diff + 3 vitest tests.

---

## 4. Update protocol

At each release tag (`v0.X.Y`):

1. Update the **"Current state"** section (test count, latest
   tag, any new ✅ in the README).
2. Walk §1-3 and **check off** any item that landed in the
   release (move to a "Shipped" subsection at the bottom or
   delete — your call, but the decision must be deliberate).
3. **Re-prioritise** §1 if a new candidate has emerged (e.g.
   a new design doc has been added under `docs/`).
4. **Re-estimate** the effort column if the code-reviewer
   surfaced a hidden cost.
5. Commit the update in the same release PR (or a follow-up
   `docs(roadmap): refresh after v0.X.Y` commit).

---

## 5. Anti-drift notes

- The "Effort" column is **relative** (XS / S / M / L / XL),
  not hours. Keep it coarse so the table stays scannable.
- The "Why now" column is the most valuable: it forces a
  justification for the priority. An item without a "why
  now" reason should be demoted or deleted.
- If a row has been in the table for >2 releases without
  progress AND without a "Why now" update, **delete it** —
  it's noise, not signal.
