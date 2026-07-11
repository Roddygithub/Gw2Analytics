# Roadmap

**Status:** Living document. Last refreshed during the v0.10.9+
audit cycle (2026-07-11).

This file is the **single source of truth** for "what's left to do" on
the project. It supersedes any ad-hoc "what's next" list in the README
or the CHANGELOG. It is meant to be edited at every release tag so
that the next session can pick up exactly where the previous one left
off.

---

## Current state (post v0.10.9+ audit cycle)

- **Latest shipped tag:** (v0.10.x — the CHANGELOG is the canonical ledger)
  (Phase 9 of web: per-account timeline `?tz=Continent/City`
  + per-fight timeline section on `/fights/[id]`).
- **Architecture:** `gw2_evtc_parser` → `gw2_core` → `gw2_analytics` →
  `apps/api` (FastAPI) + `gw2_api_client` (outbound) → `web` (Next.js
  16). Pure-Python parser, gated behind an `EvtcParser` Protocol so a
  Rust + PyO3 binding is a drop-in replacement (no churn elsewhere).

---

## 1. v1.0 candidates (designed, not yet implemented)

| Item | Source | Effort | Why now |
|---|---|---|---|
| **Skill build analyser** — parse the loadout from the EVTC header, show per-skill DPS contribution | `docs/v0.8.0-web-design.md` §6 | **M** | Builds on `SkillUsageTable` from v0.7.1. |
| **Real-time DPS meter** — WebSocket-based live DPS display during a parse in progress | `docs/v0.8.0-web-design.md` §6 | **XL** | Auth + reconnect + partial-parse handling. Own dedicated cycle. |
| **Combat readout (4 tables: Damage / Heal / Boons / Defense)** | `docs/v0.9.0-combat-readout-design.md` | **XL+** | The user spec from the brainstorming sessions. Blocked on the statechange parser + the skills DB. **Longest cycle, highest analyst value.** |

### 1.1 Items removed since v0.8.0 / v0.9.0 release cycle (for archival)

The following items previously listed in §1 have shipped and are now
documented in their respective CHANGELOG entries. Listed here once
so a future audit can confirm what was cleaned up; do not re-add.

- **Backend "webhooks" (foundational + API + single-attempt worker)** — shipped v0.9.0 close-out. 8 files: alembic migration `0006` (3 tables: `webhook_subscriptions` / `webhook_deliveries` / `webhook_dlq` per design doc §4) + 3 ORM classes (`OrmWebhookSubscription` with `filter_payload` Python attr shadowing the SQL `filter` column, `OrmWebhookDelivery` with NO ondelete cascade, `OrmWebhookDlq` with NO FK subscription_id for forensics) + 3 Pydantic schemas (`WebhookSubscriptionCreate` / `WebhookSubscriptionCreatedOut` with one-time secret / `WebhookSubscriptionOut` after the dead-`revoked_at`-field post-reviewer drop) + 4 endpoints under `/api/v1/webhooks` (POST → 201 / GET-list / GET-by-id / DELETE → 204 idempotent soft-delete) + workers module (`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`) with single-attempt HMAC-SHA256-signed dispatch + 11 e2e tests (`apps/api/tests/test_webhooks_e2e.py`, all ruff+mypy clean). The retry+DLQ+replay layer was deliberately deferred to v0.9.1 -- the v0.9.0 close-out ships enough for integrators to build against the API; the retry/DLQ replay-ui loop is the natural hardening slice.
  Original source: `docs/v0.8.0-backend-design.md` (full design doc shippable as-is). Effort estimate matched reality: M-effort vs the original L estimate (the v0.9.0 scope intentionally excluded the 3-attempt retry schedule + the DLQ replay endpoint to land the foundational layer in one cycle).
- **Cross-account comparison** — shipped v0.10.0
  (new route at `/players/compare` + `?accounts=` multi-select on the
  timeline endpoint). The effort matched the M estimate.
- **Per-day bucketing on the timeline** — shipped v0.8.1
  (`?bucket=day` on `GET /api/v1/players/{account_name:path}/timeline` +
  "Per fight" / "Per day" toggle on `PlayerTimelineSection`).
  Original source: `docs/v0.8.0-web-design.md` §7. Effort estimate
  matched reality: S-effort as predicted.

### 1.2 "Ready to implement" shortlist (post v0.8.9 / v0.9.0 close-out)

The 2 items above with a complete design doc. Any of these can be
started as soon as the maintainer gives the green light:

1. **Combat readout** — `docs/v0.9.0-combat-readout-design.md`.
   Note: blocked on statechange parser + skills DB; the §1 table
   marks this XL+ with the block reason explicit.
3. **Skill build analyser** — design doc on §6 of
   `docs/v0.8.0-web-design.md` (extracted from the §1 priorities
   table row, retained as the most-leverage M-effort web item).

The previous v0.8.0 list's third + fourth + fifth items (per-day
bucketing + fight_player_summaries materialisation + webhooks
backend) shipped in v0.8.1, v0.8.4, v0.9.0 respectively and are
no longer in the shortlist. The webhooks row's new "v0.9.1 retry +
DLQ + replay" scope is captured in the §1 table above.

---

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
- **PNG / SVG export of the timeline** (CSV is already covered
  by `CsvDownloadButton`).

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
