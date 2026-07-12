# Roadmap

**Status:** Living document. Last refreshed AT v0.10.18.1 cycle
close-out (2026-07-13).

This file is the **single source of truth** for "what's left to do" on
the project. It supersedes any ad-hoc "what's next" list in the README
or the CHANGELOG. It is meant to be edited at every release tag so
that the next session can pick up exactly where the previous one left
off.

---

## Current state (post v0.10.18.1 cycle)

- **Latest shipped tag:** v0.10.17 (F18 Replay UI main scope + C1
  partial-pre-existing-test-fix-up + D4 fetchCached LRU isolation
  pin + D5 cross-component substrate pin per the v0.10.16 deferral
  brief's "Recommended v0.10.17 scope" section; 5 cycle deliverables
  D1-D5 + 2 close-out docs commits per the
  v0.10.17 cycle-end audit at
  `plans/AUDIT-2026-07-13-3b2e71f.md`. Plan 036 (pre-existing pytest
  + vitest fix-up) is **PARTIALLY closed**: 1 of 7 vitest failures
  closed via D3 (`window-size-selector.test.tsx` TDZ fix); 6 vitest
  + 2 pytest remain as O6 carry-forward to v0.10.18).
- **Architecture:** unchanged from v0.10.9+:
  `gw2_evtc_parser` → `gw2_core` → `gw2_analytics` →
  `apps/api` (FastAPI) + `gw2_api_client` (outbound) → `web`
  (Next.js 16). Pure-Python parser, gated behind an `EvtcParser`
  Protocol so a Rust + PyO3 binding is a drop-in replacement (no
  churn elsewhere).

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

**v0.10.13 cycle shipts** (release commit `fa67b15`).

- **Plan 027 — Event dispatch streaming `gzip.GzipFile`** — shipped
  v0.10.13. Replaces `gzip.decompress + splitlines` (which
  materialised the full 30 MB JSONL into memory) with a streaming
  `gzip.GzipFile(fileobj=io.BytesIO(gz_bytes))` wrapper. Bounded
  memory peak to the zlib-chunk buffer (~64 KB) regardless of blob
  size. Closes the pre-v0.10.13 OOM path on large WvW raid dumps.

- **Plan 028 — Event dispatch hub consolidation** — shipped v0.10.13.
  Single `EVENT_TYPE_ADAPTER: TypeAdapter[Event]` instance in
  `apps/api/src/gw2analytics_api/_event_dispatch.py` shared across
  `backfill.py` + `routes/fights.py` + `routes/players.py` (3
  previous duplicates). Closes the "3 adapters go stale" future risk.

- **Plan 029 — Per-fight blob `lru_cache(maxsize=8)`** — shipped
  v0.10.13 on `get_events(blob_uri)` in `routes/fights.py`. Closes
  the 4× MinIO GET waterfall on the `Promise.allSettled` drilldown
  page (was a prior-audit F2 finding).

- **Plan 012 — Webhook DLQ GET + replay route** — shipped v0.10.13.
  New `GET /api/v1/webhooks/dlq` (returns DLQ rows with
  `subscription_id` filter) + new `POST
  /api/v1/webhooks/dlq/{delivery_id}/replay` (creates fresh
  delivery + atomically deletes the DLQ row, with SELECT FOR UPDATE
  row-locking for concurrent-replay idempotency). UI in
  `web/src/components/WebhookDlqGrid.tsx`.

- **Plan 013 — Webhook DNS executor + 2.0 s timeout fence** —
  shipped v0.10.13. `_DNS_EXECUTOR` thread pool + 2.0 s
  `future.result(timeout)` fence closes the slow-DNS-resolver DoS
  hot path. v0.10.10 followup bumped `max_workers` from 1 to 32
  via `DNS_POOL_MAX_WORKERS`.

**v0.10.14 cycle shipts** (release commit `5d0d4d4`).

