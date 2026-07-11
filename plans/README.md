# Advisor Plans Index

This directory holds the forward-looking advisor audits for the GW2Analytics
monorepo. Each audit is a senior-advisor survey (improve skill, `next`
invocation, `quick` effort) that scopes the next cycle's direction-only
candidates. The plans are self-contained implementation specs that a
different, less-context-aware executor can ship without further
clarification.

## v0.10.5 cycle (2026-07-10, c935acb)

**Scope:** Analytics accuracy / parser correctness cycle — condi/power split, arcdps_healing_stats sidecar, buff uptime model, EVTC revision helpers.

### Status

| Plan | Title | Files | Status | Tests |
|------|-------|-------|--------|-------|
| 135  | [135-v0105-condi-power-split](./135-v0105-condi-power-split.md) | `libs/gw2_analytics/src/gw2_analytics/condi_power_split.py` + `libs/gw2_analytics/tests/test_condi_power_split.py` + `apps/api/src/gw2analytics_api/services/player_summaries.py` + `apps/api/src/gw2analytics_api/routes/players.py` | **DONE** | 8 pass |
| 136  | [136-v0105-arcdps-healing-stats-sidecar](./136-v0105-arcdps-healing-stats-sidecar.md) | `libs/gw2_analytics/src/gw2_analytics/sidecar.py` NEW + `libs/gw2_analytics/tests/test_arcdps_sidecar.py` NEW | **DONE** | 10 pass |
| 137  | [137-v0105-buff-uptime-pydantic-model](./137-v0105-buff-uptime-pydantic-model.md) | `libs/gw2_analytics/src/gw2_analytics/buff_uptime.py` NEW + `buff_dispatch.py` NEW + tests NEW | **DONE** | 12 pass |
| 138  | [138-v0105-evtc-revision-helpers](./138-v0105-evtc-revision-helpers.md) | `libs/gw2_evtc_parser/src/gw2_evtc_parser/rev.py` NEW + `libs/gw2_evtc_parser/tests/test_rev.py` NEW | **DONE** | 11 pass |

**Total**: 4 plans, 13 NEW hermetic tests planned.

### Dependency graph

- **Plan 135** is standalone and DONE.
- **Plan 136** depends on Plan 137 (buff uptime Pydantic model — same merge target).
- **Plan 137** is standalone.
- **Plan 138** is parser-internal and standalone.

### Recommended execution order

1. **Plan 135** (condi/power split) — DONE.
2. **Plan 137** (buff uptime Pydantic model) — independent, unblocks Plan 136.
3. **Plan 136** (arcdps_healing_stats sidecar) — depends on Plan 137.
4. **Plan 138** (EVTC revision helpers) — independent parser work.

## v0.10.9+ audit (2026-07-11, f0249ef)

**Scope:** Full monorepo audit — 24 findings across correctness, security,
perf, tests, tech-debt, deps, DX, docs, direction.

**16 findings** already covered by existing plans (see
[AUDIT-2026-07-11-f0249ef.md](./AUDIT-2026-07-11-f0249ef.md) for the full
finding-to-plan mapping). **8 new plans** written to cover the remaining
findings:

| # | Plan | Path | Status | Effort |
|---|------|------|--------|--------|
| 018 | Route-level tests + `_persist_player_summaries` tests | [`../../advisor-plans/018-route-level-tests.md`](../advisor-plans/018-route-level-tests.md) | **DONE** (Plan 018) | M |
| 019 | Remove blanket `ignore_missing_imports` from mypy.ini | [`../../advisor-plans/019-mypy-strict-workspace.md`](../advisor-plans/019-mypy-strict-workspace.md) | **DONE** (Plan 019) | M |
| 020 | Supply-chain hardening (npmrc + react-dom version) | [`../../advisor-plans/020-supply-chain-hardening.md`](../advisor-plans/020-supply-chain-hardening.md) | **DONE** (Plan 020) | S |
| 021 | Split 3 god modules (services.py, api.ts, schemas.py) | [`../../advisor-plans/021-god-module-refactors.md`](../advisor-plans/021-god-module-refactors.md) | **DONE** (Plan 021) | M |
| 022 | DRY profession/elite wire-format helpers | [`../../advisor-plans/022-profession-elite-wire-format.md`](../advisor-plans/022-profession-elite-wire-format.md) | **DONE** (Plan 022) | S |
| 023 | Refresh stale docs (ROADMAP, README, statechange-ids, GraphQL) | [`../../advisor-plans/023-docs-refresh.md`](../advisor-plans/023-docs-refresh.md) | **DONE** (Plan 023) | S |
| 024 | Combat readout design/spike | [`../../advisor-plans/024-combat-readout-spike.md`](../advisor-plans/024-combat-readout-spike.md) | **DONE** | M |
| 025 | Webhook replay UI frontend | [`../../advisor-plans/025-replay-ui-frontend.md`](../advisor-plans/025-replay-ui-frontend.md) | **DONE** | M |