- **D1 — BFF Playwright e2e to CI green** — shipped v0.10.14.
  Rewrite `web/tests/e2e/account-bff.spec.ts` to use Playwright's
  `page.route` stubbing for the negative-path coverage. 5 cases
  exercise the BFF proxy + the validation envelope directly.

- **D2 — `fetchCached` helper for the per-fight drilldown page** —
  shipped v0.10.14. New `web/src/lib/fetchCached.ts` wraps the 5
  gateway calls in LRU (8 entries) + TTL (60 s) with in-flight
  dedup. Page uses Promise.allSettled to fire all 5 in parallel.
  Test suite in `web/tests/lib/fetchCached.test.ts` (6 cases).

- **D3 — Visual regression baseline refresh (threshold 1→1.5%)** —
  shipped v0.10.14. Refreshed 9 baseline PNGs at `docs/screenshots/`;
  `DIFF_THRESHOLD` raised from `0.01` to `0.015` to absorb the
 8-fixture font-rendering drift between the v0.10.9 baseline host
  and the v0.10.14 CI host.

- **D4 — ARQ-integration CI gate + port-1 defensive env** — shipped
  v0.10.14. New `arq-integration` job in `.github/workflows/ci.yml`
  brings up the arq worker against `docker compose up -d redis`, runs
  the `apps/api/tests/test_parser_worker.py` +
  `apps/api/tests/test_uploads_arq.py` suites. Port-1 defensive
  guard in `parser_settings.py` so a missing `REDIS_PORT` env
  surfaces a clear RuntimeError at startup, not a silent port 1
  bind.

**v0.10.15 cycle shipts** (release commit — see `plans/RELEASE-v0.10.15.md`).

- **Plan 032 — `except Exception` narrow in `main.py:113`** — shipped
  v0.10.15. Caught exception class narrowed from bare `Exception` to
  `(ConnectionError, OSError, TimeoutError)`. Other exception types
  (e.g. `AttributeError` from a typo'd `redis_settings`) now
  propagate, surfacing the real misconfiguration instead of masking
  it with a misleading "arq pool init failed" warning.

- **Plan 033 — `except Exception` narrow in `rotate_kek.py:104`** —
  shipped v0.10.15. Per-row catch narrowed to `(InvalidToken,
  UnicodeDecodeError, SQLAlchemyError)`. Closes the dev DX landmine
  of catching unrelated exception types.

- **Plan 034 — `?subscription_id=` collapse in `webhooks.py:294`** —
  shipped v0.10.15. Normalize empty query string to `None` so the
  typed contract `str | None` holds + tests can assert
  `subscription_id is None` on `?subscription_id=`.

- **Plan 035 — Per-section error chips in
  `web/src/app/fights/[id]/page.tsx`** — shipped v0.10.15. The
  `Promise.allSettled` pattern's silent partial-failure UX is
  replaced with per-section diagnostic chips on the squads / skills
  / timeline / playerTimeline grids. Events endpoint failure
  retains the page-level blocking-error banner.

**v0.10.17 cycle shipts** (release commit — see `plans/RELEASE-v0.10.17.md`).

- **D1 — Replay UI for `/fights/[id]` (F18 main scope)** — shipped
  v0.10.17. NEW `web/src/components/ReplayPlayer.tsx` (~600 LoC) is
  a Client Component with playback engine (play/pause + 1x/2x/4x/8x
  speed toggle + scrubber drag + auto-pause at last bucket) +
  per-bucket visualisation (3 horizontal sub-bars per bucket:
  damage / healing / strip) + locale-formatted totals + the
  speed-chip cluster with `aria-pressed` + current-bucket badge
  `B{i+1}` + empty-state messaging. NEW `web/src/lib/replayFetcher.ts`
  (~90 LoC) wraps `fetchCached` to fetch the per-fight timeline
  rollup at the page's resolved `window_s` (URL omits `?window_s=`
  when windowS=5; includes `?window_s=N` otherwise).
  `web/src/app/fights/[id]/page.tsx` MODIFIED to add the Replay tab
  to the tab strip; case-insensitive tab matching + wiring
  `fetchReplayTimeline` into the `Promise.allSettled` (6th parallel
  fetch). `web/src/components/PerFightTimelineChart.tsx` MODIFIED (1
  line) — `export` added to `formatSecondsLabel` so ReplayPlayer.tsx
  can reuse it.

- **D2 — `replay-player.test.tsx` vitest specs (13 cases)** — shipped
  v0.10.17. NEW `web/tests/components/replay-player.test.tsx` covers
  3 render chrome (scrubber `aria-valuemin`/`aria-valuemax`/
  `aria-valuenow` + speed chips `aria-pressed` + locale-formatted
  totals), 5 playback engine (Play click → setInterval fakes + speed
  toggle changes interval + Pause stops advancement + Reset pauses +
  auto-pause at last bucket), 2 scrubber + current bucket (drag
  updates currentIndex + badge `B{i+1}` highlights), 2 empty states
  (no timeline / no buckets), 1 initial state (Bucket 1 of N
  visible at mount). All `vi.advanceTimersByTime(N)` wrapped in
  `act(() => ...)` to neutralise React 18+ auto-batching flakiness.

- **D3 — `window-size-selector.test.tsx` vi.mock TDZ fix (pre-existing
  vitest failure closure)** — shipped v0.10.17. Closes 1 of the 7
  pre-existing vitest failures from the v0.10.14 release notes:
  `window-size-selector.test.tsx` had a TDZ error on the
  top-of-file `pushMock` + `searchParamsMock` constants when
  vitest hoists `vi.mock(...)` above them. Wraps both mocks in
  `vi.hoisted(() => ({ ... }))` so they initialise BEFORE the
  `vi.mock` calls run.

- **D4 — `fetchCached` LRU isolation test (deferred v0.10.16 D4
  hygiene pin)** — shipped v0.10.17. NEW `web/tests/lib/
  fetchCached-isolation.test.ts` pins all 5 promised-behaviors + 1
  concurrency case (TTL hit / TTL expiry / dedup / no-cache-on-error
  / LRU cap eviction at maxsize=8 / concurrent `Promise.all`).
  Without this test, a future `fetchCached` refactor could silently
  break the LRU bound + the TTL contract + the dedup contract
  without test detection. Anti-regression substrate for the v0.10.14
  D2 `fetchCached` helper.

- **D5 — `replay-substrate-integration.test.ts` cross-component
  substrate pin (v0.10.17 D5)** — shipped v0.10.17. NEW file pins
  the contract between `ReplayPlayer.tsx` (consumer) and
  `fetchCached.ts` (infrastructure) at the `fetchReplayTimeline`
  wrapper boundary. 6 sub-cases: URL omits `?window_s=` when
  windowS=5 / URL includes `?window_s=N` when windowS!==5 /
  `encodeURIComponent` defensiveness on fightId / invalid windowS
  rejection (0/-1/NaN) BEFORE the gateway call / `fetchCached` error
  propagation unmodified / LRU cache hit within 60s TTL. A future
  regression in EITHER ReplayPlayer.tsx OR fetchCached.ts would
  break this contract; D5 is the single test that catches
  regressions on EITHER side.

**v0.10.18 cycle shipts** (release commit — see `plans/RELEASE-v0.10.18.md`
+ cycle-end audit `plans/AUDIT-2026-07-20-1405720.md`).

- **D1 marker — D1 pre-closed by v0.10.17 D3** — shipped v0.10.18
  (commit `4610a10`). The v0.10.17 D3 mock-layer-swap commit
  `52fd60f` closed ALL 7 pre-existing vitest failures atomically
  (they shared ONE root cause: mocking the wrong module). The
  v0.10.18 cycle's diagnostic-first phase reconciles the audit's
  stale "1 of 7 closed" count into the true outcome (7 of 7
  closed). Zero-line `git commit --allow-empty` preserves the
  cycle's strict 4-commit topology.