**Dependency graph:**
- 021 (god modules) depends on 019 (mypy catches refactor errors)
- 022 (wire format) depends on 019 (mypy catches signature mismatches)
- 024 (combat readout) benefits from 021 (cleaner services.py)
- 018, 020, 023, 025 are independent

**Recommended execution order:** 018 → 019 → 020 → 023 → 022 → 021 → 025 → 024

## Archive

52 plans moved to `plans/archive/` (stale, superseded, or orphan). See `plans/archive/` for full history.

## v0.9.38 audit (current)

> **Scope.** Surface coverage: `apps/api/src/gw2analytics_api/backfill.py` + `routes/{fights,account,players}.py`. The remaining routes (`webhooks.py`, `uploads.py`, `health.py`) were covered by v0.9.15 + v0.9.25 + v0.9.26; the backfill library + the 3 largest operational routes (`fights`, `account`, `players`) are the v0.9.x cycle's most-touched surfaces (each edited 5-10 times across the v0.8.x / v0.9.x release history).

### Status

| Plan | Title | Files | Status | Tests |
|------|-------|-------|--------|-------|
| 116  | `_EVENT_TYPE_ADAPTER` triplicate DRY consolidation across `backfill.py` + `routes/fights.py` + `routes/players.py` | `_event_dispatch.py` NEW + 3 route/backfill sites + 1 test file | **DONE** | 5 NEW |
| 117  | `routes/fights.py::get_fight_events` monolithic 200+ lines → extract per-target roll-up helper for DRY | `routes/fights.py` + 1 test file | **DONE** | 5 NEW |
| 118  | `backfill.py::run_backfill` exception tuple gap: `EOFError` from truncated gzipped blobs aborts the loop instead of counting as `failed: 1` | `backfill.py` + 1 test file | **DONE** | 5 NEW |

**Total**: 3 plans, 15 NEW hermetic tests.

### Dependency graph

- **Plan 116** (single-source-of-truth `TypeAdapter` + `iter_events_from_blob` helper) is standalone; touches 4 production source files (`_event_dispatch.py` NEW + 3 call sites) + 1 NEW test file.
- **Plan 117** (per-target roll-up helper) is standalone; touches 1 production source file + 1 NEW test file.
- **Plan 118** (backfill `EOFError` catch + comment-block dedup) is standalone BUT transitively surfaces the same `EOFError` catch gap that plan 116 closes for the routes-via-hub path — both plans address per-fight exception-tuple correctness in different surfaces. The 3 plans can ship concurrently as 3 separate PRs.
- **No plan depends on a v0.9.27..v0.9.37 plan being merged first**. The 3 plans are independent and PR-friendly.

### Cross-cutting patterns