- **D3 — Replay UI Playwright e2e spec (deferred from v0.10.17
  D2)** — shipped v0.10.18 (commit `53e1796`). NEW
  `web/tests/e2e/replay-ui.spec.ts` (~167 LoC, 4 cases: page tab
  strip renders + scrubber keyboard accessibility with `aria-valuenow`
  + B3 badge highlight + play/pause `aria-pressed` conservation
  without console errors + 1x/2x/4x/8x speed toggle). Exercises
  the existing `mock-server.mjs` inline `/timeline` stub (3 buckets
  of 5s window). Pre-Phase-8a defensive grep verified
  `web/src/app/fights/[id]/page.tsx:404` routes `?tab=replay` to
  the ReplayPlayer Client Component.
- **D4 — F16 README parity sync (audit M4 polish observation)** —
  shipped v0.10.18 (commit `1405720`). 1 row appended to the
  README's `## Screenshots` table referencing the v0.10.17 F18
  Replay UI tab path (`/fights/[id]?tab=replay`) + the reserved
  `docs/screenshots/08-fight-drilldown.png`. Targets the actual
  documentation gap (the UI tab path, NOT a phantom 9th HTTP route;
  the `## API surface` table already lists 15 entries including
  the underlying `/api/v1/fights/{id}/timeline?window_s=N`).
  Closes the M4 polish finding from the v0.10.17 cycle-end audit.

**O7 carry-forward to v0.10.18.1 cycle** — the 2 pre-existing pytest
failures in `apps/api/tests/test_uploads_e2e.py` (per the v0.10.14
release notes; stable through v0.10.15 + v0.10.16-deferred + v0.10.17
+ v0.10.18 partial-cycle). The 2 failures are PostgreSQL-fixture-gated
and require `docker compose up -d` to surface; v0.10.18 cycle is
`web/`-only by design, so the back-end-touching D2 ships as the
v0.10.18.1 followup cycle (the v0.10.18.1 brief will be authored
post-v0.10.18 close-out per the v0.10.17 / v0.10.18
anti-premature-cycle-rule).

### 1.2 "Ready to implement" shortlist (post v0.10.18.1 close-out)

The items below have a complete plan spec in `advisor-plans/` and
can ship any time the maintainer gives the green light:

1. **Combat readout** — `docs/v0.9.0-combat-readout-design.md`.
   Note: blocked on statechange parser + skills DB; the §1 table
   marks this XL+ with the block reason explicit.
2. **Skill build analyser** — design doc on §6 of
   `docs/v0.8.0-web-design.md` (~M effort).
3. **M8 (bucket K = Test-Substrate Mismatch) — 11 pytest
   failures in webhook/Arq/DNS tests** — NEW finding from the
   v0.10.18.1 diagnostic-first phase (the full-surface pytest
   run `uv run pytest apps/api/tests -rfE --tb=no --no-header -q`
   reported `11 failed, 286 passed, 2 skipped`). All 11 cluster
   on test-to-substrate mismatches (conftest isolation leaks +
   DNS `socket.getaddrinfo` monkeypatch breakage + Arq mock-pool
   parity) running on the live docker-compose stack. NOT
   production code regressions. Sub-categorised: K1 (Arq-
   Worker connectivity, 5) + K2 (IP-routing/SSRF gate semantics,
   4) + K3 (DNS-resolver-pool latency budget, 2). Forward-
   deferred to **v0.10.19 mimo-half PRIMARY scope**. The fix-up
   lands test-substrate corrections only (conftest isolation +
   DNS monkeypatch restoration + Arq mock-pool parity); NO
   production logic changes. Effort: M-L.


The previous v0.8.0 list's third + fourth + fifth items (per-day
bucketing + fight_player_summaries materialisation + webhooks
backend) shipped in v0.8.1, v0.8.4, v0.9.0 respectively and are
no longer in the shortlist. **F18 Replay UI is no longer listed in
§1 v1.0 candidates** — it shipped in v0.10.17 (D1 + D2 + D5) and
is now in §1.1 cycle shipts (see "v0.10.17 cycle shipts" above).

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