- **DRY consolidation across 3 call sites** (plan 116) — matches the v0.9.x convention of "ONE canonical implementation + thin call-site fan-out". Previously documented in plan 037 + plan 095 + plan 113.
- **Per-target roll-up DRY** (plan 117) — `get_fight_events` is the canonical Phase 7 v1 + Phase 8 v0.8.0 + v0.8.3 endpoint; extracting the per-target trio to a helper cleans up 120 LoC of noise.
- **Per-fight exception-tuple completeness** (plan 118) — `EOFError` from truncated gzipped blobs is the canonical "blameless error" surface (the operator shouldn't see a stacktrace on a corrupted mid-upload blob); the existing 4-tuple `(S3Error, OSError, SQLAlchemyError, ValidationError)` misses `EOFError`.

### Rejected alternatives (this pass's pattern, condensed)

- **Three module-level `TypeAdapter(Event)` instances** (vs. plan 116's one) — 3× build-on-import cost + stale-instance risk. REJECTED.
- **`singledispatch` on the `Event` superclass** (vs. plan 117's `if/elif`) — closed-form dispatch table is more readable for 3 known targets. REJECTED.
- **Catch `Exception` broadly** (vs. plan 118's specific 5-tuple) — silently swallows `AttributeError` from future schema drift. REJECTED.

### Test inventory (cumulative v0.9.27..v0.9.38)

| Pass | NEW hermetic tests |
|------|--------------------|
| v0.9.27 | 16 |
| v0.9.28 | 14 |
| v0.9.29 | 16 |
| v0.9.30 | 18 |
| v0.9.31 | 16 |
| v0.9.32 | 12 |
| v0.9.33 | 14 |
| v0.9.34 | 13 |
| v0.9.35 | 10 |
| v0.9.36 | 14 |
| v0.9.37 | 15 |
| **v0.9.38** | **15** |
| **Total** | **173** |

### Style conventions

- All 3 plans mirror the `## Findings → ## Fix → ## Tests → ## Rejected alternatives → ## Dependency graph → ## Notes for executors` structure established in the v0.9.27..v0.9.37 plans.
- All 3 plans name the **real** audit finding (the line + the duplicated concept + the SOURCE comment if it documents the duplication).
- All 3 plans surface a **cross-cutting hook** to the v0.9.x cycle conventions (plan 116 → single-source-of-truth; plan 117 → thin route layer; plan 118 → blameless per-fight errors).
## v0.9.6 audit (deep audit libs+web)

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/* (the surfaces explicitly excluded from the v0.9.3 + v0.9.4 + v0.9.5 passes)
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.5 cleanup pass landed: 3 plans 017/018/019 written + indexed)
**Recon scope:** `libs/gw2_core/src/gw2_core/models.py` + `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` + `libs/gw2_analytics/src/gw2_analytics/*.py` (target_dps, target_healing, target_buff_removal, event_window, per_fight_timeline, player_profile, squad_rollup, skill_usage, multi_fight, aggregate) + `libs/gw2_api_client/src/gw2_api_client/client.py` + `web/src/lib/api.ts` + `web/src/components/*.tsx` + `web/src/app/**/*.tsx`
**Audit mode:** standard effort; full-scope deep pass on the previously-excluded surfaces; 6 HIGH-confidence findings selected for planning

### v0.9.6 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 020 | [020-v096-parser-zip-bomb-protection](./020-v096-parser-zip-bomb-protection.md) | **DONE** | #1 `_first_entry` calls `zf.read` with no uncompressed-size pre-check (security, HIGH) | S |
| 021 | [021-v096-per-fight-timeline-iterator-fix](./021-v096-per-fight-timeline-iterator-fix.md) | **DONE** | #2 `PerFightTimelineAggregator` drains the events iterator before `_check_invariants` (correctness, HIGH) | S |
| 022 | [022-v096-multi-fight-attendance-dedup](./022-v096-multi-fight-attendance-dedup.md) | **DONE** | #3 `MultiFightAggregator` double-counts reconnecting players (correctness, HIGH) | S |
| 023 | [023-v096-player-profile-dedup](./023-v096-player-profile-dedup.md) | **DONE** | #4 `PlayerProfileAggregator` drops damage for multi-character encounters (correctness, HIGH) | S |
| 024 | [024-v096-player-timeline-chart-utc-timezone](./024-v096-player-timeline-chart-utc-timezone.md) | **DONE** | #5 `PlayerTimelineChart` causes React hydration mismatch via `Intl.DateTimeFormat` without explicit `timeZone` (ux + correctness, HIGH) | S |
| 025 | [025-v096-window-size-selector-urlsearchparams](./025-v096-window-size-selector-urlsearchparams.md) | **DONE** | #6 `WindowSizeSelector` clobbers other URL query params on `window_s` change (ux, HIGH) | S |

### Recommended execution order (v0.9.6)

1. **Plan 020** (zip-bomb protection) — S effort, the security fix. Closes a DoS vector. Self-contained.
2. **Plan 024** + **Plan 025** (web UX fixes) — S effort each, the only 2 web-tier changes. Independent of the libs/* plans.
3. **Plan 021** + **Plan 022** + **Plan 023** (libs/* correctness fixes) — S effort each. Independent of each other; pick any order.

All 6 are independent. Could ship in any order. The recommended order is by tier (security → web UX → libs/* correctness) so a CI run picks up the most-impactful issues first.

### Considered and rejected (v0.9.6)

- **Bundle 021 + 022 + 023 into a single "libs/* correctness" plan**: tempting (all 3 are aggregator correctness fixes in `libs/gw2_analytics/`). The 3 plans are independent at the test fixture level (021 fixes an iterator drain; 022 fixes a per-fight dedup; 023 fixes a per-character dedup); bundling would conflate 3 separate invariants, making any one of them harder to revert if regressed in CI.
- **Plan 020 alternative: streaming zip extraction via `ZipFile.open(name)` + chunked read**: out of scope (the 500 MB bound is sufficient for realistic `.zevtc` files; streaming is a v0.9.7+ concern if the bound ever proves too tight).
- **Plan 021 alternative: cache the events list before the invariant check**: less surgical than passing pre-computed sums; same correctness outcome, more memory.
- **Plan 022 alternative: dedup at the `SingleFightAggregator` layer (per-fight rollup) instead of the multi-fight layer**: tempting (the per-fight aggregator already filters NPCs). The multi-fight layer is the correct place for cross-fight dedup; the per-fight layer doesn't have a "reconnect" concept.
- **Plan 023 alternative: surface `character_count` as a per-profile field**: out of scope (would require a schema change; this plan's minimal fix is the right v0.9.6 step).
- **Plan 024 alternative: lift `timeZone: "UTC"` to a `formatTimeZone: string` prop with default `"UTC"`**: out of scope (the prop would be unused; future plans can add a per-chart TZ preference if a user requests it).
- **Plan 025 alternative: DRY the `new URLSearchParams(searchParams.toString())` pattern into a `useFilteredQueryParam` hook**: tempting (the same pattern likely applies to `ProfessionFilter` + `TargetFilter` + `PlayerSearchBar`). Out of scope here; tracked as a v0.9.7+ plan after the 3 components are audited for the same bug.

## v0.9.5 audit (cleanup pass)

**Author:** senior-advisor audit (improve skill, standard effort) — v0.9.5 cleanup pass on the 3 lowest-leverage deferred v0.9.3 findings
**Stamped at:** `44ea862` (origin/main HEAD at audit time)
**Recon scope:** `apps/api/src/gw2analytics_api/schemas.py` + `apps/api/src/gw2analytics_api/services.py` + `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` + existing `apps/api/tests/`
**Audit mode:** standard effort; third pass on the 3 lowest-leverage v0.9.3 deferred findings (all 3 selected for planning as bounded cleanup)

### v0.9.5 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|| 017  | [017-v095-webhook-delivery-payload-shape](./017-v095-webhook-delivery-payload-shape.md) | **DONE** | #6 `WebhookDeliveryOut.payload` schema declares `dict` vs column is `bytes` (correctness, LOW) | S |
| 018 | [018-v095-filter-kind-validator](./018-v095-filter-kind-validator.md) | **DONE** (NEW `_WEBHOOK_KNOWN_KINDS` frozenset + `_validate_filter_kind` `field_validator` on `WebhookSubscriptionCreate.filter`; closes the dead-on-arrival subscription pattern (201 + secret + never-fires); 3 hermetic tests: known kind accepted, unknown kind 422, missing kind 422) | #7 `WebhookSubscriptionCreate.filter.kind` not validated at creation (correctness, LOW) | S || 019  | [019-v095-narrow-persist-event-blob-except](./019-v095-narrow-persist-event-blob-except.md) | **DONE** | #10 `_persist_event_blob except Exception` swallows programming bugs (correctness, LOW) | S |

### Recommended execution order (v0.9.5)

1. **Plan 017** (WebhookDeliveryOut payload shape) — S effort, the smallest. 1-line schema fix in `schemas.py`. Independent of 018/019.
2. **Plan 018** (filter.kind validator) — S effort, ~12-line `field_validator` addition. Independent.
3. **Plan 019** (narrow `_persist_event_blob` except) — S effort, 1-line `except` clause change + 1-2 import additions. Independent.

All 3 are independent. Could ship in any order. The recommended order is by file-locality (`schemas.py` for 017+018, then `services.py` for 019), but any order is fine.

### Considered and rejected (v0.9.5)

- **Bundle 017 + 018 into a single webhook-schemas-cleanup plan**: tempting (both touch `schemas.py`). The 2 plans are independent at the test fixture level (017 fixes a contract type; 018 adds a runtime validator); bundling would conflate the contract-fix invariant with the validator invariant, making them harder to revert if regressed in CI.
- **Plan 017 alternative: add a `payload_dict: dict[str, object] | None` field that hydrates from `payload` via `json.loads`**: out of scope (future feature, not cleanup). Documented as an escape hatch in plan 017.
- **Plan 018 alternative: per-key validation of `upload_status` / `fight_result`**: out of scope; the kind-membership check is the v0.9.5 minimum. Future plans can extend `_validate_filter_kind` into `_validate_filter` if the spec locks the contract.
- **Plan 019 alternative: catch + retry the MinIO PUT 3 times before degrading**: out of scope; the best-effort contract is documented; a future plan can add retry inside the try block. The narrowed catch stays narrow either way.

## v0.9.4 audit (perf+security second pass)

**Author:** senior-advisor audit (improve skill, standard effort) — second pass on the deferred v0.9.3 audit findings
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.3 close-out landed: 3 plans 010/011/012 written + indexed; the user requested a follow-up pass on the 7 deferred findings)
**Recon scope:** apps/api routes/* (player + fights + webhooks) + workers/webhook_scheduler.py + tests/test_players.py + tests/test_webhooks_e2e_scheduler.py + tests/test_uploads_e2e.py
**Audit mode:** standard effort; second pass on the 7 deferred v0.9.3 findings (top-4 by leverage selected for planning; 3 lowest-leverage explicitly deferred to v0.9.5)

### v0.9.4 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 013 | [013-v094-getaddrinfo-timeout](./013-v094-getaddrinfo-timeout.md) | **pending** (NEW module-level `_DNS_EXECUTOR` singleton + `_DNS_RESOLVE_TIMEOUT_S = 2.0` bounds the `getaddrinfo` call in `_resolved_address_is_blocked` via `concurrent.futures.ThreadPoolExecutor` + `.result(timeout=...)`; REJECTS `socket.setdefaulttimeout` (process-global state hazard — per thinker refinement); 3 new tests assert 422 within <0.5 s + no `setdefaulttimeout` mutation; refines the route-level error to use the shared `assert_url_safe_for_dispatch` from plan 010) | #4 `socket.getaddrinfo` in webhook URL validation has no timeout (security+perf, MED) | S |
| 014 | [014-v094-fight-blob-cache](./014-v094-fight-blob-cache.md) | **pending** (NEW `@functools.lru_cache(maxsize=8)` wraps `get_events(blob_uri)` in `routes/fights.py::_load_fight_events`; REJECTS `contextvars.ContextVar` (per-async-task only — does NOT cross requests, per thinker refinement); caches GZIPPED BYTES not parsed events (10x memory savings); 4 new tests assert 1 MinIO GET per `/fights/{id}` 4-endpoint visit, LRU eviction at 9th call, invalidation on new `blob_uri`) | #5 `_load_fight_events` re-downloads the events blob 4× per `/fights/{id}` visit (perf, MED) | S |
| 015 | [015-v094-player-routes-fastpath](./015-v094-player-routes-fastpath.md) | **pending** (refactor `_compute_contributions` to a single SQL `OrmFightPlayerSummary JOIN OrmFight` for `started_at`; drop the per-fight dispatch + the `selectinload(OrmFight.agents)` full-table pre-load; returns `(contributions, fight_id_to_started)` tuple; delete 3 orphan helpers (`_fast_path_fight_ids` + `_contributions_from_summary` + `_contributions_from_blob_walk`); 4 new tests: 3 regression + 1 perf at 1000 fights <100 ms) | #8 `list_players` + `get_player` + `get_player_timeline` all load ALL fights + agents (perf, LOW-MED) | M |
| 016 | [016-v094-webhook-scheduler-parallel](./016-v094-webhook-scheduler-parallel.md) | **pending** (NEW `_attempt_retry_independent` thread-safe worker opens its OWN session via `session_factory` — NEVER share across threads, per plan 012 escaping-by-thread rule; `concurrent.futures.ThreadPoolExecutor(max_workers=min(N, 4))` fans out retry rows; FIFO per-subscription invariant via the OS scheduler (small N=4 + sorted submission); accepts loss of "all N commit atomically"; 2 new tests: 4-retry parallel <0.75 s + per-delivery session isolation) | #9 `process_scheduled_retries` serialises retry POSTs (perf, LOW-MED) | S |

### Still deferred from v0.9.3 (NOT planned in this pass)

The 3 lowest-leverage findings from the original v0.9.3 audit are NOT planned in this pass. Tracked for future cycles:

| # | Finding | Why deferred | Suggested phase |
|---|---|---|---|
| #6 | `WebhookDeliveryOut.payload: dict[str, object]` schema vs `Mapped[bytes]` column (post-migration 0008) | Pre-emptive bug; no GET-deliveries route exposes the field today. 5-line schema type fix in `apps/api/src/gw2analytics_api/schemas.py`; trivial effort; impact 0 today + LOW future. | v0.9.5 cleanup |
| #7 | `WebhookSubscriptionCreate.filter` accepts any `dict[str, object]`; `filter.kind` not validated at creation; integrator can POST `{kind: "anything"}` and dispatcher silently ignores it | Confusing UX but no security impact; documented as the existing dispatcher behavior (`webhook_dispatch.py:178`). 10-line `field_validator` on `WebhookSubscriptionCreate.filter` adding kind-membership check + 422 for unknown kinds. | v0.9.5 cleanup |
| #10 | `_persist_event_blob`'s `except Exception` swallows programming bugs | Documented in `services.py` docstring as the canonical best-effort contract. 5-line narrowing of the catch to `(EvtcParseError, S3Error, OSError, TypeError)` would surface real bugs while keeping the best-effort contract. LOW impact; operator must monitor `logger.exception`. | v0.9.5 cleanup |

### Recommended execution order (v0.9.4)

1. **Plan 013** (getaddrinfo timeout) — S effort, the highest-leverage single fix. Closes the route-thread-starvation vector. Self-contained. Independent of 014/015/016.
2. **Plan 014** (fight blob cache) — S effort, the second perf+simplicity win. `lru_cache(maxsize=8)` is a 5-line change. Self-contained. Independent.
3. **Plan 015** (player routes fast-path) — M effort, the biggest perf refactor. Drops the full-table pre-load + 3 orphan helpers. Requires care for the `fight_id_to_started` tuple-return signature change.
4. **Plan 016** (parallel webhook retries) — S effort, the same pattern as plan 012. Self-contained. Independent.

There are NO inter-plan dependencies across 013-016. All 4 are independent and could ship in any order. The recommended order is by leverage (security > perf > perf > perf).

### Considered and rejected (v0.9.4)

- **Bundle 014 + 015 into one plan (player+fight read perf)**: tempting (both touch player/fight query paths). The two plans are independent at the test fixture level (014 caches the blob; 015 refactors the player query); bundling would conflate the blob-cache invariant with the SQL-refactor invariant, making them harder to revert if regressed.
- **Plan 013 alternative: switch the route to `async def` + `asyncio.wait_for`**: tempting (single-thread async is the canonical FastAPI pattern) but the route is sync; converting to async would force the entire `routes/webhooks.py` module to async. Out of scope per the v0.9.2 hardening posture (sync-FastAPI is the production contract).
- **Plan 014 alternative: `cachetools.LRUCache` instead of `functools.lru_cache`**: `cachetools` is an extra dep. The 5-line `lru_cache` is sufficient; strict maxsize + LRU semantics are already what `cachetools` would give.
- **Plan 015 alternative: keep `_contributions_from_blob_walk` for pre-v0.8.4 fights**: the v0.8.5 backfill + v0.8.6 health probe already ensure production is all post-v0.8.4. Keeping the fallback for 1 cycle (under `if False:`) is a safety net; full deletion in v0.9.5.
- **Plan 016 alternative: `asyncio.gather` + async SQLAlchemy**: same reasoning as plan 012 — the async-pivot is deferred to a future cycle.

## v0.9.3 audit (top-3 selected)

**Author:** senior-advisor audit (improve skill, standard effort) — top-3 by leverage selected by maintainer
**Stamped at:** `44ea862` (origin/main HEAD at audit time — after the v0.9.2 hardening cycle fully closed: 5 atomic commits per the `009 plan` + CHANGELOG `[0.9.2]` close-out + `d70c8c6` tagging deferred per the README `**Status:**` note).
**Recon scope:** README + CHANGELOG + plans/001-009 + apps/api routes/webhooks.py + workers/webhook_dispatch.py + workers/webhook_scheduler.py + config.py + main.py + databases.py + pyproject.toml + apps/api/tests/test_webhooks_e2e.py
**Audit mode:** standard effort (correctness + security + perf + DX focus); full-repo coverage of the apps/api critical path

### v0.9.3 status table

| # | Plan | Status | Addresses finding | Effort |
|---|---|---|---|---|
| 010 | [010-v093-ssrf-dispatch-re-resolve](./010-v093-ssrf-dispatch-re-resolve.md) | **pending** (NEW `apps/api/src/gw2analytics_api/_webhook_security.py` module houses `_resolved_address_kind` + `WebhookUrlBlockedError` + `assert_url_safe_for_dispatch`; call sites rewired in `webhook_dispatch.py::_dispatch_single` AND `webhook_scheduler.py::_attempt_retry` BEFORE the outbound POST; 3 new rebind regression tests in NEW `test_webhooks_e2e_resolve.py`; honors the existing `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS` opt-out; maintenance note flags the residual 1-50 ms TOCTOU window + the canonical network-level egress-filter defense (out of scope for this plan)) | #1 SSRF DNS rebind between create + dispatch (security, HIGH) — `_validate_webhook_url` ran ONCE at `POST /api/v1/webhooks`; dispatchers POST without re-resolving | S |
| 011 | [011-v093-cors-default-secure](./011-v093-cors-default-secure.md) | **pending** (NEW `Settings.env: Literal["dev", "staging", "production"]` field + `@model_validator(mode="after")` rejects `cors_allowed_origins == ["*"]` when `env != "dev"`; fail-fast `pydantic.ValidationError` at app startup with a clear remediation message; `[tool.pytest_env]` injects `ENV = "dev"` so existing tests stay green; 5 new config tests; `apps/api/.env.example` adds `ENV=production` + a comment block) | #2 `cors_allowed_origins` defaults to `["*"]` if `.env.example` copied verbatim + deployed without overrides (security, HIGH) | S |
| 012 | [012-v093-webhook-dispatch-parallel](./012-v093-webhook-dispatch-parallel.md) | **pending** (`concurrent.futures.ThreadPoolExecutor(max_workers=min(N_subs, 8))` fans out N=min(N, 8) concurrent sub-tasks; per-sub session opened INSIDE each worker via `session_factory` (sessions NOT thread-safe at psycopg driver level — per thinker refinement); plain dicts cross the thread boundary (NO ORM instances ever); 4 new parallel-dispatch tests in NEW `test_webhooks_dispatch_e2e.py`; accepts loss of "all N commit atomically" — each delivery row is independent; trades N×10 s worst-case wallclock for ≈10 s + a tiny startup tax) | #3 webhook dispatcher serialises N outbound POSTs (perf, MED) — `for sub in active_subs: _dispatch_single(...)` blocks 10 s per slow subscriber | M |

### Recommended execution order (v0.9.3)

1. **Plan 010** (SSRF DNS rebind on dispatch) — S effort, the highest-leverage single fix. Closes a CVSS-class SSRF hot path. Self-contained (1 NEW module + 3 test additions). Independent of 011 + 012.
2. **Plan 011** (CORS default secured) — S effort, the second security fix. Cross-field check via `@model_validator(mode="after")` (Pydantic v2 idiom; per the senior-advisor thinker refinement — `@field_validator` has no access to the *parsed* `env` field). Self-contained (1 new field + 1 validator + 5 tests + 1 .env addition). Independent.
3. **Plan 012** (webhook dispatch parallelised) — M effort, the perf improvement. ThreadPoolExecutor + per-thread session (CRITICAL: sessions NOT safe across threads; per the thinker refinement — open `with session_factory() as db:` INSIDE the worker). Self-contained (1 file refactor + 1 NEW test module + delete-orphan `_dispatch_single`). Independent.

There are NO inter-plan dependencies across 010/011/012. All 3 are independent and could ship in any order. The recommended order is by highest leverage (security > security > perf).

### Considered and rejected (v0.9.3)

- **Bundle 010 + 012 into one module**: tempting (both touch `_dispatch_single`). The two plans are independent at the test fixture level (010 adds a resolve-block check; 012 fans out the loop); bundling would conflate the SSRF-defense invariant with the perf invariant, making them harder to revert if regressed in CI. Keep separate.
- **Per-sub `httpx.AsyncClient` instead of `ThreadPoolExecutor`** in plan 012: would require migrating `session_factory` to async SQLAlchemy. Out of scope per the v0.9.2 hardening posture (sync-SQLA is the production contract); revisit when asyncpg lands.
- **Plan 010 alternative: pin to a specific pre-resolved IP via custom `httpx` transport** (`httpx.Client(transport=httpx.HTTPTransport(local_address=PinnedIP))`): airtight against TOCTOU but requires re-writing the entire dispatch's transport plumbing. The plan picks the simpler "re-resolve immediately before POST" + maintenance-note caveat because the airtight variant clobbers the existing 22-test contract.
- **Plan 011 alternative: separate `cors_safe_mode: bool` field**: redundant with the existing `env: Literal["dev", "staging", "production"]` discrimination. Adds a 2nd config dial where one already exists.
- **Plan 012 alternative: switch to `asyncio.gather` + async SQLAlchemy**: requires migrating `database.py`'s engine + the worker module. Defers the delivery perf win until a larger async-pivot cycle.

## v0.9.2 hardening (post v0.9.1 ship)

Stamped at `pre-d70c8c6` (origin/main HEAD at close-out time -- after the v0.9.1 hardening cycle fully closed: 5 audit plans + H1 + H2 followups shipped + the v0.9.2 close-out landed in 5 atomic commits per the [009 plan](./009-v092-webhook-rest.md)).

v0.9.2 was a hard-trigger follow-up surfaced by the v0.9.1 close-out:

| Trigger | Finding | Plan step that closes it |
|---|---|---|
| v0.9.1 deferred-3a | `test_replayed_delivery_byte_for_byte_hmac_matches_original` — JSONB intrinsic key reordering broke the HMAC byte-for-byte guarantee | Step 2 (wire `LargeBinary` through dispatch+scheduler+replay) |
| v0.9.1 deferred-3b | `test_replay_dlq_idempotent_concurrent_calls` — concurrent reads on `OrmWebhookDlq` create duplicate delivery rows | Step 3 (Postgres `SELECT ... FOR UPDATE` row-level lock on `replay_dlq_delivery`) |
| v0.9.1 close-out audit | No project-wide convention for path-parameter vs byte-only discriminator encoding (the urlsafe fix happened at one site; future discriminator sites could regress) | Step 4 (discriminator-encoding docstring convention) |
| v0.9.1 close-out audit | The full `apps/api/tests/` suite times out at >600s due to accumulated DB state across the 4 SLOW modules | Step 5 (central conftest.py fixtures, autouse cleanup of 6 tables) |
| Step 5 by-product | 2 pre-existing test failures (TZ-test contract mismatch; missing-fixture bug in plan-006 regression test) surfaced as the conftest fixed the accumulated-state hang | Followup commit `abd7deb` |

### v0.9.2 execution summary (5 atomic commits)

1. **`85716b6` — Step 1+2 (migration 0008 payload JSONB→LargeBinary + dispatch+scheduler+replay wiring)**: `apps/api/alembic/versions/0008_payload_bytes.py` (NEW) alters both `webhook_deliveries.payload` + `webhook_dlq.payload` from `JSONB` → `LargeBinary` (NOT data-preserving; documented as a v0.9.2 warning); `apps/api/src/gw2analytics_api/models.py` maps both columns to `Mapped[bytes]`; `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` writes `payload = json.dumps(body_dict, separators=(",", ":")).encode("utf-8")` (canonical bytes that the HMAC signs); `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` reads back the same bytes verbatim on retry (no dict round-trip, no JSONB re-ordering hazard); `apps/api/src/gw2analytics_api/routes/webhooks.py::replay_dlq_delivery` copies `dlq.payload` (bytes) into `new_delivery.payload` (bytes) directly.
2. **`99faa35` — Step 3 (row-level lock on `replay_dlq_delivery`)**: `apps/api/src/gw2analytics_api/routes/webhooks.py::replay_dlq_delivery` now opens the DLQ lookup with `db.execute(select(OrmWebhookDlq).where(OrmWebhookDlq.id == delivery_id).with_for_update()).scalar_one_or_none()` (Postgres `SELECT ... FOR UPDATE` row-level lock) instead of the legacy `db.get(OrmWebhookDlq, delivery_id)`. Exactly one of the concurrent threads reads + deletes the DLQ row; the second thread's transaction blocks until the first commits then sees NULL → 404.
3. **`a247430` — Step 5 (conftest.py central fixture cleanup)**: `apps/api/tests/conftest.py` (NEW) function-scoped autouse fixture `_isolate_test_state` bulk-deletes from 6 tables (uploads, fights, fight_player_summaries, webhook_subscriptions, webhook_deliveries, webhook_dlq) before each test; pre-Step-5 full suite hangs at >600s, post-Step-5 full suite runs in ~10s; removed the local autouse in `apps/api/tests/test_webhooks_e2e_scheduler.py` (now superseded by the broader conftest cleanup); `apps/api/tests/test_players.py::test_players_filter_with_pagination` now self-seeds 5 Mesmer records (the conftest wipes accumulated state, so the test must rebuild its own seed).
4. **`abd7deb` — Step 5 by-product (fix 2 pre-existing test failures)**: `apps/api/tests/test_uploads_e2e.py::test_player_timeline_tz_422_when_invalid_timezone` assertion fixed (route returns `detail` as a plain string, not a FastAPI-validation list-detail; new assertion handles both shapes via `str(body.get('detail', ''))`); `apps/api/tests/test_uploads_e2e.py::test_background_task_session_alive_at_invocation` (plan 006 regression test, 3 bugs): `probe = get_sessionmaker() → probe = get_sessionmaker()()` (double-call pattern); `assert resp.status_code == 202 → == 201` (correct REST semantics; the BG-task is implementation detail). Plus `apps/api/tests/conftest.py` gained 2 new pytest fixtures: `client` + `get_sessionmaker` (both consumed by the regression test's signature).
5. **`d70c8c6` — Step 4 (discriminator-encoding docstring convention)**: `apps/api/src/gw2analytics_api/routes/webhooks.py` gets 3 docstring additions (no code logic changes) on `_generate_subscription_id` (path-parameter convention), `_generate_secret` (byte-only convention), and `_generate_delivery_id` (UUID is URL-safe by definition). `CONTRIBUTING.md` gains a new `## Webhook discriminator IDs` section (cross-referenced from the 3 helper docstrings) with 3 bullet classifications + a classification guide for new discriminators.

### Outcomes

- Plan 009's 2 originally-deferred v0.9.1 test failures are now resolved (HMAC byte-for-byte across retries + concurrent replay idempotent).
- The full `apps/api/tests/` suite: **92 pass / 0 fail / 3 skip in ~10s** (was 90/1/2 in >600s pre-Step-5).
- Webhook e2e + scheduler: **22 pass / 0 fail / 1 skip** (unchanged from v0.9.1 close-out; the v0.9.2 followups are defect fixes, not new test coverage).
- The discriminator-encoding convention is now IDE-discoverable + CONTRIBUTING-documented for future discriminator sites.
- `apps/api` test count is unchanged (219 → 241 was the v0.9.1 delta; v0.9.2 adds zero new test cases since the pre-existing fixes are regression guards, not new tests).
- Migration 0008 is intentionally **NOT** data-preserving — pre-v0.9.2 rows become an opaque byte-bag (their dict structure is lost). Operators MUST either: (a) drain DLQ + deliveries before applying, OR (b) accept that pre-v0.9.2 rows lose their original dict. Documented in the migration's `# WARNING` header + the CHANGELOG `[0.9.2]` close-out note.

### Considered but not in v0.9.2 scope (deferred to v0.9.3+)

- **webhook secret-at-rest** (carried from v0.9.1 Deferred list): plaintext in PostgreSQL today; HMAC verification requires plaintext, so full hashing is impossible — pgcrypto envelope encryption with a `SECRETS_KEK` env var is the layered defence path. Deferred because v0.9.2 is feature-complete; tracking starts from the v0.9.1 close-out CHANGELOG.
- **migration 0008 reverse path** (data preservation on `alembic downgrade -1`): would require a v0.9.2 patch-release if any operator needs to roll back the upgrade. Listed as a future hardening item.

## Conventions for the executor

- The repo uses Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `style:`, `refactor:`).
- Python: `uv run <cmd>` from repo root or `cd apps/api && uv run <cmd>` — never `pip`.
- JS: `pnpm <cmd>` from `web/` or repo root (pnpm workspace).
- Validation: `uv run ruff check`, `uv run mypy --no-incremental libs apps`, `uv run pytest <path>`, `pnpm typecheck`, `pnpm test:unit`, `pnpm exec playwright test`.
- Commit-style: every commit has substance (no empty commits); every feature gets a doc sync in the same cycle (README + CHANGELOG).
- Code-reviewer pattern: spawn `code-reviewer-minimax-m3` for **every** non-trivial commit with concrete prompt (≤70 words + focus questions).
- Plan pattern: every plan is self-contained. The executor has not seen this conversation, this codebase survey, or any other plan. If a plan references "the pattern discussed above," it is broken.
## Archive

0 plans moved to `plans/archive/` (already-shipped cycles v0.7.x → v0.9.38; the canonical shipped history lives in `CHANGELOG.md`). The archive is read-only history: revive a plan by copy-and-modify INTO `plans/`, not by `git mv` reversing.

## Archive

52 plans moved to `plans/archive/` (stale, superseded, or orphan). See `plans/archive/` for full history.
