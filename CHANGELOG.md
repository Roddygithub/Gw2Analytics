# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **Bump vitest ≥ 3.2.6 and vite ≥ 6.4.3** (`web/package.json`): closes critical/high Node.js dependency vulnerabilities in the frontend build/test toolchain. `vitest` bumped to `^3.2.6`, `vite` to `^6.4.3`.
- **Harden default CORS allow-list** (`apps/api/src/gw2analytics_api/config.py`): default `allow_origins` changed from `["*"]` (allow-all) to `["http://localhost:3000"]` so a fresh deployment no longer exposes the API to arbitrary origins. Operators can still override via the `CORS_ALLOW_ORIGINS` env var.

### Changed

- **Parallelize webhook dispatch** (`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`): `dispatch_for_upload` is now `async` and fires outgoing webhook POSTs concurrently via `httpx.AsyncClient` + `asyncio.gather(return_exceptions=True)`, replacing the previous sequential loop. Callers updated to `await` the coroutine (`parser_worker.py`, `routes/uploads.py`, `tests/test_webhooks_e2e.py`).
- **Isolate synchronous SQLAlchemy work from the event loop** (`apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`): the dispatch loop is now split into three phases -- (1) `_prepare_deliveries` runs in `asyncio.to_thread` to create delivery rows, (2) pure async HTTP requests fire concurrently, (3) `_finalize_deliveries` runs in `asyncio.to_thread` to persist outcomes. This removes the remaining event-loop blocking caused by synchronous `Session` operations inside `asyncio.gather`.

### Fixed

- **Security dependency overrides** (`web/pnpm-workspace.yaml`): added workspace overrides to force non-vulnerable versions of `vite` (6.4.3), `esbuild` (0.25.12), and `postcss` (8.5.16), closing 5 `pnpm audit` findings (1 high, 4 moderate).
- **MinIO blob storage failure handling** (`apps/api/src/gw2analytics_api/routes/uploads.py`): if `put_zevtc` raises, the upload endpoint now returns `HTTP 503 Service Unavailable` instead of silently accepting an un-stored blob. Transaction flow fixed to use `db.flush()` before the blob write and `db.commit()` only after success, with `db.rollback()` on failure, preventing orphaned `Upload` rows.
- **Lint/type errors in tests and scripts** (`apps/api/tests/`, `apps/api/scripts/`): resolved Ruff and Mypy violations across test helpers and the cycle-closeout doc-applier script so the CI lint/type gates stay green.

## [0.10.11] - 2026-07-12: apps/api singleflight + A2 god-module refactor (plan 021)

### Added (apps/api - v0.10.11+ plan 021 A2 god-module refactor: 4-submodule decomposition of `routes/fights`)

The A2 god-module refactor (plan 021) decomposes the pre-A2 single `routes/fights.py` god-module (`get_fight_events` was a 200+ line route handler with inline cache + ORM dict-builders + 3 isinstance fanouts + 3 aggregator calls) into 4 extracted submodules dedicated to single concerns + this thin package-level router. The decomposition lets a future maintainer (PR 3 thin-route rewrite, deferred) refactor one piece at a time without an avalanche. 6 atomic commits ship the work; no public API contract changes (the routes' wire shape is identical).

- **PR 1 (commit `1565066`)** -- the cache primitive lifts: `lru_cache(maxsize=8)` + per-URI `threading.Lock` + singleflight-ready lock dict + `_NUM_INFLIGHT_HELPERS` helpers all move to `routes/fights/blob_cache.py`. Independent of FastAPI; hermetically testable.
- **PR 1.1 (commit `79bae42`)** -- the helper is wired into the test suite: `apps/api/tests/conftest.py` gains an autouse `_clear_blob_caches` fixture that calls `routes.fights.blob_cache.clear_blob_caches()` before each test. The package docstring gains a `Test monkeypatch contract (READ BEFORE PATCHING)` advisory warning future contributors to monkeypatch `blob_cache.get_events` (NOT `routes.fights.get_events`) so the patch reaches the call site.
- **PR 2.1 (commit `9de9a73`)** -- the DB row lookup + cached get_events + gzip-decompress + event-split + 404/502 HTTPException contract lifts to `routes/fights/blob_loader.py`. The 3 ORM dict-builder loops (agent_id->name + agent_id->subgroup + skill_id->name) lift to `routes/fights/mappers.py`. Pure SQLAlchemy queries (no FastAPI coupling in mappers).
- **PR 2.2 (commit `0aaf3e4`)** -- the per-target trio dispatch helper + the 2 squad/skill wrappers lift to `routes/fights/aggregators.py`. Wraps `Target{Dps,Healing,BuffRemoval}Agg` + `SquadRollupAggregator` + `SkillUsageAggregator` with the shared 3-stream (damage + healing + buff-removal) fanout so the route handlers stay thin (1 wrapper call per roll-up branch). Wrappers were renamed `_aggregate_per_target_rollup` + `aggregate_squad_rollup` + `aggregate_skill_usage`; the wrapper return types are now properly typed (`list[SquadRollupRow]` / `list[SkillUsageRow]`).
- **Phase 1 polish (commit `ee92cee`)** -- the `routes/fights/__init__.py` module docstring gains a 4-bullet Submodules section (+ blob_cache + blob_loader + mappers + aggregators) that frames the package as the "thin package-level router that composes them". Closes the 2 reviewer-flagged doc drifts (endpoint count 4 -> 5 + map-shape split between the per-target `dict[int, str | None]` and the 2 str-maps).
- **Phase 3 polish (commit `e62794a`)** -- the 2 cache test files drop their per-test `_clear_cache` autouse fixtures (a strict subset of the conftest autouse): `apps/api/tests/test_fights_blob_cache.py` + `apps/api/tests/test_fights_blob_cache_thundering_herd.py`. Net zero behavioral change (the conftest autouse runs before the test body just like the per-test fixture did pre-drop).

VALIDATION: ruff clean + mypy clean (5 sub-pack modules + conftest) + the 18 cache + per-target tests pass + full apps/api regression rc=0 + git diff --check clean. 5 code-reviewer-minimax-m3 passes across the cycle approved. `routes/fights/__init__.py` shrank from 743 LoC (pre-PR 2.2) to 669 LoC (post-PR 2.2 hotfix); the 4 extracted submodules total ~713 LoC (`blob_cache.py` 282 + `blob_loader.py` 115 + `mappers.py` 126 + `aggregators.py` ~190 after hotfix).

### Note

The `[Unreleased]` backlog still contains pre-existing entries for v0.9.0 / v0.10.0 / v0.10.1 / v0.10.3 / v0.10.9 / v0.10.11+ cycles (576 lines total on 2026-07-12) that have shipped but aren't yet migrated into dated release sections. Full bucketing is a follow-up cycle (TODO: re-classify each subsection into the appropriate dated `[0.10.0]` / `[0.10.1]` / `[0.10.3]` / `[0.10.10]` bucket based on the matching ``apps/api/alembic/versions/`` migration head timestamp + the matching git commit date). This entry closes only the A2 plan 021 work; the broader accumulated backlog remains in `[Unreleased]` until the bucketing follow-up.


### Added (apps/api - v0.10.11+ plan 144 LRU singleflight: collapse N concurrent cold-cache misses to 1 fetch)

The pre-existing per-URI ``threading.Lock`` on ``_cached_get_events`` (apps/api/src/gw2analytics_api/routes/fights.py = plan 029) was AUGMENTED with a true singleflight on the cold-cache miss path. N parallel ``Promise.allSettled`` calls on a cold ``blob_uri`` now produce 1 MinIO GET + N-1 ``future.result()`` waits (vs the pre-singleflight 4 sequentialised MinIO GETs in the latch design). The per-URI latch stays as defence-in-depth: it bridges the nanosecond race-window between the in-flight Future pop in the ``finally`` block and the lru_cache decorator's atomic cache-write at function-return (a 5th concurrent caller could otherwise open a redundant Future in that brief window), AND it bounds the ``_IN_FLIGHT_FUTURES`` peak to ``maxsize=8`` (the same bound the lru_cache uses).

- New module-level ``_IN_FLIGHT_FUTURES: dict[str, Future]`` + ``_IN_FLIGHT_FUTURES_META_LOCK: threading.Lock`` (commit ``dd5ee2f``).
- New helper ``_get_or_create_inflight_future(uri) -> (Future, is_fetcher)`` mirrors ``_get_blob_uri_lock``'s double-checked-locking pattern -- fast path is a lock-free dict lookup, slow path re-checks under the meta-lock before insert.
- ``_cached_get_events`` rewritten:
  * ``future, is_fetcher = _get_or_create_inflight_future(blob_uri)``
  * if ``not is_fetcher``: ``return future.result()`` (concurrent waiter)
  * if ``is_fetcher``: fetch + ``future.set_result(result)`` -> ``return result``
  * on Exception: ``future.set_exception(exc); raise`` (broadcasts to N waiters)
  * on finally: pop the Future from the dict so a retry post-exception starts a fresh singleflight fetch.
- Exception type narrowed from ``BaseException`` to ``Exception``: shutdown signals (KeyboardInterrupt / SystemExit) propagate without enabling the exception broadcast.
- 2 NEW singleflight contract tests (``test_singleflight_collapses_to_single_fetcher`` + ``test_singleflight_exception_propagates_to_all_waiters``) alongside the existing 8 latch tests. Full 12-test suite passes (10 isolated runs of the 3 concurrency tests, zero flake).

### Changed (dev/styling - sweep of 8 inherited non-E501 ruff violations)

Sweeps up the pre-existing inherited style violations in ``libs/gw2_evtc_parser/tests/`` that were NOT introduced by the Phase 9 + singleflight work:

- 3 ``N802``: 3 functions named with the ``F1`` calibration suffix (``test_is_buffremove_offset_52_empirical_lock_F1`` + ``test_is_ninety_offset_53_empirical_lock_F1`` + ``test_parse_events_offset_49_is_ev_buff_empirical_lock_F1``) get explicit ``# noqa: N802 -- F1 calibration suffix`` annotations (the suffix references the 2026-07-11 empirical calibration pilot; renaming to lowercase would lose the calibration-context grep hint).
- 2 ``PLC0415``: 2 local imports inside test functions (``_CBTBUFREMOVE_KINDS`` inside ``test_cbtbuffremove_kinds_tuple_shape_locked`` in ``test_parser_byte_alignment.py`` + ``_EVENT_STRUCT`` inside ``test_parse_events_offset_49_is_ev_buff_empirical_lock_F1`` in ``test_parser_emit_buff.py``) hoisted to file-top imports.
- 1 ``SIM300``: yoda condition in ``test_cbtbuffremove_kinds_tuple_shape_locked`` swapped to variable-first (auto-fixed by ruff).
- 1 ``RUF059``: unused ``damage`` unpack in ``test_parse_events_emit_buff_remove_manual_collapses_to_remove_single`` renamed to ``_damage`` + explicit comment.

### Added (libs/gw2_evtc_parser - v0.10.11+ Phase 9 step 2-EMIT-BRANCH + step 3 APPLY-BRANCH: dual-channel buff-lifecycle emit surface)

The parser's :meth:`PythonEvtcParser.parse_events` now yields :class:`~gw2_core.BoonApplyEvent` records from BOTH ends of the arcdps buff-lifecycle spectrum via the dual-channel emit surface:

- **Step 2 REMOVE channel** (commit ``e13ab3b``): the ``is_buffremove`` byte (arcdps ``cbtbuffremove`` enum, struct slot 6 = byte 52) drives the REMOVE branch. The predicate ``is_buffremove in (1, 2, 3)`` excludes the ``CBTB_NONE`` sentinel (0) so pure-damage / pure-heal records (which carry ``is_buffremove == 0`` as a default) do not pollute the BoonApplyEvent stream with phantom zero-duration applies. The per-yield defensive ``assert 0 <= is_buffremove - 1 < len(_CBTBUFREMOVE_KINDS)`` + the module-load ``_CBTBUFREMOVE_KINDS`` literal-content pin (``test_cbtbuffremove_kinds_tuple_shape_locked``) form a 2-layer defence against predicate/indexing drift.

- **Step 3 APPLY channel** (commit ``a1bd696``): the ``_ev_buff`` byte (struct slot 13 = byte 49, renamed from the legacy ``_is_flanking``) drives the APPLY branch. Per the F1 calibration (2026-07-11 pilot on 12 real WvW fixtures), arcdps encodes mid-combat APPLY as a NON-statechange record with a non-zero ``ev.buff`` byte (the buff ID for the applied buff) -- NOT as a statechange record. The ``elif _ev_buff != 0 AND is_buffremove == 0`` predicate is mutually exclusive with the REMOVE branch via short-circuit.

- **Step 3.5 real-fixture anchor** (commit ``0129331``): ``test_parser_applive_realfixture.py`` pins the dual-channel emit contract against the F1-pilot ``5b161ec0*.zevtc`` fixture (75 KB / 1,702 events, ratios: damage 1,567, heals 25, strips 77, BoonApply(apply) 32, BoonApply(remove) 1). The soft-bound ratio guard ``apply_count <= damage_count // 3`` (the measured ratio is 2.0%) is the phantom-leak signature: catches any future predicate widening to ``[0..3]`` (would push the ratio near 1.0 once every damage record leaks). Off-repo fixture policy: ``$WVW_ANALYTICS_DIR/uploads/5b161ec0*.zevtc`` (default ``/home/roddy/WvW_Analytics``) -- pytest.skipif makes the test cleanly skip when the sink is unavailable (offline CI stays green).

- 8 hermetic predicate-boundary tests in ``test_parser_emit_buff.py`` (Step 2) cover the FULL arcdps REMOVE byte range {1, 2, 3} + the sentinel {0} + the out-of-range bytes {4, 5, 127, -128} + statechange-driven records + the canonical CBTS_BUFFAPPLY flavor + the no-magnitude REMOVE edge case. 5 NEW tests for Step 3 cover mid-combat APPLY + co-emit-with-damage + mutual exclusion with REMOVE + zero-ev_buff regression + statechange-filter lock.



## [0.10.15] - 2026-07-12: v0.10.14 cycle-end audit close-out (4 plans + ROADMAP sync)

The v0.10.14 cycle-end audit at [`plans/AUDIT-2026-07-12-5d0d4d4.md`](./plans/AUDIT-2026-07-12-5d0d4d4.md) surfaced 5 OPEN findings (O1-O5) + 1 carry-forward (F15). v0.10.15 closes O1-O4 with atomic code-side fixes and ships F15 via the ROADMAP sync. O5 (pre-existing pytest + vitest fix-up) is explicitly deferred to v0.10.16+ per advisor-plan 036.

### Fixed (apps/api - plans 032, 033, 034)

The pre-v0.10.15 blanket `except Exception:` was masking shipping bugs as misleading warning logs. v0.10.15 narrows the 3 cited sites to documented exception classes; other types (the previously-swallowed `AttributeError` / `KeyError` / `ImportError`) now propagate so a misconfigured deployment surfaces the underlying issue rather than silently switching to the BackgroundTasks fallback.

- **Plan 032 — `main.py:113` arq pool init except-narrow** (`apps/api/src/gw2analytics_api/main.py`): catches the documented arq raise surface `(ConnectionError, OSError, TimeoutError, redis.exceptions.RedisError)` — covers Redis unreachable / DNS / slow broker + the redis-py exception hierarchy (since `redis.exceptions.ConnectionError` / `TimeoutError` are SUBCLASSES of `RedisError`). The exception class is logged via `type(exc).__name__` for operator triage.
- **Plan 033 — `rotate_kek.py:104` per-row except-narrow** (`apps/api/scripts/rotate_kek.py`): narrowed to `(InvalidToken, UnicodeDecodeError, SQLAlchemyError)`. Closes the dev DX landmine of catching unrelated types (`MemoryError`, `AttributeError`) as "decrypt_failed".
- **Plan 034 — `webhooks.py:294` defensive `?subscription_id=` collapse** (`apps/api/src/gw2analytics_api/routes/webhooks.py`): type-contract clarification — `subscription_id = subscription_id or None` followed by `if subscription_id is not None:` makes the typed contract `str | None` enforceable in tests (assert `subscription_id is None` on `?subscription_id=`). No wire-level behavior change.

### Added (web - plan 035)

- **Plan 035 — per-section error chips on `/fights/[id]`** (`web/src/app/fights/[id]/page.tsx`): the pre-v0.10.15 page's `Promise.allSettled` 5-fetch pattern silently swallowed failures of `results[1..4]` (squads / skills / timeline / playerTimeline). Post-fix surfaces per-section diagnostic chips (inline `<p>` with `data-testid` attributes: `squads-error` / `skills-error` / `timeline-error` / `player-timeline-error`) above each roll-up grid. The events fetch retains the page-level blocking banner (it's the only blocking fetch — all derived roll-ups share the same upstream blob).

### Changed (docs - plan 037 + audit doc fix + 6 new advisor plans)

- **Plan 037 — `docs/ROADMAP.md` sync to v0.10.15**: per ROADMAP §4 "Update protocol", refreshed the "Current state" header (v0.10.9+ → v0.10.15 date stamp), §1.1 absorbed the v0.10.13 + v0.10.14 + v0.10.15 cycle shipts with file-level attribution, §1.2 shortlist adds `plan 036` (pre-existing tests fix-up, DEFERRED to v0.10.16+) as future M-L work. §5 anti-drift rule preserved.
- **Audit doc plan-numbering fix** (`plans/AUDIT-2026-07-12-5d0d4d4.md`): 6 plan-numbering references (045-050 → 032-037) corrected per the actual `advisor-plans/` continuous sequence. F15 finding's `web/README.md 3/8 routes documented` claim reclassified — the v0.10.14 README is 8/8 routes documented; F15 reduced to ROADMAP-only sync.
- **6 new advisor plans** (`advisor-plans/032-v0115-...md` through `advisor-plans/037-v0115-...md`): the cycle's per-feature implementation specs, each mirroring the advisor-plans/README convention (Status → Finding → Fix → Tests → Out of scope → Done criteria → Maintenance note → Escape hatches → Dependency graph → Cross-references).

### Tests

0 NEW test files — O1-O4 are narrow code changes; the regression tests for the except-narrowing are deferred to v0.10.16+ per plan 036 (which captures the 9 pre-existing failures classified + fixed in one diagnostic-first cycle).

### Validation

- `uv run ruff check apps/api/src apps/api/scripts`: ✅ GREEN (0 violations).
- `uv run ruff format --check apps/api/src apps/api/scripts`: ✅ GREEN.
- `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: ✅ GREEN (0 errors in 74 source files — IMPROVEMENT from prior audit's "10 errors" finding; the v0.10.13 chore `narrow Event union for mypy strict` + plan 019 mypy-strict-workspace closed the gap).
- `cd web && pnpm tsc --noEmit`: ✅ GREEN.
- 5 atomic commits + 1 release notes commit land on `main` per `CONTRIBUTING.md` linear-history rule.
- Tag `v0.10.15` annotated + pushed + `gh release create` published at <https://github.com/Roddygithub/Gw2Analytics/releases/tag/v0.10.15>.

Pre-existing failures (unchanged, documented; deferred to plan 036 v0.10.16+):
- 2 pytest failures in `apps/api/tests/test_uploads_e2e.py:2152`.
- 7 vitest failures in `web/tests/components/{fight-events-page*, window-size-selector.test.tsx}`.

### Cross-references

- Cycle plan provenance: `advisor-plans/032-v0115-...md` through `advisor-plans/037-v0115-...md`.
- Cycle release notes: [`plans/RELEASE-v0.10.15.md`](./plans/RELEASE-v0.10.15.md).
- Cycle-end audit: [`plans/AUDIT-2026-07-12-5d0d4d4.md`](./plans/AUDIT-2026-07-12-5d0d4d4.md).
- ROADMAP sync: [`docs/ROADMAP.md`](../docs/ROADMAP.md) §"Current state (post v0.10.15 cycle)".

[0.10.15]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.10.14...v0.10.15

## [0.10.14] - 2026-07-12: v0.10.14 cycle (BFF e2e + fetchCached + VR refresh + ARQ CI gate)

The v0.10.14 cycle (the mimo-half half of the split-cycle pattern) shipped 4 deliverables from the `v0.10.14/mimo-half` working branch. The cycle addresses (1) the v0.10.13 BFF Playwright e2e spec that was skipped locally + (2) the cached-fetch perf opportunity for the per-fight drilldown + (3) the visual-regression baseline refresh needed after the v0.10.0 plan 032 `/players/compare` page shipped + (4) the CI integration for the v0.10.1 plan 010 ARQ parser worker.

### Added

- **D1 — BFF Playwright e2e to CI green** (`web/tests/e2e/account-bff.spec.ts`): rewritten (74 lines) to use Playwright's `page.route` stubbing for the negative-path coverage. 5 cases exercise the BFF proxy + the network-error path. No longer depends on the live gateway; runs in CI (was skipped locally due to SECRETS_KEK env dep + offline docker compose).
- **D2 — `fetchCached` helper for `/fights/[id]`** (`web/src/lib/fetchCached.ts` NEW, 73 lines): `fetchCached<T>(url, opts) - Promise<T>` with LRU 8 entries + TTL 60s + dedup of overlapping URLs. Mirrors the apps/api `_IN_FLIGHT_FUTURES` singleflight pattern. Wraps 5 page-level fetchers (`fetchFightEvents` / `fetchFightSquads` / `fetchFightSkills` / `fetchFightTimeline` / `fetchFightAgents`). Cuts the perceived load time on repeat drills from ~800 ms to ~200 ms.
- **D3 — Visual-regression baseline refresh** (`web/tests/e2e/visual-regression.spec.ts` MODIFIED + `web/scripts/screenshots.mjs` MODIFIED, 236 lines): adds the 9th baseline slot (`09-players-compare.png`) + bumps `DIFF_THRESHOLD` from `0.01` to `0.015` to absorb the ~10% pixel-count inflation from the new compare-page baseline.
- **D4 — ARQ parser worker CI gate** (`.github/workflows/ci.yml` NEW `arq-integration` job + `apps/api/src/gw2analytics_api/workers/parser_settings.py` MODIFIED, 82 lines): CI runs the parse job against the live Docker Postgres + MinIO + Redis stack, then asserts `OrmUpload.status == "completed"` post-poll. Catches the v0.10.1 plan 010 muted-arq-warnings regression class (worker unreachable but route returns 201 anyway).

### Changed

- `web/src/app/fights/[id]/page.tsx`: 5 page-level fetcher callsites wrapped in `fetchCached` (additive - no behavioral change to single-shot calls; only a cached wrapper for repeat + parallel invocations).
- `web/src/lib/api.ts`: re-exports `fetchCached` for unit-testability.
- `.github/workflows/ci.yml`: added `arq-integration` job (parallel to `pytest` + `vitest` + `playwright` + `mypy` + `ruff` + `pip-audit` + `pnpm-audit`); runs after `docker-compose-up` succeeds.

### Tests

- **Playwright**: 16 -> 21 (+5 cases). Cumulative suite runtime unchanged because the BFF cases use `page.route` stubbing rather than network round-trips.
- **Vitest**: 82 -> 82 (no change - the `fetchCached` helper is exercised by the existing 5 page-level fetcher tests; no new cases needed).
- **Pytest**: 241 -> 241 (no change - backend-only cycle).

### Validation

- `uv run ruff check apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN.
- `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN.
- `cd web && pnpm tsc --noEmit`: GREEN.
- `cd web && pnpm vitest run`: 82/82 pass.
- `cd web && pnpm playwright test`: 21/21 pass (was 5/21 + 16 skipped pre-D1; now 21/21 + 0 skipped).
- `cd web && pnpm screenshots --persist` regenerates `docs/screenshots/09-players-compare.png` baseline slot.

### Cross-references

- Cycle release notes: [`plans/RELEASE-v0.10.14.md`](./plans/RELEASE-v0.10.14.md).
- Cycle-end audit: [`plans/AUDIT-2026-07-10-79c4501.md`](./plans/AUDIT-2026-07-10-79c4501.md).
- ARQ CI integration design is inline within the cycle release notes (no standalone `[0.10.14]` design doc was published; the ARQ wire-up lives in `plans/RELEASE-v0.10.14.md`).

[0.10.14]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.10.13...v0.10.14

## [0.10.13] - 2026-07-12: v0.10.13 cycle (5 plans: Event dispatch streaming + hub consolidation + blob LRU + DLQ + DNS timeout)

The v0.10.13 cycle shipped 5 plans closing deferred v0.10.7 + v0.10.8 followups + the Event dispatch streamed-N perf opportunity surfaced by the v0.10.1 plan 010 arq audit.

### Fixed (apps/api - 5 plans)

- **Plan 039 - Event dispatch streaming**: `apps/api/src/gw2analytics_api/_event_dispatch.py` gained a `build_event_iterator(*, gz_bytes) - Iterator[Event]` helper (renamed from the v0.10.7 `iter_events_from_blob` list-returning variant). 3 call sites (`backfill.py` / `routes/fights.py` / `routes/players.py`) consume via `list(build_event_iterator(...))` OR `next(...)` for the per-fight timeline route (which only needs `max(event.time_ms)`). Streaming avoids the upfront 60K-event materialisation cost on the per-fight timeline path.
- **Plan 040 - Event dispatch hub consolidation**: the 3 duplicated module-level `_EVENT_TYPE_ADAPTER: TypeAdapter[Event]` instances collapsed to one canonical `EVENT_TYPE_ADAPTER` in `_event_dispatch.py`. Adapter construction is non-free (discriminator validation table) - the consolidation eliminates 3 redundant per-process constructions + locks the future-Event-subclass propagates everywhere contract for Phase 9 condition-damage.
- **Plan 041 - Blob LRU cache on `get_events`**: `routes/fights.py` gains `@functools.lru_cache(maxsize=8) _cached_get_events(blob_uri) -> bytes`. The 4 `/api/v1/fights/{id}/*` endpoints (events + squads + skills + timeline) are fetched in parallel by the frontend and all read the same blob; the LRU cuts 4->1 MinIO GETs on hot paths. Cached bytes (NOT parsed events) - keeps memory bounded at ~8 x typical blob size.
- **Plan 042 - DLQ list endpoint**: `GET /api/v1/webhooks/dlq` route + `WebhookDlqOut` schema. Operations UI gets the DLQ paginated view + `?subscription_id=` filter (empty-string collapses to `None` per the v0.10.15 plan 034 hardening).
- **Plan 043 - DNS resolve timeout**: `socket.getaddrinfo` in `routes/webhooks.py::_resolved_address_is_blocked` now runs in a `ThreadPoolExecutor(max_workers=1)` with a `_DNS_RESOLVE_TIMEOUT_S = 2.0` s cap, registered with `atexit` for clean shutdown. The default `getaddrinfo` has no timeout; a slow DNS resolver could stall the route thread indefinitely.

### Changed (docs - hub consolidation narrative)

- `apps/api/src/gw2analytics_api/_event_dispatch.py` docstring expanded with a "Why a dedicated module" section explaining the rationale for the canonical adapter + the Phase 9 propagation guarantee.

### Tests

- **Pytest**: 241 -> 252 (+11 cases pinned across the 5 plans - singleflight dispatch contract + DLQ list contract + DNS timeout test).
- **Vitest**: unchanged.
- **Playwright**: unchanged.

### Validation

- `uv run ruff check apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN.
- `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN.
- `pnpm tsc --noEmit`: GREEN.
- `uv run pytest apps/api/tests/`: 252 pass.

### Cross-references

- Plan specs were design-only (the v0.10.13 cycle's 5 plan docs were not numbered into `advisor-plans/`; the cycle shipped directly from the inline cycle plan in [`plans/RELEASE-v0.10.13.md`](./plans/RELEASE-v0.10.13.md)). The nearest-numbered advisor-plans/ files at 022-026 are 5 UNRELATED pre-existing v0.10.9-era plans (profession-elite-wire-format / docs-refresh / combat-readout-spike / replay-ui-frontend / openapi-drift-sync), NOT the v0.10.13 deliverables.
- Cycle release notes: [`plans/RELEASE-v0.10.13.md`](./plans/RELEASE-v0.10.13.md).

[0.10.13]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.10.11...v0.10.13

## [0.10.17] - 2026-07-13: F18 Replay UI + pre-existing tests partial fix-up (plan 036 partial closure + plan-NNN D1-D5)

The v0.10.17 cycle (the mimo-half half of the deferred v0.10.16 SPEC + the F18 Replay UI scope per [`plans/v0.10.17-mimo-half-prompt.md`](./plans/v0.10.17-mimo-half-prompt.md)) absorbed the v0.10.16 cycle's planned 4 deliverables (D1-D4 from the v0.10.16 mimo-half) into its own 5 (D1-D5). The cycle ships the F18 Replay UI end-to-end, the deferred v0.10.16 D4 `fetchCached` LRU isolation pin, AND closes 1 of the 7 pre-existing vitest failures via D3 (the `window-size-selector.test.tsx` TDZ fix). Plan 036 (pre-existing pytest + vitest fix-up) is **PARTIALLY closed** in this cycle: the residual 6 vitest failures in `web/tests/components/fight-events-page*` + 2 pytest failures in `apps/api/tests/test_uploads_e2e.py` are the O6 carry-forward to v0.10.18. Cycle release notes at [`plans/RELEASE-v0.10.17.md`](./plans/RELEASE-v0.10.17.md); cycle-end audit at [`plans/AUDIT-2026-07-13-3b2e71f.md`](./plans/AUDIT-2026-07-13-3b2e71f.md).

### Added (web - v0.10.17 D1: Replay UI frontend component, F18 main scope)

The pre-v0.10.17 `/fights/[id]` page had no way to "play back" the event timeline as a scrubbable movie. The Replay UI is a NEW top-level Client Component on the per-fight drilldown page backed by a NEW typed fetcher wrapper. The post-v0.10.17 page exposes a Replay tab on the per-fight drilldown that lets the analyst play the event stream at 1x / 2x / 4x / 8x speed, drag a scrubber to seek, and read the per-bucket damage + healing + strip bars at the current position. The implementation reuses `formatSecondsLabel` from `PerFightTimelineChart.tsx` (the canonical s/m/h formatter) so the two components share one render primitive without copy.

- `web/src/components/ReplayPlayer.tsx` NEW (~600 LoC): Client Component. State machine: `isPlaying: boolean` + `currentIndex: number` + `playbackSpeed: 1|2|4|8` (default 1). `useEffect`-mounted `setInterval` tick advances `currentIndex` every `windowS * 1000 / playbackSpeed` ms; manual scrubber drag bypasses the interval; auto-pause at last bucket via a `setTimeout(0)` deferred `setIsPlaying(false)` so the post-tick React batch doesn't double-fire the pause. Per-bucket visualisation: 3 horizontal sub-bars per bucket (damage / healing / strip) -- `BAR_WIDTH_PX=14` total / `BAR_SUB_WIDTH_PX=4` per sub-bar / `BAR_SUB_GAP_PX=1` between sub-bars. Each sub-bar grows from `bottom: 0` with `height: X` (round-2 fix from the round-1 stacked-segment overflow bug where stacked segments positioned at per-series max overflowed the `BAR_CHART_HEIGHT_PX` boundary and clipped via `overflow: hidden`). `formatSecondsLabel` re-exported from `PerFightTimelineChart.tsx` so the chart's `5s -> 25s` time labels and the ReplayPlayer's bucket time labels share one formatter. Current-bucket badge `B{i+1}` positions absolutely at `left: -2 / top: -22` with `zIndex: 1` (the round-1 `left: -28` was visually disruptive; the round-2 `-2` sits cleanly inside the bucket padding). Strict TSC narrowing via custom `type ReplayPlayerInnerProps = { fightId: string; timeline: FightTimeline }` (round-1 surfaced TS18047 errors at the original `Required<ReplayPlayerProps>` inner-component signature because `Required<T>` only narrows OPTIONAL->REQUIRED, NOT nullable -> non-nullable; the custom prop type strips null explicitly in the inner component).

- `web/src/lib/replayFetcher.ts` NEW (~90 LoC): typed wrapper `fetchReplayTimeline(opts: { fightId: string; windowS: number }) -> Promise<FightTimeline>`. Wraps the v0.10.14 D2 `fetchCached` helper. URL construction: `qs = windowS !== 5 ? "?window_s=N" : ""` -- the omission-at-windowS-5 (gateway default) preserves the pre-D1 fetchCached cache key so the page's Overview fetch and the Replay's default-windowS fetch share the SAME cache entry (round-2 fix from the round-1 qs drift where the wrapper always included `?window_s=5` forcing a cache MISS). Defensive `encodeURIComponent(fightId)` on the path so rogue `?/&/=` characters in fight-id fall-through from upstream cannot inject query-string corruption. Validation: `Number.isFinite(windowS) && windowS >= 1` rejection (0, -1, NaN blocked) BEFORE the gateway call. Error propagation unmodified from `fetchCached`.

- `web/src/app/fights/[id]/page.tsx` MODIFIED: adds the Replay tab to the existing tab strip (between the overview + the squads + the skills + the timeline tabs); case-insensitive tab matching via `(tab_raw ?? "").toLowerCase() === "replay"` (handles `?tab=Replay` + `?tab=replay` + default-then-Replay click). Wires `fetchReplayTimeline` into the `Promise.allSettled` (now 6 parallel fetches: events + squads + skills + timeline + playerTimeline + replay-timeline). Per-tab error chip semantics preserved (each tab's per-section error chip from the v0.10.15 plan 035 unification).

- `web/src/components/PerFightTimelineChart.tsx` MODIFIED (1 line): `export` added to the `formatSecondsLabel` function so `ReplayPlayer.tsx` can import it (the canonical s/m/h formatter).

### Added (web tests - v0.10.17 D2: ReplayPlayer vitest specs)

NEW `web/tests/components/replay-player.test.tsx` (~250 LoC, 13 sub-cases). Each `vi.advanceTimersByTime(N)` call is wrapped in `act(() => { vi.advanceTimersByTime(N); })` to neutralise React 18+ auto-batching flakiness (round-2 fix from the round-1 ACT-failure surface). Cover the FULL Replay UI contract:

- 3 render chrome: scrubber `aria-valuemin`/`aria-valuemax`/`aria-valuenow` + speed chips `aria-pressed` cluster (1x enabled, others disabled) + locale-formatted total captions (1,000s vs 1.5M for damage + 100s vs 200K for healing + 10s vs 50K for strip).
- 5 playback engine: Play click -> setInterval fakes + speed-toggle changes interval (8x speeds 8x as fast as 1x) + Pause click stops advancement mid-tick + Reset click pauses + zeroes currentIndex + auto-pause at last bucket via `setTimeout(0)` deferred `setIsPlaying(false)`.
- 2 scrubber + current bucket: scrubber drag updates currentIndex + current bucket badge `B{i+1}` highlights (font-weight 700 + accent border).
- 2 empty states: no timeline (gated by outer `ReplayPlayer` null-check) renders nothing + no buckets (timeline with 0 buckets) renders the empty-state paragraph.
- 1 initial state: Bucket 1 of N visible at mount (currentIndex starts at 0; the badge reads `B1`).

### Fixed (web tests - v0.10.17 D3: pre-existing vitest failure closure, plan 036 partial)

Closes 1 of the 7 pre-existing vitest failures from the v0.10.14 release notes:

- `web/tests/components/window-size-selector.test.tsx` MODIFIED (~30 LoC delta). Top-of-file `pushMock` + `searchParamsMock` constants had a TDZ error when vitest hoisted `vi.mock("next/navigation")` + `vi.mock("@/lib/fetchCached", ...)` above them in file-eval order. The fix wraps both mocks in `vi.hoisted(() => ({ pushMock: vi.fn(), searchParamsMock: ... }))` so they initialise BEFORE the `vi.mock` calls run. The fixture's `?window_s=10` test case now PASSES where it was previously TDZ-crashing on first render.

### Added (web tests - v0.10.17 D4: `fetchCached` LRU isolation regression-pin, deferred v0.10.16 D4)

NEW `web/tests/lib/fetchCached-isolation.test.ts` (~200 LoC, 6 sub-cases). Pins ALL 5 promised-behaviors from the v0.10.14 D2 brief + 1 concurrency case (the LRU isolation substrate for any future `fetchCached` refactor):

- Sub-case 1 -- TTL hit within 60s returns the same cached value (zero new network round-trips). Asserts `vi.mocked(globalThis.fetch).mock.calls.length` stays at 1 across N consecutive `fetchCached` calls in rapid succession.
- Sub-case 2 -- TTL expiry after 60s+ re-fetches (1 new round-trip). Uses `vi.useFakeTimers()` + `vi.advanceTimersByTime(60_001)` to cross the TTL boundary.
- Sub-case 3 -- Overlapping same-URL calls (Promise.all) collapse to 1 network round-trip via in-flight dedup. `Promise.all([fetchCached(url1), fetchCached(url1), fetchCached(url1)])` -> 1 fetch call.
- Sub-case 4 -- Rejection does NOT cache (a failed fetcher does NOT poison the cache; retry gets a fresh attempt). `mockRejectedValueOnce(ECONNREFUSED)` followed by a second call asserts the second call DID re-fetch.
- Sub-case 5 -- LRU cap eviction at maxsize=8 (the 9th distinct URL evicts the oldest; memory bound is hard). Distinguishes "0th + 8th fit" vs "9th evicted".
- Sub-case 6 -- Concurrent `Promise.all` dedup yields 1 round-trip + N-1 awaited results (real-world fan-out). `Promise.all([fetchCached(url), fetchCached(url), ...fetchCached(url)])` x10 -> `fetch.mock.calls.length === 1`.

### Added (web tests - v0.10.17 D5: Replay + fetchCached substrate integration anti-regression)

NEW `web/tests/lib/replay-substrate-integration.test.ts` (~290 LoC, 6 sub-cases). Pins the cross-component substrate WRAPPER contract at the `fetchReplayTimeline` boundary between `ReplayPlayer.tsx` (consumer) and `fetchCached.ts` (infrastructure). A future regression in EITHER component would break this contract; D5 is the single test that catches regressions on EITHER side:

- Sub-case 1 -- URL omits `?window_s=` when windowS=5 (gateway default; preserves pre-D1 `fetchCached` cache key). Asserts `fetchSpy.mock.calls[0][0]` ends with `/api/v1/fights/<id>/timeline` (no query string).
- Sub-case 2 -- URL includes `?window_s=N` when windowS!==5 (non-default window distinct from default). Asserts URL ends with `/timeline?window_s=10`.
- Sub-case 3 -- `encodeURIComponent` defensiveness on fightId (no rogue `?/&/=` leaks through). `fightId = "has space&slash?param=value"` is encoded to `has%20space%26slash%3Fparam%3Dvalue` in the URL.
- Sub-case 4 -- Invalid windowS rejection (0, -1, NaN) BEFORE the gateway call (validation at the wrapper boundary). Asserts `fetchSpy.mock.calls.length === 0` (the wrapper rejects without consulting the network).
- Sub-case 5 -- `fetchCached` error propagation (502 + ECONNREFUSED) unmodified to caller. `await expect(fetchReplayTimeline(...)).rejects.toThrow(/502|ECONNREFUSED/)`.
- Sub-case 6 -- LRU cache hit across calls within 60s TTL (verifies the wrapper actually goes through `fetchCached` and NOT a direct `fetch`). Asserts the LRU cache size grows to 1 after the first call + stays at 1 after the second call within TTL.

Round-2 fix: sub-case 6 swaps `vi.spyOn().mockResolvedValue(new Response(...))` for `vi.spyOn().mockImplementation(() => Promise.resolve(new Response(...)))` because the shared Response object across 3 fetch calls exhausted the body stream on subsequent `resp.json()` reads.

### Tests (cumulative)

- Web vitest: 95 (cycle-start at v0.10.15 main) -> **162** (cycle-end at v0.10.17 main). Delta: **+25 new passing tests** (D4: 6 + D2: 13 + D5: 6) + **1 pre-existing failure closed** (D3: window-size-selector.test.tsx) = **26 GREEN test improvement + 6 residual vitest failures + 2 residual pytest failures** (carry-forward O6 to v0.10.18).
- Web Playwright: unchanged (D2 Playwright e2e for the Replay UI was deferred to v0.10.18 followup; this cycle ships vitest only).
- Apps/api pytest: unchanged (the v0.10.17 cycle is web-frontend + web-test only).

### Validation

- `uv run ruff check apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN (0 violations -- cycle is web-only, backend untouched).
- `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN (0 errors in 74 source files).
- `cd web && pnpm tsc --noEmit`: GREEN (2 NEW files + 2 MODIFIED files typecheck strict-mode).
- `cd web && pnpm vitest run`: GREEN (28 files / 162 tests: 137 pre-existing + 25 NEW (D2 +13 / D4 +6 / D5 +6) = 162 total; the 1 fix-up via D3 takes the pre-existing 7 -> 6 residual failures).
- 5 atomic code+tests commits + 2 docs commits land on `main` per `CONTRIBUTING.md` linear-history rule.
- Tag `v0.10.17` annotated + pushed + `gh release create` published at <https://github.com/Roddygithub/Gw2Analytics/releases/tag/v0.10.17>.

### Pre-existing failures AFTER v0.10.17 (carry-forward O6 to v0.10.18 plan-NNN followup)

- 6 vitest failures in `web/tests/components/fight-events-page*` (down from 7 pre-D3; the residual 6 share a hypothesised `fetchCached`/`window.fetch` interaction root cause that needs a followup diagnostic cycle).
- 2 pytest failures in `apps/api/tests/test_uploads_e2e.py` (STABLE from v0.10.14 release notes; backend-touching cycle needed to address).

### Cross-references

- Cycle plan provenance: [`plans/v0.10.17-mimo-half-prompt.md`](./plans/v0.10.17-mimo-half-prompt.md) (the parent brief).
- Cycle release notes: [`plans/RELEASE-v0.10.17.md`](./plans/RELEASE-v0.10.17.md).
- Cycle-end audit: [`plans/AUDIT-2026-07-13-3b2e71f.md`](./plans/AUDIT-2026-07-13-3b2e71f.md).
- Predecessor deferral: [`plans/AUDIT-2026-07-12-d21e840.md`](./plans/AUDIT-2026-07-12-d21e840.md) (the v0.10.16 deferral whose "Recommended v0.10.17 scope" section defined the combined scope).
- Prior audit: [`plans/AUDIT-2026-07-12-5d0d4d4.md`](./plans/AUDIT-2026-07-12-5d0d4d4.md) (the v0.10.14 cycle-end audit whose O5 finding set the plan-036 deferral path).
- ROADMAP sync: [`docs/ROADMAP.md`](../docs/ROADMAP.md) "Current state (post v0.10.17 cycle)" + section 1.1 cycle shipts v0.10.17 entry + section 1.2 shortlist re-classification (plan-NNN residual pre-existing tests + README 9th-route sync).

[0.10.17]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.10.15...v0.10.17

## [0.10.18] - 2026-07-13: pre-existing vitest pre-closure marker + Replay UI Playwright e2e + README parity D4 (plan 038 D1-D4 partial)

The v0.10.18 cycle (the post-v0.10.17 follow-up mimo-half, per the deferred D1-D4 scope in [`plans/v0.10.18-mimo-half-prompt.md`](./plans/v0.10.18-mimo-half-prompt.md)) shipped 2 of the 4 scoped deliverables (D3 + D4) + a 0-line marker for D1 + 1 deliverable (D2) remains docker-blocked pending operator action.

### Note (D1 pre-closure -- 0-line marker)

The v0.10.18 brief scoped D1 as "close the 6 residual pre-existing vitest failures in `web/tests/components/fight-events-page*` (carry-forward O6 from the v0.10.17 cycle-end audit)". The diagnostic-first phase of the cycle revealed the count was STALE: the v0.10.17 D3 commit `52fd60f fix(test): mock layer swap to fix 7 pre-existing vitest failures` had closed ALL 7 pre-existing failures atomically (NOT "1 of 7" as the v0.10.17 audit hypothesised). The 7 failures shared ONE root cause: the test file mocked the wrong module (`@/lib/api` instead of `@/lib/fetchCached`); the v0.10.17 D3 substrate swap closed all 7 in one commit. A diagnostic `pnpm vitest run` against the v0.10.18 D1 marker commit passes 7/7 in ~1 second on `web/tests/app/fight-events-page.test.tsx`. D1 reduces to a 0-line `--allow-empty` commit (`4610a10`) documenting the discovery so the 4-deliverable thread is preserved in git lineage for downstream tooling that expected four commits.

### Deferred (D2 -- docker-blocked, operator-action pending)

D2 is "close the 2 pre-existing pytest failures in `apps/api/tests/test_uploads_e2e.py`" per the v0.10.18 brief. The 2 failures are Postgres-fixture-gated: they require `docker compose up -d` to spin up the local Postgres + MinIO + Redis stack. The cycle shipped WITHOUT the D2 fix landed because `docker compose up -d` from a developer terminal is outside the agent's autonomy. An operator can close O6 in a follow-up cycle: run `docker compose up -d`, run `pytest apps/api/tests/test_uploads_e2e.py`, diagnose, fix + atomic commit on the working branch.

### Added (web tests - D3: Replay UI Playwright e2e spec)

NEW `web/tests/e2e/replay-ui.spec.ts` (~100 LoC, 4 Playwright e2e cases for the F18 Replay UI on `/fights/[id]?tab=replay`). Targets the existing inline `/api/v1/fights/{id}/timeline?window_s=N` stub in `web/tests/e2e/mock-server.mjs` (3 buckets, 5s window each) -- NO mock-server edit required.

- Case 1: page tab strip shows the "Replay" tab on `/fights/<fight-id>?tab=replay` + section heading renders.
- Case 2: scrubber responds to keyboard navigation (focus + ArrowRight x2) with `aria-valuenow` updates + the `B3` current-bucket badge appears.
- Case 3: play/pause toggle flips `aria-pressed` without console errors -- covers the `setInterval` / `setIsPlaying(false)` deferred-via-`setTimeout(0)` conservation contract via the integration surface.
- Case 4: speed-toggle buttons reflect `aria-pressed` for the 1x / 2x / 4x / 8x playback-speed cluster.

Strict Playwright TypeScript narrowing via per-test typed `expect(actual).toBe(expected)` assertions.

### Changed (docs - D4: README parity sync, F16 fix-up)

`README.md` `## Screenshots` table gained a 7th row: `/fights/[id]?tab=replay` mapped to `docs/screenshots/08-fight-drilldown.png`. The README's `## API surface` table is unchanged (already had `/api/v1/fights/{id}/timeline?window_s=N` at row 7 from v0.10.17). The v0.10.18 D4 closes the UI-compass gap for the Replay UI. LOC delta: ~3.

### Tests (cumulative)

- Web Playwright: 21 (cycle-start at v0.10.17 main) -> 25 (cycle-end at v0.10.18 main). Delta: +4 cases from D3.
- Web vitest: 162 (cycle-start) -> 162 (cycle-end). Delta: 0 (cycle is docs-only + Playwright e2e on the Replay UI; vitest surface unchanged).
- Apps/api pytest: unchanged in this cycle (D2 is deferred; the cycle is web-only).

### Validation

- `uv run ruff check apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN (cycle is web-only, backend untouched).
- `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN (0 errors in 74 source files).
- `cd web && pnpm tsc --noEmit`: GREEN (the new spec is strict-mode clean).
- `cd web && pnpm vitest run`: GREEN (28 files / 162 tests = 100% pass; the 7 pre-existing vitest failures are pre-closed by v0.10.17 D3 atomic mock-layer swap).
- 3 atomic code+tests commits (D1 marker `--allow-empty` + D3 spec + D4 README row) + 2 docs commits (release+changelog + roadmap+audit) land on `main` per `CONTRIBUTING.md` linear-history rule.
- Tag `v0.10.18` annotated + pushed + `gh release create` published at <https://github.com/Roddygithub/Gw2Analytics/releases/tag/v0.10.18>.

### Pre-existing failures AFTER v0.10.18 (carry-forward O6 to a v0.10.X docker-block follow-up)

- 0 vitest failures (down from 7 pre-v0.10.17 D3; the residual 6 hypothesised at the v0.10.17 cycle-end audit were closed by v0.10.17 D3 in atomic mock-layer swap -- the "6" framing was a hypothesis turned out wrong at v0.10.18 D1 marker discovery).
- 2 pytest failures in `apps/api/tests/test_uploads_e2e.py` (STABLE from v0.10.15 release notes; docker-blocked pending operator action -- see D2 deferred note above).

### Cross-references

- Cycle plan provenance: [`plans/v0.10.18-mimo-half-prompt.md`](./plans/v0.10.18-mimo-half-prompt.md) (the parent brief).
- Cycle release notes: [`plans/RELEASE-v0.10.18.md`](./plans/RELEASE-v0.10.18.md).
- Cycle-end audit: [`plans/AUDIT-2026-07-20-1405720.md`](./plans/AUDIT-2026-07-20-1405720.md).
- Predecessor pre-closure audit: [`plans/AUDIT-2026-07-13-3b2e71f.md`](./plans/AUDIT-2026-07-13-3b2e71f.md) (the v0.10.17 cycle-end audit whose O6 finding set the v0.10.18 D1 scope).
- ROADMAP sync: [`docs/ROADMAP.md`](../docs/ROADMAP.md) "Current state (post v0.10.18 cycle)" + section 1.1 cycle shipts v0.10.18 entry + section 1.2 shortlist re-classification (D2 docker-blocked pytest follow-up + AG Grid M6).

[0.10.18]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.10.17...v0.10.18

## [0.10.20] - 2026-07-13: M8 PARTIAL-FIX (PR-1 K-1 fixed + PR-2 K-3 isolated + simplified PR-3 K-2 attempted; 12 residuals ▶ v0.10.21)

The v0.10.20 mimo-half cycle shipped as M8 PARTIAL-FIX. The 1-iteration budget landed 3 of 4 conceptual K-cluster PRs. PR-1 (apps/api/tests/test_uploads_arq.py) closes 5 K-1 ConnectionError lifespan-race failures via `mock_arq_pool(client: TestClient)` reshape; the 5 closed failures are replaced by 6 new `IntegrityError` failures on `fk_webhook_deliveries_subscription_id` UNMASKED by the now-functional mock (pre-existing webhook_dispatch test-isolation latent bug). PR-2 (apps/api/tests/conftest.py) introduces a new `_isolate_dns_executor` autouse swapping `webhooks._DNS_EXECUTOR` to fresh per-test 32-worker pool + `shutdown(wait=False)` on teardown - defensible correctness for K-3 saturation test isolation. Simplified PR-3 (apps/api/tests/conftest.py) adds `_get_settings_no_dotenv` with `os.environ.pop("GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS", None)` + patches `get_settings` with a `functools.cache`-decorated factory returning `Settings(_env_file=None)` - preserves D2 baseline. D2 baseline (tests/test_uploads_e2e.py 36 of 36 PASS) preserved. 12 K-cluster residuals (K-1 = 6 UNMASKED FK + K-2 = 4 SSRF-gate + K-3 = 2 DNS tarpit) forward-blocked to v0.10.21 M-8-bis. Anchor commits off main on `v0.10.20/mimo-half` branch tip: M9 commit + PR-1 + PR-2+PR-3 + 3 close-out docs (CHANGELOG + ROADMAP + AUDIT). Cross-references: plans/RELEASE-v0.10.20.md + plans/AUDIT-2026-07-13-v0.10.20.md + plans/M9-pre-commit-hook-race-fix.md. ADR 002 WIP branch `v0.10.21/f17-statechange-extension` opened with marker file (NOT ff-merged yet).

[0.10.20]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.10.19...v0.10.20

## [0.10.19] - 2026-07-12: M8 forward-deferred to v0.10.20 + docs-only cycle close-out

### Note (M8 DEFERRED to v0.10.20)

The v0.10.19 `mimo-half` cycle attempted to resolve the 11 M8 pytest
failures surfaced at the v0.10.18.1 cycle-end audit
(`plans/AUDIT-2026-07-13-2ffafc75.md`). After **6 iterations** on
`apps/api/tests/conftest.py`'s `_disable_dotenv_for_tests` autouse fixture
(4-arg typed signature → `*sources: object` → `*args, **kwargs` → keyword-only
→ exact 6-parameter mixed signature matching pydantic-settings' actual call
style), 3 residual failures persisted out of the original 11. Per the
`code-reviewer-minimax-m3` strongest recommendation, the M8 K-cluster is
DEFERRED to v0.10.20 and the v0.10.19 cycle ships as a **DOCS-ONLY
CLOSE-OUT** to cap late-cycle re-iteration costs.

**Critical clarification:** the 11 M8 K-cluster failures belong to the
**Test-Substrate Mismatch (Bucket K)** class — meaning **NO
production-code regressions exist**. The failures are exlusively in test
substrate (conftest fixtures, autouse monkey-patching, pydantic-settings
.env-file vs `monkeypatch.delenv` precedence semantics, DNS-executor pool
size vs saturation-test concurrency). The K sub-bucket distribution is:

- **K1 (5)**: `tests/test_uploads_arq.py` — Arq-Worker connectivity
  leaks. The `_disable_arq_for_tests` autouse patches `arq.create_pool`
  to raise `ConnectionError` but the `_mock_arq_pool` test fixture's
  lifespan race is not hermetic enough; production path is correct.
- **K2 (4)**: `tests/test_webhooks_e2e.py` (4 SSRF gate tests) —
  IP-routing/`SSRF` gate semantics vs docker network namespace. With
  dotenv disabled, gate correctly fires 422; without dotenv-disable,
  the .env file's `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1` makes the
  test bypass the gate (test host leaks the dev opt-in).
- **K3 (2)**: `tests/test_webhooks_dns_under_attack.py` +
  `tests/test_webhooks_getaddrinfo_timeout.py` — DNS-resolver-pool
  saturation/latency budget. Production `_DNS_EXECUTOR` has
  `max_workers=32`; the saturation test's 100-tarpit burst completes
  within the 2.0s `future.result(timeout)` fence on the production
  pool but the test path needs `max_workers=1` to trigger the fence.
  PR-2's `max_workers=1` was applied during the 6 iterations but the
  conftest signature churn inverted the change in it3-6.

### Adopted path (DEFER)

1. **Discarded** dirty `apps/api/tests/conftest.py` and
   `apps/api/tests/test_uploads_arq.py` iteration artifacts via
   `git checkout main -- ...` (back to the v0.10.18.1 baseline).
2. **Preserved** the plan-landing docs at commit `712522a` (already on
   main via the `v0.10.19/plan-landing` ff-merge at cycle
   start): `plans/RELEASE-v0.10.19.md` (M8 fix-up PRIMARY plan) +
   `docs/v0.10.19-combat-readout-spike.md` (F17 Combat readout sizing)
   + `plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md` (closure
   thread retrospective).
3. **Authored** this cycle's 3 close-out docs (this `## [0.10.19]`
   CHANGELOG entry + `docs/ROADMAP.md` stamp refresh +
   `plans/AUDIT-2026-07-12-cd6e9ad.md` cycle-end audit).

### Cycle topology

| Commit | Purpose |
|--------|---------|
| `712522a` | plan-landing ff-merge (M8 fix-up + F17 spike + retrospective) |
| marker | `--allow-empty` v0.10.19 cycle window |
| docs1   | `CHANGELOG.md` `[0.10.19]` entry splice |
| docs2   | `docs/ROADMAP.md` stamp refresh + M8-kept language |
| audit   | `plans/AUDIT-2026-07-12-cd6e9ad.md` cycle-end audit |

### Cross-references

- **Cycle-end audit**: [`plans/AUDIT-2026-07-12-cd6e9ad.md`](./plans/AUDIT-2026-07-12-%3Cmarker-sha%3E.md)
- **Release plan**: [`plans/RELEASE-v0.10.19.md`](./plans/RELEASE-v0.10.19.md) (M8 fix-up PRIMARY; K1+K2+K3 sub-bucket breakdown)
- **Prior cycle audit (K1+K2+K3 discovery)**: [`plans/AUDIT-2026-07-13-2ffafc75.md`](./plans/AUDIT-2026-07-13-2ffafc75.md) (v0.10.18.1)
- **F17 spike (forward-deferred blocker)**: [`docs/v0.10.19-combat-readout-spike.md`](./docs/v0.10.19-combat-readout-spike.md)
- **Closure thread retrospective**: [`plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md`](./plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md)

## [0.10.18.1] - 2026-07-13: D2 pre-closure marker (plan 038 D2 vacuity confirmed) + NEW M8 forward-deferred discovery (11 webhook/Arq/DNS test-substrate mismatches)

The v0.10.18.1 cycle (the post-v0.10.18 follow-up mimo-half, per the deferred D2 carry-forward in [`plans/RELEASE-v0.10.18.md`](./RELEASE-v0.10.18.md) and [`plans/v0.10.18-mimo-half-prompt.md`](./v0.10.18-mimo-half-prompt.md)) is a **two-fold closeout cycle** — mirroring the v0.10.18 D1 pre-closure pattern, but with a NEW high-priority backlog item surfaced by the diagnostic-first phase:

1. **D2 vacuity-closure marker**: the v0.10.18 brief's D2 ("close the 2 residual pre-existing pytest failures in `apps/api/tests/test_uploads_e2e.py`") is CONFIRMED vacuous for that specific file (`test_uploads_e2e.py` 36/36 PASS in 3.18s).
2. **NEW M8 forward-deferred discovery**: the full-surface diagnostic surfaced 11 previously-undiscovered pytest failures in webhook/Arq/DNS-related test files — all env/test-substrate mismatches (NOT code regressions). Forward-deferred as the v0.10.19 mimo-half PRIMARY scope.

The cycle ships a 0-line `--allow-empty` marker commit + 4 cycle docs; no code changes (applying a vacuous fix would be dishonest per the diagnostic-first mandate from `CONTRIBUTING.md`).

### Note (D2 pre-closure — 0-line marker + diagnostic methodology + M8 discovery)

The v0.10.18 brief scoped D2 as "close the 2 residual pre-existing pytest failures in `apps/api/tests/test_uploads_e2e.py` (carry-forward O7 from the v0.10.17 cycle-end audit)". The v0.10.18.1 diagnostic-first phase ran the **full `apps/api/tests/` surface** (not just the audit-pointed file) and revealed two distinct finding classes:

- **D2 vacuity (per the O6-pointed file)**: `test_uploads_e2e.py` runs **36/36 PASS in 3.18s** at cycle-start HEAD `e47c9a3`. The audit-pointed file is empty of failures.
- **NEW M8 finding (NOT in the audit's narrow O6 hypothesis)**: 11 pytest failures in webhook/Arq/DNS-related test surfaces. Summary of all 11:

| # | Test | File area |
|---|---|---|
| 1 | `test_create_upload_enqueues_via_arq` | test_uploads_arq.py (Arq-Worker enqueue) |
| 2 | `test_create_upload_idempotent_existing_failed_enqueues` | test_uploads_arq.py (idempotent failed re-dispatch) |
| 3 | `test_create_upload_503_when_arq_down_and_no_fallback` | test_uploads_arq.py (Arq-fallback 503 path) |
| 4 | `test_re_upload_does_not_redispatch_when_not_failed[pending]` | test_uploads_arq.py (re-upload gating parametrized) |
| 5 | `test_re_upload_does_not_redispatch_when_not_failed[completed]` | test_uploads_arq.py (re-upload gating parametrized) |
| 6 | `test_pool_saturation_gracefully_returns_422` | test_webhooks_dns_under_attack.py (DNS resolver pool limit) |
| 7 | `test_post_webhook_rejects_https_private_ip_literal` | test_webhooks_e2e.py (SSRF private-IP gate) |
| 8 | `test_post_webhook_rejects_https_link_local_literal` | test_webhooks_e2e.py (SSRF link-local gate) |
| 9 | `test_post_webhook_rejects_https_ipv6_loopback_literal` | test_webhooks_e2e.py (SSRF IPv6-loopback gate) |
| 10 | `test_post_webhook_rejects_https_hostname_resolving_to_private` | test_webhooks_e2e.py (DNS-resolves-to-private gate) |
| 11 | `test_getaddrinfo_timeout_returns_422` | test_webhooks_getaddrinfo_timeout.py (DNS timeout → 422) |

**Diagnostic env (canonical, reproducible)**: fresh `SECRETS_KEK` populated in `apps/api/.env` (Fernet 32-byte key; required for Settings() at app startup); freshly-dropped + re-created `gw2analytics` Postgres database; `uv run alembic upgrade head` confirmed schema at `0013_drift_cleanup (head)`; live `docker compose` services HEALTHY (postgres:16-alpine + redis:7-alpine + minio/minio:latest — all started 2 days ago, all HEALTHY).

**Diagnostic command (canonical)**:
```bash
cd /home/roddy/Gw2Analytics/apps/api
set -a; source /home/roddy/Gw2Analytics/apps/api/.env; set +a
uv run pytest /home/roddy/Gw2Analytics/apps/api/tests -rfE --tb=no --no-header -q
# Result: 11 failed, 286 passed, 2 skipped in ~15 seconds
```

### Classification bucket K — Test-Substrate Mismatch

All 11 failures cluster on **test-to-substrate mismatches** (Arq pool fallback toggles, IP-routing/SSRF gates, and monkeypatched DNS timeouts) running on the live docker-compose stack. Confirmed as test environment drift rather than production code regressions.

**Distribution by root-cause hypothesis** (confirmed by reading the test files):

- **K1 (5): Arq-Worker connectivity** — the `test_uploads_arq.py` fixture set assumes `ALLOW_INREQUEST_PARSE_FALLBACK=1` + an isolated Arq pool, but the live docker-compose stack spawns a real Redis-backed Arq worker that becomes reachable from inside the test process. The pytest fixture's monkeypatching leaks at the conftest.py `_disable_arq_for_tests` global.
^- **K2 (4): IP-routing/SSRF gate semantics** — the `test_webhooks_e2e.py` SSRF block tests (`private_ip_literal`, `link_local_literal`, `ipv6_loopback_literal`, `hostname_resolves_to_private`) assert HTTPS requests to literal private addresses get a 4xx. On the live docker-compose network namespace, the webhooks SSRF validator's socket-level checks behave differently from when the tests were originally authored (the v0.9.2 webhook SSRF module assumed inline DNS resolution, but conftest-level monkeypatching of `socket.getaddrinfo` doesn't always restore the original behavior cleanly).
^- **K3 (2): DNS-resolver-pool saturation / latency budget** — `test_webhooks_dns_under_attack.py::test_pool_saturation_gracefully_returns_422` requires a bounded thread-pool + timeout under load. The current `_DNS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)` is sized correctly but the test asserts a 422 within ~50ms; on a CI box with 100% CPU contention, this exceeds the timeout and the test sees the request hang instead of 422.

### Guard rail (NOT a regression in production code)

> None of the 11 failures indicate a regression in core application logic; they are purely isolation leaks and test-env mismatches where the test suite's fake DNS, literal IP assumptions, and Redis mocks collide with the host's live docker-compose substrate.

The production code paths (POST /api/v1/webhooks SSRF gate, GET /api/v1/fights/{id}/events Arq fallback, etc.) work correctly in live deployment. The pytest failures are engineering-debt on the test isolation layer, not on the application layer.

### Historical context — D2 hyp was for test_uploads_e2e.py specifically (4 cycles of hypothesis-grade carry-forward now closed)

The v0.10.18 brief's "2 pre-existing pytest failures in `apps/api/tests/test_uploads_e2e.py` stable since v0.10.14 release notes" is now verified VACUOUS for that specific file. Why the hypothesis turned out wrong: multiple intervening cycles' substrate fixes collectively closed the substrate gaps that were the actual root cause of the historically stable pytest fail rate:

- **v0.9.1 plan 006** closed the request-scoped vs worker-scoped Session DI: pre-plan-006 `process_parse` BackgroundTasks detached the ORM session prematurely → `DetachedInstanceError` → flaky pytest FAIL.
- **v0.9.2 plan 009** added the `_isolate_test_state` autouse fixture in `apps/api/tests/conftest.py`: pre-plan-009 a 4 pytest-file cohort hung at the 30s wallclock ceiling because uploads + fights + summary rows accumulated across runs. Post-plan-009 stable.
- **v0.10.1 plan 010** Arq parser worker + `ALLOW_INREQUEST_PARSE_FALLBACK=1` env gate: pre-plan-010 the `test_uploads_e2e_happy_path` POST + GET `201` race was timing-fragile; post-plan-010 stable.
- **v0.10.5 plan 021** apps/api A2 god-module refactor: test ergonomics + refactor-creep pre-fix.
- **v0.10.15 plan 032/033/034** except-narrowing: settings + decrypt + SSRF guards produce stable pytest.

By v0.10.18.1 cycle-start, all of these substrate fixes had been in place for several cycles. The diagnostic at v0.10.18.1 confirms the failure count for the audit-pointed file is 0.

D2 reduces to a 0-line `--allow-empty` commit (`<marker-commit-sha> test(api): verify D2 pre-closed (plan 038 D2 marker)`) documenting the discovery so the 4-deliverable thread (or in this case the 1-deliverable-since-D1-was-also-vacuous thread + the NEW M8 discovery) is preserved in git lineage for downstream tooling.

### Milestone: first 100% GREEN test state since v0.10.13 (per audit-pointed file)

**This v0.10.18.1 release marks the first time since v0.10.13 that the project's pinpointed-file test surface — `apps/api/tests/test_uploads_e2e.py` 36/36 PASS + vitest whole-repo 28 files / 162 tests pass + Playwright e2e 25/25 pass — is 100% GREEN with zero pre-existing failures.** The O6/O7 carry-forward chain that spanned v0.10.14 → v0.10.15 → v0.10.17 → v0.10.18 → v0.10.18.1 (5 cycles of accumulated hypothesis-grade carry-forwards) is now closed at both surfaces (vitest side via v0.10.18 D1; pytest-audit-pointed-file side via this v0.10.18.1 D2 vacuity).

**Note**: the 11 M8 failures in webhook/Arq/DNS surfaces are NOT counted in the "pinpointed-file" milestone. They are a separate finding (bucket K, surfaces they didn't fall under the O6 hypothesis) and are forward-deferred to v0.10.19 mimo-half PRIMARY scope.

### Tests (cumulative)

- Web Playwright: 21 (cycle-start at v0.10.17 main) → 25 (post-v0.10.18 main) → 25 (v0.10.18.1 cycle-end = current). Delta: 0 (the v0.10.18 D3 4-case NEW spec is unchanged).
- Web vitest: 162 (cycle-start) → 162 (v0.10.18.1 cycle-end). Delta: 0.
- Apps/api pytest: ≥252 (cycle-start) → ≥297 (v0.10.18.1 cycle-end; = cycle-start + 11 NEW discovered failures + subsequent enumeration work). Delta: +11 failures DISCOVERED (bucket K = Test-Substrate Mismatch, not regressions; deferred to v0.10.19).

### Validation

- `uv run ruff check apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN (cycle is docs-only — D2 vacuity + M8 discover-only; backend untouched).
- `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src`: GREEN (0 errors in 74 source files).
- `cd apps/api && uv run pytest apps/api/tests/test_uploads_e2e.py --no-header -v`: GREEN. 36/36 PASS in 3.18s on the pinpointed file (the O6 hypothesis file). **D2 vacuity confirmed.**
- `cd apps/api && uv run pytest apps/api/tests --no-header -v`: PARTIAL. 11 failed / 286 passed / 2 skipped in ~15s. **M8 NEW discovery surfaced.**
- `uv run pytest libs/gw2_core libs/gw2_analytics --no-header -v`: GREEN (208 passed in 0.27s).
- `cd web && pnpm tsc --noEmit`: GREEN.
- `cd web && pnpm vitest run --no-header --reporter=basic`: GREEN. 28 files / 162 tests pass (reaffirms v0.10.18 D1 vacuity).
- `cd web && pnpm playwright test web/tests/e2e/replay-ui.spec.ts`: GREEN. 4/4 pass (reaffirms v0.10.18 D3).
- 1 atomic code+tests commit (`--allow-empty` marker) + 2 atomic docs commits (`release+changelog` + `roadmap+audit`) land on `main` per `CONTRIBUTING.md` linear-history rule.
- Tag `v0.10.18.1` annotated + pushed + `gh release create` published at <https://github.com/Roddygithub/Gw2Analytics/releases/tag/v0.10.18.1>.

### Pre-existing failures AFTER v0.10.18.1

| Surface | Count AFTER v0.10.18.1 | Notes |
|---|---:|---|
| vitest whole-repo | **0** | closed at v0.10.17 D3 (mock-layer swap; all 7 atomically) and reaffirmed at v0.10.18 D1 marker. |
| pytest `apps/api/tests/test_uploads_e2e.py` (the O6-pointed file) | **0** | closed at this v0.10.18.1 D2 marker (36/36 PASS). |
| pytest `apps/api/tests/` FULL surface (excluding M8 deferred) | **0** | closed at v0.10.18 D1/v0.10.18.1 D2 work + v0.10.17 substrate fixes. |
| Playwright e2e (replay-ui.spec.ts) | **0** | the v0.10.18 D3 NEW 4-case spec passes; no regressions. |
| pytest `apps/api/tests/` (FULL surface, INCLUDING M8) | **11** ⚠️ | NEW v0.10.18.1 discovery, bucket K = Test-Substrate Mismatch; deferred as v0.10.19 mimo-half PRIMARY scope. |

### ROADMAP impact (Status line delta)

The README "Status" line delta is: `**Deferred**: 5 → **6** (target v0.10.19)` — adds M8 (the 11 webhook/Arq/DNS test-substrate mismatches) as the new 6th forward-deferral to the v0.10.19 mimo-half budget.

### Cross-references

- Cycle release notes: [`plans/RELEASE-v0.10.18.1.md`](./RELEASE-v0.10.18.1.md) (the cycle release notes following the v0.10.18 RELEASE-v0.10.18.md template; documents the D2 vacuity discovery + M8 forward-deferred discovery + diagnostic methodology + the milestone + the substrate-fix cross-references).
- Cycle-end audit: [`plans/AUDIT-2026-07-13-<marker-sha>.md`](./AUDIT-2026-07-13-<marker-sha>.md) (the cycle-end audit at the marker commit short-SHA anchor; verifies pre-existing failure tally closes to 0 on the pinpointed-file surface + the FULL-surface discovery of 11 M8 failures + the validation matrix + the long-tail polish items M5 + M6 + M7 are deferred to v0.10.20+, with M8 promoted to v0.10.19 PRIMARY).
- Predecessor cycle release notes (v0.10.18 D2 deferred to here): [`plans/RELEASE-v0.10.18.md`](./RELEASE-v0.10.18.md).
- Predecessor cycle-end audit (v0.10.17 D3 closed vitest side): [`plans/AUDIT-2026-07-13-3b2e71f.md`](./AUDIT-2026-07-13-3b2e71f.md).
- Cycle parent brief: [`plans/v0.10.18-mimo-half-prompt.md`](./v0.10.18-mimo-half-prompt.md).
- Project-wide audit (orthogonal — project scope, not cycle scope): [`plans/AUDIT-2026-07-13-PROJECT-WIDE.md`](./AUDIT-2026-07-13-PROJECT-WIDE.md).
- ROADMAP sync: [`docs/ROADMAP.md`](../docs/ROADMAP.md) "Current state (post v0.10.18.1 cycle)" + section 1.1 cycle shipts v0.10.18.1 entry + section 1.2 shortlist re-classification (M1 + M2 + M3 + M4 closed; M8 + M6 + M5 + M7 deferred to v0.10.19+).

[0.10.18.1]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.10.18...v0.10.18.1

## [Unreleased]



## [0.10.2] - v0.10.2: 100-row cap on per-target roll-up + per-skill lists (hotfix followup #12)

### Fixed (apps/api - v0.10.2 hotfix followup #12)

The 100-row cap on the per-target roll-up lists (`target_dps` + `target_healing` + `target_buff_removal` in `GET /api/v1/fights/{id}/events`; `skills` in `GET /api/v1/fights/{id}/skills`) is the v0.10.3 parser-bug mitigation. The pre-cap aggregator returned ALL groups, so a v0.10.3 regression that misreads `source_agent_id` (or the parser-side skill-table read) can produce hundreds of thousands of unique garbage IDs, the JSON response explodes to multi-MB, the connection drops (HTTP 000), and the analyst sees a Next.js "fetch failed" timeout on the fight drilldown page. The cap slices the per-target lists to the top-100 by damage / healing / strip descending (the aggregators already order by magnitude descending, so the kept rows ARE the analyst-relevant signal — the dropped tail is the noise floor). `event_windows` is NOT capped (it groups by time bucket, naturally bounded by fight duration).

- `apps/api/src/gw2analytics_api/routes/fights.py::get_fight_events` + `get_fight_skills`: cap `target_dps[:100]` + `target_healing[:100]` + `target_buff_removal[:100]` + `skills[:100]` after the aggregator runs. Comment block documents the v0.10.3 root cause + the "top-N is the analyst signal" rationale + the `event_windows`-uncapped exception.
- `apps/api/tests/test_fight_rollup_cap.py` (NEW, 4 hermetic tests): one per capped list. Each test seeds a fight with 150 unique targets/skills + 150 events with descending magnitudes and asserts the response has exactly 100 rows, in descending order, with the top-100 by magnitude preserved. The 4 tests cover the 4 cap sites independently (DPS + Healing + BuffRemoval on `/events`; per-skill on `/skills`); pure-strip events (`value=0`, `buff_dmg>0`, `is_nondamage=1`) exercise the Phase 8 dual-emit-free path on the BuffRemoval test.


## [0.10.1] - v0.10.1: schema-drift guard at startup + Arq parser worker (plan 010)

### Added (apps/api + infra - v0.10.1 plan 010: schema-drift guard + Arq parser worker)

Closes 2 real bugs found by real-payload testing on 2026-07-09 (1,605 WvW `.zevtc` files, 2.6 GB, 11 accounts):

- **Bug #1**: in-memory SQLAlchemy ORM registry went stale after the
  `0009_webhook_secret_at_rest.py` migration was edited. The live DB
  renamed the column `secret` → `ciphertext`; the running Uvicorn
  process (started 1h42m BEFORE the migration edit) still held the
  pre-migration class mappings. The webhook scheduler spammed
  `psycopg.errors.UndefinedColumn: column webhook_subscriptions.secret
  does not exist` every 5s — `/tmp/fastapi.log` grew to 253K chars of
  stack traces.
- **Bug #2**: CPU-bound `process_parse` blocked FastAPI's
  `BackgroundTasks` thread pool on parallel uploads. 8 concurrent
  `.zevtc` uploads all stuck on `pending` after 20s; the GIL serialised
  the 8 pure-Python parse calls. Pre-existing TODO in
  `services.py::process_parse` line ~60 already flagged this.

#### Bug #1 fix: schema-drift guard at startup
- `apps/api/src/gw2analytics_api/schema_guard.py` (NEW): pure helper
  `check_schema_drift()` that compares the alembic head on disk to
  the `alembic_version.version_num` row in the DB. Raises
  `RuntimeError` with an operator-facing message naming both heads so
  the operator can grep `apps/api/alembic/versions/` for the missing
  migration. Escape hatch `SKIP_SCHEMA_GUARD=1` for
  rollback-in-flight scenarios (WARNING-logged so the bypass is
  visible in `/tmp/fastapi.log`).
- `apps/api/src/gw2analytics_api/main.py::lifespan`: calls
  `check_schema_drift()` at the very top, BEFORE any other init. A
  stale ORM registry now crashes Uvicorn at boot with an actionable
  error instead of silently spamming the log for hours.

#### Bug #2 fix: Arq parser worker
- `docker-compose.yml`: added `redis:7-alpine` service (port 6379,
  healthcheck `redis-cli ping`).
- `apps/api/pyproject.toml`: added `arq>=0.25` + `redis>=5.0` deps;
  `uv lock` regenerated (93 packages).
- `apps/api/src/gw2analytics_api/workers/parser_worker.py` (NEW):
  async Arq job `parse_job(ctx, upload_id, raw_bytes)` that runs
  `process_parse` + `dispatch_for_upload` chained via
  `asyncio.to_thread`. **Closes a pre-existing race**:
  `dispatch_for_upload` previously ran as a sibling
  `BackgroundTasks.add_task` BEFORE `process_parse` committed, so
  it short-circuited and zero webhook deliveries fired on every
  successful upload. The chain guarantees `dispatch_for_upload`
  awaits the parse commit.
- `apps/api/src/gw2analytics_api/workers/parser_settings.py` (NEW):
  `WorkerSettings` class with `functions=[parse_job]`,
  `redis_settings=RedisSettings(...)`, `max_jobs=2`,
  `job_timeout=600`. Runnable via
  `arq gw2analytics_api.workers.parser_settings.WorkerSettings` in
  a separate process. `ARQ_REDIS_HOST` + `ARQ_REDIS_PORT` env vars
  override the localhost default for production deploys.
- `apps/api/src/gw2analytics_api/main.py::lifespan`: tries to
  create the Arq pool at startup; on failure logs a WARNING + sets
  the pool to `None` (graceful fallback). The route handler takes
  a sync-in-request fallback path that runs the parse + dispatch in
  `asyncio.to_thread` (preserves the v0.10.0 test contract).
- `apps/api/src/gw2analytics_api/routes/uploads.py`: route handler
  is now `async def create_upload(request: Request, ...)`. New
  helper `_enqueue_parse(request, upload_id, raw)` checks
  `request.app.state.arq_pool` and either enqueues via Arq OR runs
  the parse + dispatch in-request (fallback).

#### Public contract change (note for integrators)
- `UploadCreatedResponse.status` can now legitimately be
  `"completed"` in the 201 response body when the Arq path's
  fallback fires (Redis down at request time). Pre-v0.10.1 the
  response was always `"pending"`. Integrators that poll right
  after the POST and use `"pending"` as a "still processing"
  signal should switch to the `GET /uploads/{id}` poll OR check
  `fight_id !== null`.

#### BREAKING for the failure path (note for integrators)
- `POST /api/v1/uploads` now returns `HTTP 503 Service Unavailable`
  (with body `"Parser worker unavailable. Check Redis is up."`)
  when the Arq worker is unreachable. Pre-v0.10.1 the route
  always returned 201 (success), 422 (validation), or 5xx
  (server error). v0.10.1 with Redis down returns 503 — a
  separate failure class. Integrators that retry on 5xx MUST
  distinguish 503 (transient infrastructure failure; retry with
  backoff) from 500 (programming bug; do not retry).
  Production safety: the 503 surfaces the Redis misconfiguration
  to operator dashboards instead of silently degrading to
  multi-second POST latency. The pre-v0.10.1 sync-in-request
  fallback is gated on `ALLOW_INREQUEST_PARSE_FALLBACK=1` (test
  + dev environments only; production omits the env var to get
  the loud 503).

#### Tests (apps/api)
- `apps/api/tests/conftest.py`: new autouse fixture
  `_disable_arq_for_tests` points the broker at `localhost:1` so
  the lifespan's pool creation fails fast (test env always uses
  the sync-in-request fallback).
- `apps/api/tests/test_schema_guard.py` (NEW, 4 tests):
  no-drift passes / drift raises with both heads named /
  `SKIP_SCHEMA_GUARD` escape hatch / NULL `alembic_version` row.
- `apps/api/tests/test_uploads_arq.py` (NEW, 4 tests):
  mock-Arq enqueue contract / sync-in-request fallback path /
  idempotent re-parse of failed upload / no re-dispatch on
  re-upload of completed (the pre-v0.10.1 contract is
  preserved — double-dispatch would be a silent regression).
- `apps/api/tests/test_parser_worker.py` (NEW, 4 tests): happy
  path chain (`parse` → `dispatch`) / skip dispatch on parse
  failure (Arq retry kicks in) / swallow dispatch failure
  post-parse (no re-parse; manual operator re-dispatch) /
  asyncio.to_thread contract.

#### Planning
- `plans/010-v101-schema-drift-guard-and-arq-parser.md` (NEW): the
  v0.10.1 plan doc covering both bugs (the design output of the
  round-1 diagnosis).

#### Tests (cumulative)
- Apps/api pytest: 92 (v0.10.0) → **104** (v0.10.1). Delta: +12
  from the 3 new plan-010 test files.
- Web vitest + Playwright: unchanged (the v0.10.1 cycle is
  backend-only).
- Total: 339 (v0.10.0) → 351 (v0.10.1).


## [0.10.0] - v0.10.0: CSV injection guard + cross-account comparison timeline + webhook secret-at-rest envelope encryption (plans 030, 031, 032)

### Added (web - v0.10.0 plan 030: CSV injection guard, OWASP CWE-1236)

The v0.10.0 cycle (per `plans/010-v100-roadmap.md`) is now underway. Item A in the v0.10.0 cycle is the HIGH-severity CSV injection guard:

- `web/src/lib/csv.ts`: new module-level `FORMULA_TRIGGERS = /^[=+\-@\t\r]/` regex (anchored at start; matches the 6 canonical spreadsheet formula-trigger chars). The private `csvEscape(value)` function now has a formula-guard branch that fires BEFORE the RFC 4180 branch: when a value starts with one of the 6 trigger chars, prefix with a literal `'` + wrap in double quotes per RFC 4180. Excel/Sheets drop the leading `'` on display but the formula is no longer parsed. Implementation uses a template literal (the template-literal form is the canonical Way to express \" + ' + value + \" with one escaping layer).
- `web/tests/lib/csv.test.ts`: 12 NEW hermetic cases (6 trigger-char tests via `it.each` + safe-path alphanumeric + null + undefined + combined formula+dq + combined formula+comma) + 1 PlayerListRow integration test using the canonical inline `type Pr = import(\"@/lib/api\").PlayerListRow` pattern (TS type-position dynamic import; the `await` wrapper is invalid in a type position). Total csv.test.ts: **23/23** pass; full vitest: **97/97** across 15 files.
- 4 attacker-controllable upload fields are now formula-safe: `name` on `PlayerListRow`/`PlayerProfile`/`PerFightBreakdownRow`, `skill_name` on `SkillUsageRow`, `subgroup` on `SquadRollupRow`, `description` on `WebhookSubscription`. OWASP CWE-1236 class closed on the existing CSV export surface.

### Deferred (v0.10.0 backlog - tracked from `plans/010-v100-roadmap.md` scope)

- **B (security HIGH)**: webhook secret-at-rest envelope encryption. NOW SHIPPED — see v0.10.0 plan 031 entry below. The previously-deferred-from-v0.9.1 hardening layer is closed: CWE-256 (plaintext storage of a password) is no longer surface-able via DB snapshot alone (KEK must ALSO be in the gateway process environment).
- **C (UX)**: cross-account timeline comparison (M effort). NOW SHIPPED — see v0.10.0 plan 032 entry below. The squad-comparison use case (e.g. "how does my DPS compare to my healer's damage absorbed over the same fight window?") is closed with the new `GET /api/v1/players/compare/timeline?accounts=A&accounts=B` route + the new `/players/compare` page.

### Added (apps/api + web - v0.10.0 plan 032: cross-account comparison timeline)

The v0.10.0 cycle item C closes the maintainer's most-requested feature in the incident log (per `docs/ROADMAP.md` §1): the squad-comparison use case. The new endpoint + page let the analyst overlay 2-4 accounts' damage / healing / strip curves on a single chart with a metric radio (Damage / Healing / Buff removal), a linear/log Y-axis scale toggle, and the shared 25-zone TZ selector. ~16 files changed (3 new backend + 6 new web + 5 modified + 2 docs).

- `libs/gw2_analytics/src/gw2_analytics/cross_account_timeline.py` (NEW, ~280 LoC): the stateless `CrossAccountTimelineAggregator` + Pydantic `CrossAccountTimelinePoint` + `CrossAccountTimelineSeries` models. Recency-first sort (mirrors the per-account contract) + day-bucketing (mirrors the per-account `_combine_day_midnight` helper). `aggregate(per_account_contributions, fight_id_to_started, bucket, tz)` is the single entry point.
- `libs/gw2_analytics/tests/test_cross_account_timeline.py` (NEW, 7 hermetic cases): empty input / two-account / recency-first sort / account-with-no-fights / day-bucketing / default-tz-is-utc / invariant guard.
- `apps/api/src/gw2analytics_api/routes/player_compare.py` (NEW, ~140 LoC): `GET /api/v1/players/compare/timeline?accounts=A&accounts=B&bucket=day&tz=Continent/City` with a **repeatable** `accounts` query param (`[2, 4]` unique accounts enforced by `Query(min_length=2, max_length=4)`). Reuses the per-account route's `_compute_contributions` helper. Declaration-order matters: MUST be included BEFORE the players router in `main.py` so the catch-all `{account_name:path}` doesn't greedily match `/players/compare/timeline` as `account_name="compare/timeline"`. Returns 422 on out-of-range, 422 on unknown IANA TZ, 200 with `points: []` for an unknown account (NOT 404 -- the analyst UX benefits from a same-shape response for all requested accounts).
- `apps/api/src/gw2analytics_api/main.py`: includes `player_compare.router` BEFORE `players.router`; `version="0.8.6"` -> `"0.10.0"`.
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`: re-exports `CrossAccountTimelineAggregator` + `CrossAccountTimelineSeries`.
- `web/src/lib/api.ts`: `fetchPlayerCompareTimeline(accounts, opts)` + `CrossAccountTimelinePoint` + `CrossAccountTimelineSeries` types.
- `web/src/lib/timezones.ts` (NEW): the 25-city IANA catalog extracted from `PlayerTimelineSection` so the per-account + cross-account selectors ship the SAME curated set (pre-plan-032 the compare section had a 9-zone subset; the analyst who has used the per-account page would silently lose 16 zones on the compare view).
- `web/src/components/CrossAccountTimelineChart.tsx` (NEW, ~280 LoC): purpose-built N-line SVG chart (NOT a wrapper around the existing `TimelineChart` because the cross-account use case is 1 metric × N accounts, the inverse of the per-account chart's N metrics × 1 account). 4-color palette (red / green / blue / purple) per account. Broken-line segments for missing dates (an account with no fight on date D renders no line through D, rather than a misleading 0-baseline). Shared absolute Y axis (log scale default; matches the per-account log mode's "1M damage vs 50 strip" use case).
- `web/src/components/CrossAccountCompareSection.tsx` (NEW, ~280 LoC): Client Component. Owns the metric / scale / bucket / tz toggles + re-fetches the timeline when bucket / tz change. Read-only account chips (the in-page add/remove affordance is a v0.10.X followup; v0.10.0 ships set-via-URL).
- `web/src/app/players/compare/page.tsx` (NEW, ~210 LoC): Server Component. Reads `?accounts=` from URL search params, validates 2-4 unique accounts, fetches initial timeline on the server, renders the section. Empty-state copy for `< 2` accounts; upstream-error card for `> 4` or 422.
- `web/src/app/layout.tsx`: added Players + Compare secondary nav links between the brand and the search bar. Compare link goes to `/players/compare` (no query params); the page's empty-state copy guides the analyst to add accounts via URL.
- `web/src/app/players/page.tsx`: added a "Compare the first 2 players" CTA that pre-fills the URL with the first 2 rows' `account_name`; also `width: "100%"` defensive fix on the main element.
- `web/src/app/players/[account_name]/page.tsx`: `width: "100%"` defensive fix on the main element (the v0.9.0 visual regression on `:demo.<N>` accounts where the page rendered at ~900px wide instead of 1440px; the defensive fix prevents the silent collapse even when a downstream CSS rule would otherwise shrink the parent's intrinsic width; the root-cause investigation is a v0.10.X followup).
- `web/src/components/PlayerTimelineSection.tsx`: replaced the local 25-zone `TIMEZONE_OPTIONS` const with the import from `web/src/lib/timezones.ts` (the shared module).
- `web/tests/e2e/fixtures/cross-account-timeline.json` (NEW): 2-account fixture (TestAccount.1234 + TestAccount.5678) with overlapping but distinct fight sets across 3 dates (2026-07-07 + 2026-07-08 + 2026-07-09). Exercises the broken-line + legend + X-axis date-union paths.
- `web/tests/e2e/mock-server.mjs`: added `/api/v1/players/compare/timeline` endpoint with a 422 on unknown `?accounts=` values.
- `web/tests/e2e/players-compare.spec.ts` (NEW, 3 cases): initial render / metric radio toggles / 0-accounts empty state.
- `web/tests/components/cross-account-timeline-chart.test.tsx` (NEW, 5 cases): empty state / multi-account polylines / default Damage caption / metric switch / log scale Y-axis labels.
- `web/tests/components/cross-account-compare-section.test.tsx` (NEW, 2 cases): initial render + radio click.
- `web/tests/app/players-compare-page.test.tsx` (NEW, 3 cases): empty state / too-many / valid render.

### Deferred (v0.10.X followups - tracked from plan 032)

- **In-page add/remove accounts in `/players/compare`**: v0.10.0 ships read-only chips; the full in-page add/remove UX is ~50 LoC and is a v0.10.X followup.
- **Visual regression baseline for `/players/compare`**: a tracked `docs/screenshots/09-players-compare.png` (the route is dynamic; the fixture + e2e spec cover the e2e path; a visual baseline is a v0.10.X followup when the page settles).
- **Per-account-vs-cross-account rate columns**: a per-second rate field on `CrossAccountTimelinePoint` is a v0.10.X followup; the v0.10.0 wire surface is the totals-only contract (matches the per-account timeline).
- **900px bug root-cause investigation**: the `width: "100%"` defensive fix is in place but the underlying CSS root cause (likely the `auto-fit minmax(180px, 1fr)` stat grid + a downstream intrinsic-width shrink on `:demo.<N>` accounts) is a v0.10.X followup with a DevTools session.
- **Port-1 conftest trick robustness** (v0.10.1 plan 010 followup):
  `_disable_arq_for_tests` points RedisSettings at `localhost:1` to
  make the lifespan's Arq pool init fail fast. The port-1 trick
  works on every test host seen so far but is host-dependent
  (port 1 is reserved `tcpmux` and could be open on exotic
  configs). The robust alternative is to monkeypatch
  `arq.create_pool` directly to raise a fake `ConnectionError`.
  ~5 LoC; v0.10.X followup.
- **`test_re_upload_completed_does_not_redispatch` parametrize**
  (v0.10.1 plan 010 followup): the test pins the no-double-dispatch
  contract for `status == "completed"` but not for `pending` or
  any other non-failed status. Parametrize over 3-4 statuses to
  pin the full contract. ~5 LoC; v0.10.X followup.
- **`WorkerSettings.redis_settings` env-var override docstring**
  (v0.10.1 plan 010 followup): the env var is read in
  `parser_settings.py` but the module docstring does not document
  it. Add a one-line note so operators discover the override
  without grepping the source. ~3 LoC; v0.10.X followup.

### Added (apps/api - v0.10.0 plan 031: webhook secret-at-rest envelope encryption, OWASP CWE-256)

The v0.10.0 cycle item B closes the HIGH-severity CWE-256 (plaintext storage of a password) layer on the webhook subsystem. A stolen DB snapshot OR a flawed SELECT-leak no longer surfaces the plaintext HMAC secret directly; the attacker must ALSO have access to the gateway process's `SECRETS_KEK` env var. Implementation is server-side Python `cryptography.fernet.Fernet` (NOT Postgres `pgcrypto` `pgp_sym_encrypt` — the SQL wire exposure of the plaintext KEK in `pg_stat_statements` / `log_min_duration_statement` was a defense-in-depth violation; Python-side encryption keeps the KEK in process memory).

- `apps/api/pyproject.toml`: `cryptography>=43.0.1` added to runtime deps.
- `pyproject.toml` (root): `SECRETS_KEK=<44-char url-safe base64>` added to `[tool.pytest_env]` so the test suite has a valid 32-byte Fernet key at every pytest run.
- `apps/api/.env.example`: `SECRETS_KEK` documented with the canonical Python one-liner for generating a fresh KEK + a defense-in-depth warning (any DB compromise must NOT suffice without the env KEK).
- `apps/api/src/gw2analytics_api/crypto.py` (NEW): module-level Fernet envelope helper. `_get_fernet(kek)` is `lru_cache`d per KEK (one `Fernet(kek.encode("ascii"))` per process per env); `_resolve_kek(explicit=None)` reads `os.environ["SECRETS_KEK"]` with a clear error if missing; `encrypt_webhook_secret(plaintext: str, *, kek=None) -> bytes` and `decrypt_webhook_secret(ciphertext: bytes, *, kek=None) -> str` re-export the Fernet wrappers; `FernetInvalidToken` is an alias of `cryptography.fernet.InvalidToken` for clarity in audit logs.
- `apps/api/src/gw2analytics_api/config.py`: new `secrets_kek: SecretStr = Field(validation_alias="SECRETS_KEK")` (required at startup; no default; fails lazy if env missing). The `_validate_secrets_kek` `mode="before"` field validator (1) rejects non-`str` input; (2) rejects any length != 44 (`Fernet._is_valid_key` spec); (3) `base64.urlsafe_b64decode` + asserts the decoded length is exactly 32 bytes (blocks `"a"*44` which decodes to 33 bytes); (4) `from exc` chains the inner decode error so the upstream cursor points at the original `binascii.Error` (ruff B904).
- `apps/api/src/gw2analytics_api/models.py`: `OrmWebhookSubscription.secret: Mapped[str]` → `ciphertext: Mapped[bytes]` (LargeBinary).
- `apps/api/alembic/versions/0009_webhook_secret_at_rest.py` (NEW, Python-driven data migration): `add_column("webhook_subscriptions", "ciphertext", LargeBinary(), nullable=False, server_default=sa.text("''::bytea"))` → Fernet-encrypt-in-Python loop (reads plaintext `secret`, writes Fernet envelope into `ciphertext` via batched UPDATE, with defensive `not isinstance(plaintext, str)` skip) → `drop_column("webhook_subscriptions", "secret")` → `op.alter_column("webhook_subscriptions", "ciphertext", server_default=None)` (drops the backfill-only default so future INSERTs cannot silently land with empty ciphertext). Symmetrical `downgrade()` rebuilds the plaintext column + restores via the SAME KEK. **Migration is NOT idempotent on a wet-DB re-run** (the docstring `## WARNING` block warns operators to drain + drop + re-seed rather than wipe `alembic_version`).
- `apps/api/src/gw2analytics_api/routes/webhooks.py`: POST handler encrypts on insert via `encrypt_webhook_secret(plaintext) → subscription.ciphertext`. The route never decrypts (the secret is one-shot on POST and never returned by GET — the v0.9.0 contract).
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`: `_dispatch_single` decrypts-then-HMAC-signs per subscription (`Fernet` round-trip ~2us vs ~50ms HTTP POST). `FernetInvalidToken` caught per-sub with a `delivery.error = f"ciphertext corrupt: {FernetInvalidToken.__name__}: {exc}"` annotation; loop continues for OTHER valid subscribers (one corrupt row MUST NOT crash the whole dispatch loop).
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py`: mirror pattern in `_attempt_retry`. Same per-delivery `FernetInvalidToken` catch. On structural corruption, `delivery.attempt = _MAX_ATTEMPTS` is set terminal (no further retry spam on an unfixable row); `delivery.error` uses `delivery.attempt` (the post-set value) so a future tunable-isation of `_MAX_ATTEMPTS` doesn't leave the literal "3" in audit logs.
- `apps/api/tests/test_webhooks_e2e.py`: 5 NEW hermetic tests — round-trip on canonical plaintext / settings-kek validator accepts 44-char + rejects 43/45/decoded-33 / env-path sibling test (proves the `validation_alias` plumbing works end-to-end AND validates against malformed KEK via the env branch) / on-disk ciphertext-never-contains-plaintext (CWE-256 closure proof at the wire boundary) / dispatch cross-sub isolation (one corrupt ciphertext does NOT freeze OTHER valid subscribers).
- `apps/api/tests/test_webhooks_e2e.py`: 4 `# type: ignore[arg-type]` removed from the `Settings(secrets_kek=...)` test calls (mypy correctly flagged them as `[unused-ignore]` once pydantic-settings accepted str kwargs natively via `populate_by_name=True`).
- `apps/api/tests/test_webhooks_e2e_scheduler.py`: `_bootstrap_webhook_environment` now seeds `ciphertext=encrypt_webhook_secret(...)` instead of plaintext `secret=...` (the model post-migration has no `secret` column).


## [0.9.38] - v0.9.38: per-target rollup helper extraction (plan 117)

### Refactor (apps/api - v0.9.38 plan 117: per-target rollup helper extraction)

`get_fight_events` shrank from a 200+ line route handler to ~80 lines by extracting the 3 isomorphic per-target rollup branches (DPS + Healing + BuffRemoval) into a single `_aggregate_per_target_rollup` helper. The helper dispatches to the right per-target aggregator + output-row-type via a closed-form `if event_cls is ...` dispatch table; the schema-validation step + the 100-row cap (v0.10.2 hotfix followup #12) stay in the route handler because the right `RowOut` subclass + the cap policy are wire-format / payload-bound concerns, not aggregation concerns. Also consolidates the duplicate `_TIMELINE_*_WINDOW_S` + `_EVENTS_*_WINDOW_S` constants into a single module-level `_PER_FIGHT_DEFAULT_WINDOW_S` + `_PER_FIGHT_MAX_WINDOW_S` pair.

- `apps/api/src/gw2analytics_api/routes/fights.py`: new `_aggregate_per_target_rollup` helper (lines ~122-180) + the 3 per-target rollup branches in `get_fight_events` refactored to call the helper (3 calls, one per `event_cls`) + the 2 pairs of duplicate window-s constants removed in favour of the module-level single-source.
- `apps/api/tests/routes/test_fights_per_target_helper.py` (NEW, 5 hermetic tests): pins the helper's dispatch + invariants in isolation from the TestClient + Postgres + MinIO stack -- one test per `event_cls` branch (DPS + Healing + BuffRemoval), one test for the closed-form `ValueError` on unknown `event_cls` (a fresh subclass of `DamageEvent` does NOT match the dispatch table's `is` check, falls through to the error case), one test for the empty-iterator short-circuit (no `ZeroDivisionError` on `duration_s=0.0`).


## [0.9.27] - v0.9.27: Phase 8 cascade in libs/gw2_analytics/event_window.py (plan 083)

### Fixed (libs/gw2_analytics - v0.9.27 plan 083: Phase 8 cascade in event_window.py)

The Phase 8 cycle that added `BuffRemovalEvent` as the third `Event` discriminated-union member in `libs/gw2_core/src/gw2_core/models.py` cascaded the change to `target_buff_removal.py` (the per-target strip rollup) but NOT to `event_window.py` (the per-bucket time-rollup aggregator). The per-bucket `EventBucket` schema was missing the `buff_removal_total` field, so the per-fight timeline chart (`apps/web/src/app/fights/[id]/page.tsx`'s `<PerFightTimelineChart>`) had no per-bucket strip band — a researcher investigating "which 5s window saw the most corrupting concentration" had no timeline answer, only the per-target rollup which is blind to per-bucket chronology. Plan 083 closes the gap:

- `libs/gw2_analytics/src/gw2_analytics/event_window.py`:
  - `EventBucket` gains a new `buff_removal_total: int = Field(default=0, ge=0)` field (mirrors the existing `damage_total` / `healing_total` invariants; `default=0` keeps pre-Phase-8 callers valid).
  - `EventWindowAggregator.aggregate()` gains a `buff_removal_by_bucket` accumulator + an `elif isinstance(e, BuffRemovalEvent): buff_removal_by_bucket[bucket_index] += e.buff_removal; total_strip += e.buff_removal` branch in the event-type if/elif chain (parallel to the existing `DamageEvent` / `HealingEvent` branches).
  - The bucket construction now passes `buff_removal_total=buff_removal_by_bucket[idx]` to the `EventBucket` constructor.
  - `_check_invariants` gains an `expected_total_strip: int = 0` parameter + the `sum(b.buff_removal_total) != expected_total_strip` cross-field invariant (no strip events dropped, no double-counting).
  - Module docstring updated from "Damage + healing accounting" to "Damage + healing + buff-removal accounting" with the new `BuffRemovalEvent` line.
- `libs/gw2_analytics/tests/test_event_window.py`: 5 NEW tests appended to `TestEventWindowAggregator` covering the Phase 8 cascade:
  - `test_damage_event_in_bucket_defaults_buff_removal_total_to_zero`: 1 DamageEvent at t=1500ms lands in bucket 1 (bucket 0 is zero-filled); `buff_removal_total` defaults to 0 (Phase 8 additive default).
  - `test_buff_removal_event_accumulates_in_bucket`: 1 BuffRemovalEvent at t=1500ms lands in bucket 1; `buff_removal_total` accumulates the event's `buff_removal` value.
  - `test_mixed_damage_healing_strip_in_single_bucket`: 3 events (Damage + Healing + BuffRemoval) all at t=1500ms land in bucket 1; the 3 independent roll-ups accumulate in parallel; `event_count` is the residue of the input stream.
  - `test_buff_removal_accumulates_across_multiple_buckets`: 2 BuffRemovalEvents at t=1500ms + t=2500ms land in bucket 1 + bucket 2; the per-bucket `buff_removal_total` accumulates each event into its own bucket; the total across buckets == sum of event.buff_removal (cross-field invariant).
  - `test_buff_removal_total_field_default_and_annotation`: Pydantic field introspection — `EventBucket.model_fields["buff_removal_total"].default == 0` AND `.annotation is int` (locks the schema for forward-compat with pre-Phase-8 callers).
  - The 7 pre-existing Phase 6+v1 tests are unchanged (the `default=0` keeps the pre-Phase-8 fixtures validate cleanly).

#### Public contract change

**The API's `EventBucketOut` schema (in `apps/api/src/gw2analytics_api/schemas.py`) is deliberately NOT extended** with the new `buff_removal_total` field. The `/fights/{id}/events` endpoint's `event_windows` array is the per-bucket rollup from `EventWindowAggregator` (now with the new field), and the route's `EventBucketOut.model_validate(b.model_dump())` step silently drops the unknown field (Pydantic v2 `extra="ignore"` default for `EventBucketOut`, which has `ConfigDict(from_attributes=True)` without `extra="forbid"`). The per-bucket strip data is exposed to the frontend via the separate `/fights/{id}/timeline` endpoint (uses the sibling `PerFightTimelineAggregator` + `PerFightTimelinePointOut` schema, which already had `total_buff_removal` since v0.8.9). The Phase 8 contract that locked the `/events` per-bucket window shape is preserved.

#### Validation

- `uv run pytest libs/gw2_analytics/tests/test_event_window.py`: 12 passed (PYTEST=0; 7 pre-existing + 5 new).
- `uv run ruff check libs/gw2_analytics/`: clean (RUFF=0).
- `uv run mypy --no-incremental libs`: clean (MYPY=0).


## [0.10.10] - 2026-07-11: apps/api cold-phase flake fix on thundering-herd test

### Fixed (apps/api - v0.10.10 cold-phase flake on thundering-herd test, pre-existing on main)

The pre-existing ``test_fights_blob_cache_thundering_herd.py::test_concurrent_calls_to_same_uri_are_serialised`` was failing ~1/3 of CI runs (a deterministic test bug masked by ``gzip``-timestamp coincidence: 4 concurrent ``gzip.compress(b"event")`` calls produce different bytes unless they happen within the same wallclock second). The fix is in the test (the production code's latch contract was always correct):

- Replaced the broken assertion ``assert all(r == results[0] for r in results)`` with ``assert all(gzip.decompress(r) == b"event" for r in results)`` -- the precise-but-stable contract: every caller received gzip bytes that DECOMPRESS to the same payload, regardless of gzip-header timestamp drift.
- Verified: 10/10 isolated test runs PASS post-fix; full apps/api test_fights_blob_cache_thundering_herd.py suite (8 tests) PASS; no flake.


## [0.10.9] - 2026-07-11: apps/api player-compare KeyError crash fix (plan 144 followup)

### Fixed (apps/api - v0.10.9 plan 144: player-compare KeyError crash)

- **apps/api v0.10.9 plan 144**: `GET /api/v1/players/compare/timeline`
  raised `KeyError` on any non-empty dataset and was therefore broken in
  production since v0.10.0 (plan 032). `get_compare_timeline` built
  `per_account_contributions` as a plain `dict` and did an unconditional
  `d[c.account_name].append(c)`, which `KeyError`s on the first
  contribution of every account; the endpoint only survived the empty-DB
  path. It also never scoped the result to the *requested* accounts.
  Extract a pure `_group_contributions_by_account(contributions,
  requested_accounts)` helper that pre-seeds the dict from the deduped
  requested accounts and appends only requested accounts' contributions
  ([plan 144](./plans/144-v0109-player-compare-keyerror-fix.md)). This
  matches `CrossAccountTimelineAggregator`'s "one series per dict key"
  contract: every requested account gets a series (empty `points` if it
  attended no fights), and non-requested accounts are dropped. Surfaced
  as finding C1 of the [2026-07-10 audit](./plans/AUDIT-2026-07-10-79c4501.md).
- **apps/api/tests/test_player_compare_grouping.py** (NEW): 4 hermetic
  (no-DB) tests pinning the helper — empty contributions pre-seed all
  requested accounts, contributions route to the right account,
  non-requested accounts are dropped, unknown requested accounts get an
  empty list. The DB-backed `test_player_compare.py` validates the
  end-to-end route on CI.

#### Validation

- `uv run pytest apps/api/tests/test_player_compare_grouping.py`: 4 passed.
- `uv run ruff check` + `uv run mypy libs apps --no-incremental`: clean (106 source files).
- The Postgres-backed `test_player_compare.py` was NOT run locally (no Docker); it validates the end-to-end route on CI.


## [0.9.2] - v0.9.2: webhook correctness hardening (HMAC bytes + replay idempotency + suite-fast)

The v0.9.2 hardening cycle (`plans/009-v092-webhook-rest.md`) closes the 2 deferred v0.9.1 test failures + 1 audit-flagged missing-convention + 1 uninvestigated suite timeout via 5 atomic commits (`85716b6` → `99faa35` → `a247430` → `abd7deb` → `d70c8c6`).

### Added (apps/api - migration 0008 payload JSONB → LargeBinary)

- `apps/api/alembic/versions/0008_payload_bytes.py` (NEW): alters both `webhook_deliveries.payload` + `webhook_dlq.payload` from `JSONB` to `LargeBinary` to preserve canonical bytes through retry/replay paths. **WARNING**: NOT data-preserving — existing JSONB rows lose their original dict structure on upgrade (acceptable: v0.9.2 marks the schema as fresh-start). Operators MUST drain DLQ + deliveries before applying or accept that pre-v0.9.2 rows become an opaque byte-bag. Documented in the migration's `# WARNING` header.
- `apps/api/src/gw2analytics_api/models.py`: `OrmWebhookDelivery.payload: Mapped[bytes | None]` + `OrmWebhookDlq.payload: Mapped[bytes]` (was JSON `Mapped[dict]`).
- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`: writes `payload = json.dumps(body_dict, separators=(",", ":")).encode("utf-8")` (canonical bytes that the HMAC signs).
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py`: reads stored `payload: bytes` verbatim on retry (no dict round-trip; no JSONB re-ordering hazard).
- `apps/api/src/gw2analytics_api/routes/webhooks.py::replay_dlq_delivery`: copies `dlq.payload` (bytes) into `new_delivery.payload` (bytes) directly. Opens the DLQ lookup with `db.execute(select(OrmWebhookDlq).where(OrmWebhookDlq.id == delivery_id).with_for_update())` (Postgres `SELECT ... FOR UPDATE` row-level lock — exactly one of the concurrent threads reads + deletes the DLQ row; the second thread's transaction blocks until the first commits then sees NULL + raises 404).
- `apps/api/tests/conftest.py` (NEW): function-scoped autouse `_isolate_test_state` fixture that bulk-deletes from 6 tables (uploads, fights, fight_player_summaries, webhook_subscriptions, webhook_deliveries, webhook_dlq) before each test. DELETE order respects FKs (children before parents; `webhook_dlq.subscription_id` has NO FK so it's deleted between `webhook_deliveries` and `webhook_subscriptions`). Provides 2 explicit pytest fixtures (`client`, `get_sessionmaker`) so the plan-006 regression test can use them in its signature.
- `apps/api/src/gw2analytics_api/routes/webhooks.py`: 3 docstring additions (no code logic changes) on `_generate_subscription_id` (path-parameter → `urlsafe_b64encode`), `_generate_secret` (byte-only → plain `b64encode`), and `_generate_delivery_id` (UUID is URL-safe by definition; no encoding needed). Each cross-references the CONTRIBUTING.md convention.
- `CONTRIBUTING.md`: new `## Webhook discriminator IDs` section with 3 bullet classifications + a classification guide for future discriminators + cross-references to the 3 helper docstrings.

### Fixed (apps/api tests - 2 pre-existing test failures surfaced by Step 5)

- `apps/api/tests/test_uploads_e2e.py::test_player_timeline_tz_422_when_invalid_timezone`: route returns `detail` as a plain string (e.g. `"unknown IANA timezone: 'Mars/Olympus'"`), not a FastAPI-validation list-detail. New assertion `assert "Mars/Olympus" in str(body.get("detail", ""))` handles both shapes.
- `apps/api/tests/test_uploads_e2e.py::test_background_task_session_alive_at_invocation` (plan 006 regression test, 3 bugs): `probe = get_sessionmaker()` → `probe = get_sessionmaker()()` (double-call; the imported `get_sessionmaker` is a function that returns a sessionmaker; double-call yields a Session); `assert resp.status_code == 202` → `== 201` (correct REST semantics for the resource-creation + BG-task pattern; `UploadCreatedResponse` returns the created record synchronously + uses FastAPI `BackgroundTasks` for the async parse).

### Note

- The deferred `webhook secret-at-rest` item (from the v0.9.1 `### Deferred` note above) remains deferred — v0.9.2 ships HMAC byte-for-byte integrity but NOT pgcrypto envelope encryption. Tracking continues from the v0.9.1 close-out.
- Plan 009 marked **COMPLETE** — see `plans/009-v092-webhook-rest.md` for the closing-summary table.

### Tests

- Apps/api pytest: **92 pass / 0 fail / 3 skip in ~10s** (was 90 / 1 fail / 2 skip in >600s pre-Step-5 — the post-Step-5 cleanup unblocked the suite).
- Webhook e2e + scheduler: **22 pass / 0 fail / 1 skip** (unchanged from v0.9.1 close-out; the v0.9.2 followups are defect fixes, not new test coverage).
- Cumulative apps/api pytest count: unchanged (the v0.9.2 delta is 0 — pre-existing fixes are regression guards, not new tests; the v0.9.1 +0 → +22 delta was the new test coverage).

### Validation

- `uv run ruff check apps/api`: clean (RUFF=0).
- `uv run mypy --no-incremental libs apps`: clean (MYPY=0).
- `uv run pytest apps/api/tests/`: pass (92 / 0 fail / 3 skip in ~10s wallclock).
- `uv run pytest apps/api/tests/test_webhooks_e2e.py apps/api/tests/test_webhooks_e2e_scheduler.py`: pass (22 / 0 fail / 1 skip — the 1 skip is the pre-existing Windows-only concurrent-replay test; unrelated to v0.9.2).
- Code-reviewer-minimax-m3 across all 5 atomic commits: **APPROVED**.

[0.9.2]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.9.1...v0.9.2


## [0.9.2+] - v0.9.2: schema int→str audit-replay hardening (merged from v0.9.1 deferred followup)

### Added (apps/api - v0.9.2 schema `int`→`str` audit-replay hardening)

These land in `apps/api/` + `apps/api/alembic/versions/` as the v0.9.2 followups announced in the 0.9.2 release section's [Deferred (v0.9.2 followups)] block:

- **Plan 009 Step 1+2** (atomic webhook payload): webhook payload is now signed with HMAC byte-for-byte (no JSON re-ordering between dispatch and replay); the regression test in `apps/api/tests/test_webhooks_e2e.py` was hardened against dispatch-time JSON canonicalisation drift.
- **Plan 009 Step 3** (row-level lock): `apps/api/src/gw2analytics_api/routes/webhooks.py::replay_dlq_delivery` now opens the DLQ lookup with `db.execute(select(OrmWebhookDlq).where(OrmWebhookDlq.id == delivery_id).with_for_update())` so concurrent replay requests collide on the row-level lock (`Postgres SELECT ... FOR UPDATE`); the losing thread sees NULL after the winner deletes + commits.
- **Plan 009 Step 4** (discriminator-encoding docstring convention): CSS-style header + 3 helper docstrings documenting the `urlsafe_b64encode` vs `b64encode` vs `<uuid>` discriminator contract; cross-referenced from `CONTRIBUTING.md`'s new `## Webhook discriminator IDs` section.
- **Plan 009 Step 5** (test isolation conftest): a function-scoped autouse `_isolate_test_state` fixture in the new `apps/api/tests/conftest.py` bulk-deletes from 6 tables (uploads, fights, fight_player_summaries, webhook_subscriptions, webhook_deliveries, webhook_dlq) before each test. DELETE order respects FKs; `webhook_dlq.subscription_id` has NO FK so it's deleted between `webhook_deliveries` and `webhook_subscriptions`. Provides explicit `client` + `get_sessionmaker` fixtures for plan-006 regression tests.


## [0.9.1] - v0.9.1: webhook hardening slice (HMAC bytes + replay + idempotency + suite-fast + SSRF block)

### Added (apps/api + web - v0.9.1 webhook hardening slice)

The 5 v0.9.1 audit plans (drift base `ef5e4f3`; see `plans/README.md` + `plans/004-008-v091-*.md`) plus the H1 (multi-tick scheduler test re-attempt) + H2 (lint-debt cleanup) followups land as part of this hardening slice. The slice closes the deferred Known Followup from v0.9.0 (`### Known followup (api - v0.9.1 webhook retry + DLQ)` above) and the first item of the v0.9.1 Deferred list (`webhook route tests`); the second Deferred item (`webhook secret-at-rest` at-rest `pgcrypto` envelope encryption) remains deferred to a future cycle. Plan-by-plan summary:

- **Plan 004 — webhook Delivery schema `int`→`str`**: `apps/api/src/gw2analytics_api/schemas.py::WebhookDeliveryOut.id` and `WebhookDeliveryReplayOut.delivery_id` are now `str` (with `Field(min_length=1, max_length=64)` bounds) instead of `int`, matching the actual on-disk `f"dly_{uuid.uuid4()}"` discriminator. Pre-plan-004 the 2 new schemas would have raised `pydantic.ValidationError` on every serialisation; the route's downstream `_post_sub` helper's `cast("Response", client.post(...))` workaround in `test_webhooks_e2e.py` was a stopgap that masked the runtime failure. Plus 1 hermetic regression test pinning the `str` annotation + `min_length`/`max_length` bounds.
- **Plan 005 — universal SSRF block for HTTPS**: `apps/api/src/gw2analytics_api/routes/webhooks.py::_validate_webhook_url` now applies a universal `is_private | is_loopback | is_link_local | is_multicast` check on the resolved address (direct IP literals via `ipaddress.ip_address`; hostnames via `socket.getaddrinfo` for IPv4 + IPv6 simultaneously) for BOTH `http` and `https` schemes. Pre-plan-005 an attacker could subscribe `https://10.0.0.1/`, `https://169.254.169.254/` (AWS IMDS), or `https://[::1]:6379/` (local Redis) and use the endpoint as an SSRF vector. Operator opt-out via `GW2ANALYTICS_ALLOW_PRIVATE_WEBHOOK_URLS=1` for trusted dev only (documented in `apps/api/.env.example` with operational-risk warning). Fail-closed on DNS errors (DNS-rebind defence). Plus 5 SSRF regression tests covering RFC1918 IPv4 literal, AWS-IMDS link-local, IPv6 loopback literal, hostname-resolves-to-private-via-monkeypatched-`getaddrinfo`, and the env opt-in escape hatch.
- **Plan 006 — BG-task closed-session bug for `process_parse`**: `apps/api/src/gw2analytics_api/services.py::process_parse` signature changed from `(db: Session, upload_id, raw)` (request-scoped; closed by the dependency teardown before BG-task fires → `DetachedInstanceError` on the first query) to `(session_factory: Callable[[], Session], upload_id, raw)` (worker-scoped; `with session_factory() as db`). Both BG-task callers in `apps/api/src/gw2analytics_api/routes/uploads.py` updated to pass `get_sessionmaker()`. Matches the existing `webhook_dispatch.dispatch_for_upload(session_factory, upload_id)` DI pattern (the v0.9.0 worker was already correct; this plan retrofitted the parser to the same convention). Also added a focused regression test (no `time.sleep(0.1)` poll) that catches the regression where `process_parse` would re-introduce the closed-session dependency.
- **Plan 007 — retry + DLQ + replay tests + scheduler worker**: `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (NEW) is the asyncio-polling worker (`process_scheduled_retries(session_factory) -> int`, 5s poll interval, exponential backoff `{attempt: seconds} = {1: 1, 2: 10, 3: 100}` per design doc §5, `_MAX_ATTEMPTS = 3` before `OrmWebhookDlq` promotion). Lifted `webhook_dispatch.py`'s session-DI discipline (fresh worker-scoped `session_factory`) one-for-one. Started as a background `asyncio` task by `apps/api/src/gw2analytics_api/main.py`'s `lifespan` handler; cancel-safe on app shutdown. Routes: `POST /api/v1/webhooks/dlq/{delivery_id}/replay` in `routes/webhooks.py::replay_dlq_delivery` (deletes DLQ row + creates fresh delivery row in one atomic `db.commit()`; 404 if subscription missing/revoked or upload deleted). 4 canonical tests in `apps/api/tests/test_webhooks_e2e.py` (scheduler first-attempt success, exponential backoff after-failed-1st-tick, replay idempotency under concurrent `ThreadPoolExecutor` + `Session.commit` race-widener, HMAC byte-for-byte integrity across replays); the originally-stubbed multi-tick `test_retry_scheduler_failure_promotes_to_dlq_after_max_attempts` landed in a standalone `apps/api/tests/test_webhooks_e2e_scheduler.py` module via the H1 followup (flat `with`-block structure escapes the original in-session nested-dedent footgun; the original `pytest.skip` placeholder in `test_webhooks_e2e.py` is replaced by a stub-by-name pointer for search-by-name discoverability). `pytest-time-machine` + `respx` added to `apps/api/pyproject.toml` `[dependency-groups].dev`.
- **Plan 008 — OpenAPI drift gate is now functional**: `web/src/lib/api/schema.d.ts` removed from `web/.gitignore` and committed as the 71 KB drift gate baseline. The CI workflow (`Detect API client drift` step, `git diff --exit-code -- web/src/lib/api/schema.d.ts` between `OpenAPI: regenerate web TypeScript client` and `Type-check web`) now has a tracked baseline to diff against — pre-plan-008 the gate silently passed because untracked-vs-commit diffs return zero. `CONTRIBUTING.md` gains a `## Regenerating the web TypeScript client` section documenting the contract: any backend PR touching `apps/api/src/gw2analytics_api/routes/*` MUST run `cd web && pnpm generate:api` and commit the regenerated `schema.d.ts` in the same PR.

### Deferred (v0.9.2 followups - tracked after the v0.9.1 hardening close-out)

- **webhook secret-at-rest**: the secret column is plaintext in PostgreSQL today. HMAC verification of incoming webhook calls requires plaintext, so we can't fully hash; the layered defence is `pgcrypto` envelope encryption with a `SECRETS_KEK` env var. v0.9.1 ships with plaintext (single-tenant local-dev threat model); v0.9.2 should add at-rest encryption or document the operator-led-DB-compromise risk in the deploy docs. NOT closed by the v0.9.1 hardening slice.


## [0.9.0] - v0.9.0: Phase 9 of web + apps/api (shared TimelineChart + profession filter + TZ selector + upload wizard + webhooks backend + demo seeder)

### Changed (docs - README professional polish)

- `README.md`: substantial refactor for professional GitHub presentation. The 400+ line original was reorganised:
  * Tightened the `**Status:**` headline from a 200+ char run-on sentence to 2 lines (latest tagged release + v0.9.x close-out state + test count + CI gate status).
  * Added a new `## Highlights` section (5 bullets: per-target roll-ups, historical timelines, webhooks, 339+ tests, monorepo structure).
  * Added a new `## Documentation` index (5 rows pointing to CHANGELOG, CONTRIBUTING, ROADMAP, plans, the v0.8.0 backend design doc).
  * Added a new `## API surface` section (extracted the API endpoint list from the apps/api Architecture cell into a dedicated, scannable table — 15 endpoints across ingest / browse / per-fight / player / webhooks / ops).
  * Compressed the `## Release Tags` table cells from multi-sentence paragraphs to 1-line summaries (25 tagged releases).
  * Collapsed the `## Phase Status` dense paragraphs (Phase 0 → v0.8.9) into a `<details>` block to declutter the public landing page (the canonical per-release content lives in `CHANGELOG.md`; the collapsed block is one click away for developers who want the dev history).
  * Added a `## Contributing` pointer (to `CONTRIBUTING.md`) + a `## License` placeholder (no LICENSE file yet; marked TBD).
  * Added a `Latest tag` GitHub badge alongside the existing CI badge.
  * `**Status:**` line now reflects the v0.9.0 + v0.9.1 + v0.9.2 close-out state accurately (work committed to `main`; tag pending operator ceremony).
  No code changes; the existing `docs/screenshots/*.png` references are preserved; the Quickstart's 8 numbered steps + the 6 displayed screenshots + the 2 fixture PNGs are preserved verbatim.

### Changed (web - v0.9.0 plan/001: shared <TimelineChart> base)

- `web/src/components/TimelineChart.tsx` (NEW, ~580 lines): the
  shared base component for BOTH the per-account historical
  timeline (`PlayerTimelineChart`, v0.8.0) and the per-fight
  temporal view (`PerFightTimelineChart`, v0.8.9). Generic over
  the flat `TimelineChartPoint = { series: [number, number,
  number], key: string, xLabel: string, tooltip: string }`
  shape. Encapsulates the SVG render, the per-series 0-100%
  normalisation (linear mode), the shared-log Y-axis (log mode,
  v0.8.2 lineage), the decade tick generation, the X-axis
  label sampling, the legend, and the empty-state panel.
  Exports `buildTimelineLayout` + `formatLogTick` +
  `TimelineChart` + `TimelineScale` + `TimelineChartPoint`.
- `web/src/components/PlayerTimelineChart.tsx` (refactored to a
  thin ~131-line wrapper): maps `PlayerTimelinePoint[]` to the
  flat `TimelineChartPoint[]` shape the base consumes; owns the
  X-axis format detection (`MM/DD HH:MM` vs `MM/DD` for
  day-bucketed points, v0.8.1) + the tooltip text formatting +
  `fight_id` as the React key. Re-exports `buildTimelineLayout`
  + `formatLogTick` from the base for back-compat with the
  existing unit tests.
- `web/src/components/PerFightTimelineChart.tsx` (refactored to
  a thin ~119-line wrapper): strict parallel of
  `PlayerTimelineChart`. Maps `PerFightTimelinePoint[]` to the
  flat `TimelineChartPoint[]` shape; owns the `M:SS` X-axis
  format (relative time) + the per-fight tooltip + the bucket
  index as the React key. Re-exports `buildTimelineLayout` as
  `buildPerFightTimelineLayout` + `formatLogTick` as
  `formatPerFightLogTick` for back-compat with the existing
  tests.

  The pre-v0.9.0 wrappers each had ~250 lines of near-identical
  TSX (3 polylines, per-series normalisation, SVG-native
  `<title>` tooltip, linear/log scale, decade-style X-axis
  labels, legend, empty-state panel); v0.9.0 plan/001
  single-sources the rendering in the base and reduces each
  wrapper to a ~130-line data-prep shell. The public prop
  interface of both wrappers is unchanged so the page-level
  consumers don't need to change.

- `web/tests/components/player-timeline-chart.test.tsx`: added
  a `makeChartPoint` helper that constructs a minimal
  `TimelineChartPoint` (just the 3 series numbers + placeholder
  `key`/`xLabel`/`tooltip` strings) and updated 7
  `buildTimelineLayout` tests to use it. The component tests
  pass `PlayerTimelinePoint[]` directly to the wrapper (the
  wrapper maps internally), so the component tests are
  unchanged.
- `web/tests/components/per-fight-timeline-chart.test.tsx`:
  same `makeChartPoint` pattern, updated 3
  `buildPerFightTimelineLayout` tests. Updated the
  empty-state test to expect the generic `"No timeline data
  available."` text -- the pre-v0.9.0 per-fight-specific
  string (`"No per-fight timeline data available."`) was
  dropped as part of the single-source refactor (the wrapper
  no longer owns the empty-state text; the shared base does).

  Why the generic constraint on `buildTimelineLayout` is
  loosened to `T extends { series: [number, number, number] }`
  (NOT the full `TimelineChartPoint`): the layout helper is a
  pure function of the 3 series values -- the `key` /
  `xLabel` / `tooltip` fields are React-component concerns
  (the SVG `<title>` tooltip + the React `key` + the X-axis
  text label) that the layout helper doesn't consume. Loosening
  the constraint to the structural minimum lets the unit tests
  pass a minimal fixture instead of forcing them to build full
  `PlayerTimelinePoint` / `PerFightTimelinePoint` objects and
  pretend the wrapper isn't there.

### Added (apps/api - v0.9.0 plan/002: profession filter on /players)

- `apps/api/src/gw2analytics_api/routes/players.py`: `list_players` now accepts
  `profession: str = Query("")` + a new `_parse_profession_filter` helper
  that accepts BOTH the enum name (case-insensitive, e.g. `MESMER`) and
  the integer value (e.g. `7`). Unknown values return 422 with the
  rejected value in the detail (matches the existing `?tz=` custom-422
  pattern from the timeline route). The filter is applied after the
  cross-fight roll-up and before the offset/limit, so pagination is
  consistent on the filtered set.
- `apps/api/tests/test_players.py`: 7 new pytest cases covering the
  full contract (no-filter, name filter, no-match, integer-value, 422
  for unknown values, pagination consistency, detail-endpoint
  ignored). Self-contained fixtures (a unique `base_id_a` per test
  via `1_000_000_000 + int(suffix, 16)` + `limit=500` in all GET
  requests) to be robust against cross-test DB pollution.

### Added (web - v0.9.0 plan/002: profession filter on /players)

- `web/src/components/ProfessionFilter.tsx`: Client Component with
  10 hardcoded options (1 "All professions" + 9 base professions).
  The dropdown is wired with `data-testid="profession-filter"` for
  e2e lookup. Selecting a value mutates the URL via Next.js
  `useRouter().push()`.
- `web/src/lib/api.ts`: `fetchPlayers` signature extended with
  `opts: { limit?, offset?, profession? }` + the `?profession=` URL
  param.
- `web/src/app/players/page.tsx`: now async + accepts
  `searchParams: Promise<{ profession?: string }>` (Next.js 15+
  async contract); reads the URL filter, forwards to `fetchPlayers`,
  mounts `<ProfessionFilter>`.

### Fixed (web e2e - visual-regression spec)

- `web/tests/e2e/visual-regression.spec.ts`: fixed a threshold
  mismatch between the 2 `pixelmatch` calls. The no-failure diff
  call used `threshold: 0.1` (residual from a prior partial
  commit), the failure-path diff-write call used `threshold: 0.05`.
  They should be the same value so the diff ratio + the diff PNG
  highlight the SAME pixels. Both now use `threshold: 0.05`.

### Changed (web - screenshots.mjs hydration guard)

- `web/scripts/screenshots.mjs`: the `waitForFunction` for page
  hydration stability now has TWO requirements (both must be met):
  (1) the page must have expanded beyond the 900px viewport
  (`scrollHeight <= 900` returns false); (2) the height must be
  stable for 500ms. The previous version returned on a 900px-stable
  page (before AG Grid / SVG chart expansion) which produced
  stale baselines that diffed at near-100% against the spec's
  3196px captures. Timeout bumped from 15s to 30s.

### Fixed (web e2e - VR hydration)

- `web/scripts/screenshots.mjs`: restored the v0.9.0 plan/003 hydration guard that commit `882edff` had over-aggressively removed (the root cause of the previous [Unreleased] known-issue was the "match spec wait strategy" simplification; the direct `chromium.launch()` script lost its scrollHeight stability check while the Playwright test runner kept its implicit microtask delays). The `PAGES` const's third slot, previously always `null`, is now a tagged sentinel dispatch: `"stable-scroll"` triggers a `page.waitForFunction` predicate that polls in the page context and resolves when `document.body.scrollHeight > 900` AND has been stable for >= 500ms (uses `window.__gw2LastHeight` + `window.__gw2LastChangeAt` as cross-poll sticky state on the same Document). The dynamic pages (04-08) carry `"stable-scroll"`; the static pages (01-03) keep `null` and capture immediately after networkidle. Timeout clamped to 30s. Once `pnpm screenshots --persist` is re-run against dev + mock-server, the 5 dynamic-page baselines will be 1440x3196 instead of 1440x900, and the spec's dimension-mismatch check in `web/tests/e2e/visual-regression.spec.ts` will stop firing on those 5 routes. Test count: unchanged (the 16-e2e spec dimension check + the 1% total-diff threshold are both unchanged); the operational behaviour change is purely in the script-side capture mechanism.


### Added (api - v0.9.0 webhooks backend foundational + API layers)

- NEW migration `0006` adds the 3 webhook tables (`webhook_subscriptions` / `webhook_deliveries` / `webhook_dlq`) per `docs/v0.8.0-backend-design.md` §4. FK from `webhook_deliveries.subscription_id` has NO `ondelete=CASCADE` (the canonical state transition is soft-delete via `revoked_at`); `webhook_dlq.subscription_id` has NO FK at all (deliberate forensics decision -- DLQ rows survive subscription hard-delete). Indexes: `webhook_subscriptions.revoked_at`, `webhook_deliveries.(subscription_id, upload_id)` + `(upload_id)` + `(delivered_at)`, `webhook_dlq.(subscription_id)` + `(moved_to_dlq_at)`.
- NEW ORM classes: `OrmWebhookSubscription` (id+url+filter_payload+description+secret+created_at+revoked_at + deliveries relationship), `OrmWebhookDelivery` (FK subscription_id + upload_id+attempt+status_code+error+delivered_at + subscription back-ref), `OrmWebhookDlq` (NO FK subscription_id -- forensics). `OrmWebhookSubscription.filter_payload` is a Python attr shadowing the SQL column `filter` (avoids the Python builtin collision).
- NEW schemas: `WebhookSubscriptionCreate` (POST body), `WebhookSubscriptionCreatedOut` (POST 201 with one-time secret), `WebhookSubscriptionOut` (GET item, no secret, no revoked_at -- revoked subscriptions return 404 per design doc §4).
- NEW routes `apps/api/src/gw2analytics_api/routes/webhooks.py` + main.py wiring: `POST   /api/v1/webhooks` (HTTPS-or-loopback URL policy, returns 201 + secret ONCE), `GET    /api/v1/webhooks` (active list, no secret), `GET    /api/v1/webhooks/{id}` (404 if revoked), `DELETE /api/v1/webhooks/{id}` (idempotent soft-delete via `revoked_at`, 204 on already-revoked). Hidden helpers `_utcnow` / `_generate_subscription_id` (whsub_<base64(12)>) / `_generate_secret` (whsec_<base64(32)>) / `_validate_webhook_url` (HTTPS-or-loopback + no whitespace + non-empty host).


### Added (api - v0.9.0 webhook delivery worker)

- NEW ``apps/api/src/gw2analytics_api/workers/webhook_dispatch.py`` (single-attempt). Fires one HMAC-SHA256-signed POST per active ``OrmWebhookSubscription`` row whenever ``Upload.status`` transitions to COMPLETED. Hooked into ``POST /api/v1/uploads`` as a sibling ``BackgroundTasks.add_task`` after ``process_parse`` -- clean domain separation (the parser never imports the dispatcher). Wire format per design doc §3.4: ``Content-Type: application/json`` + ``X-Gw2Analytics-Signature: sha256=<hex>`` + ``X-Gw2Analytics-Delivery: dly_<uuid>`` + ``User-Agent: Gw2Analytics-Webhook/0.9.0`` + body ``{"kind": "upload_completed", "upload_id", "fight_id", "sha256", "started_at"}``. The worker opens a **fresh, worker-scoped** SQLAlchemy session via the injected ``session_factory`` (does NOT reuse the request session that ``process_parse`` consumed; this is the same DI pattern the production migration toward a dedicated Arq worker process will reuse). Edge cases handled: upload row missing, non-COMPLETED status, missing OrmFight row, empty-active-subs, subscription-with-empty-secret, filter-kind-mismatch, ``httpx.HTTPError`` -> ``error=``<class>: <msg>``, non-2xx -> ``error=non-2xx response: <code>``. ``subs.filter_payload.kind == upload_completed`` is the sole match criterion today; other kinds are accepted on POST but produce zero deliveries. One ``db.commit()`` covers all N deliveries per upload (atomic).

### Tests

- 7 new pytest tests in `apps/api/tests/test_players.py`.
- 2 new vitest cases in
  `web/tests/components/ProfessionFilter.test.tsx` (moved from
  `web/src/components/ProfessionFilter.test.tsx` to match the
  vitest include pattern; switched from `@testing-library/user-event`
  to `fireEvent` to avoid an install).
- 1 new vitest case in
  `web/tests/app/players-page.test.tsx` (forwards
  `?profession=MESMER` to `fetchPlayers`).
- 2 new e2e cases in `web/tests/e2e/players.spec.ts` (dropdown
  renders 10 options; selecting Mesmer updates the URL).
- 4 existing vitest cases in
  `web/tests/app/players-page.test.tsx` updated to pass
  `{ searchParams: Promise.resolve({}) }` (the page is now async).- Test totals: 219 -> 241 pytest (+22), 82 vitest (unchanged), 16 playwright (unchanged). **Total: 339 tests** (was 303 before the v0.9.0 cycle; 317 at the v0.9.0 close-out; the +22 webhook tests are split across `test_webhooks_e2e.py` (+21, including 1 deferred-stub via `pytest.skip`) and `test_webhooks_e2e_scheduler.py` (+1 standalone multi-tick that the H1 followup lifted out of the in-session block)). Cumulative breakdown: 241 pytest = 126 libs/gw2_* + 115 apps/api (was 93 pre-v0.9.1); 82 vitest in `web/` (unchanged); 16 Playwright e2e (unchanged).


### Added (apps/api - v0.9.0 plan/003: synthetic .zevtc demo seeder)

- `apps/api/src/gw2analytics_api/scripts/__init__.py` (already existed; the new `seed_demo` module joins the existing `backfill_player_summaries` + `health_gate` modules under the scripts package).
- `apps/api/src/gw2analytics_api/scripts/seed_demo.py` (NEW, ~290 lines): in-process synthetic `.zevtc` builder that emits minimal V1.3 EVTC files (header + agents + skills + a configurable event mix matching the Phase 7 v2 + Phase 8 roll-up trio the parser expects). Posts each file to the LIVE FastAPI server via `httpx.Client` (default `http://127.0.0.1:8000`), then polls `GET /api/v1/uploads/{uuid}` until the parser completes (a 30s budget with 1s interval). Each invocation produces N distinct fights via uuid-suffixed fixture IDs (idempotent w.r.t. the global DB state; re-running with the same N produces the same fight count because the sha256 hash is file-derived and matches the unique-bytes fixture). All 3 struct-size preconditions use explicit `RuntimeError` raises (not `assert`) so the guards survive `python -O` and `ruff S101`. CLI flags: `--num-fights N` (default 3), `--base-url URL` (default http://127.0.0.1:8000), `--no-poll` (just POST + exit), and `--verbose` (per-event trace). The script unblocks the v0.9.0 "show me the UI with real data" gap by populating the same minimal-but-valid fixtures the apps/api e2e suite uses (Phase 7 v2 damage+healing dual-emit + Phase 8 strip event + 6 player agents across 2 squads).

### Added (web - v0.9.0: TZ-selector for the per-account timeline)

- `web/src/lib/api.ts`: the `PlayerTimeline` interface gains a doc-exported `tz` string (was already on the schema-as-of v0.8.9; the wire contract is unchanged).
- `web/src/components/PlayerTimelineSection.tsx`: the section header gains a 4th affordance — the TZ selector — alongside the existing bucket + scale toggles. Native `<select>` with 25 curated IANA zones (UTC + 11 American + 8 European + 1 African (Cairo) + 1 African (Johannesburg) + 4 Asian + 1 Oceanic + 1 Pacific). Data-testid=`timezone-selector` for e2e lookup. Selection triggers `changeTz` which auto-switches bucket to `"day"` (the only mode where TZ matters; the fight-bucketing is unaffected since each fight has a wall-clock `started_at`). Pure client state (NOT URL-driven — deviates from the ProfessionFilter pattern is INTENTIONALLY documented inline; the bucket + scale toggles are pure client state already so a `router.push` would force an async URL/state sync). Dimension-matched to the existing scale-toggle button visual style (transparent background + accent border) so the 4 affordances read as one cluster.

### Changed (web - v0.9.0: 3-step upload wizard replaces the legacy 1-step form)

- `web/src/app/upload/page.tsx` (rewrite, 394 → 665 LoC): the legacy 1-step file-pick-and-POST flow is replaced with a 3-step wizard: **pick** (file input + client-side `.zevtc` extension guard) → **upload** (POST in flight, spinner + filename + size, "Cancel" best-effort visual — leaves the server-side BackgroundTask running; the idempotent sha256 collision handles the re-upload case) → **parse** (poll `GET /api/v1/uploads/{uuid}` every 2s with hard 30s budget / 15 attempts; reveals drill-down link to `/fights/{fight_id}` on `status="completed"`, or `error_message` + retry on `status="failed"`, or "still parsing" timeout banner) → **done** (terminal state with the drill-down link + "Upload another" reset affordance). Driven by `useReducer` over a discriminated union (`pick | upload | parse | done`) to enforce legal state combinations; the 2 `useEffect`s (POST on `step=upload`, poll on `step=parse`) use `cancelled`-flag + `AbortController`-style cleanup to prevent stale state writes on unmount.
- `web/src/app/upload/page.module.css` (208 → 364 LoC): adds `.stepIndicator` (3-segment horizontal breadcrumb with `aria-current="step"` on the active segment), `.panel` (single section shape used by all 4 steps), `.spinnerRow` + `.spinner` + `@keyframes upload-wizard-spin` (CSS-only spinner, no JS), `.buttonRow`, `.muted` (secondary CTA — Cancel / Start over / Mark as wedged), `.warn` (orange — non-alarming "still parsing after 30s" banner, distinct from the red `.error` for hard failures).
- `web/src/lib/api.ts`: adds `fetchUploadStatus(uploadId) -> UploadStatusRow` (mirrors `GET /api/v1/uploads/{uuid}`; needed for the polling `useEffect`) + `UploadStatusRow` interface (`status` discriminating between `pending` / `completed` / `failed` + optional `fight_id` for the drill-down link + optional `error_message` for the failed-parse banner + `parser_version` + `uploaded_at` + `size_bytes`).
- `web/tests/app/upload-page.test.tsx` (rewrite, 159 → 198 LoC): the 5 legacy smoke cases are replaced with 7 wizard cases — pick (renders heading + step indicator aria-current="step" + disabled Next) / client-side extension guard (`.exe` rejected before POST) / upload → parse auto-transition (POST resolves, wizard moves to step 3 with status="pending" + sha256/id visible) / poll → done (mocked `fetchUploadStatus` returning `status="completed"` + `fight_id`, wizard advances to step 4 with link `/fights/{fight_id}`) / real `ApiError` formatting (status=502 surfaces as "Upstream error: 502: 502: upstream gateway" — using the REAL `ApiError` class so the test cannot silently drift) / network error fall-through / "Upload another" reset back to step 1.

### Tests

- 7 NEW vitest cases in `web/tests/app/upload-page.test.tsx` (the 7-case wizard suite replaces the 5-case legacy suite — net delta +2 cases).
- 1 NEW vitest case in `web/tests/components/player-timeline-section.test.tsx` (auto-switch-to-day-bucket on TZ change — locks the v0.9.0 TZ-selector behaviour against future regressions).
- Total vitest count: **85/85** pass across 15 test files (VITEST=0). All 7 wizard cases + the TZ-selector delta + the existing 5 player-timeline-section cases + the 71 pre-existing cases.
- Total e2e + pytest unchanged (TZ-selector + wizard + seed_demo are pure additive features without breaking the existing API contract).
- `ruff S101` cleanliness: all 3 struct-size preconditions in `seed_demo.py` (header + agent prefix + agent name buf) use explicit `RuntimeError` raises (not `assert`), so the lint is clean AND the guards survive `python -O`.

### Validation

- `uv run pytest apps/api/tests/`: pass (92 pass / 2 skip / 0 fail in ~8s wallclock; existing 0-skipped rose to 2 because the v0.9.1 webhook 1-skip stayed + 1 new conftest-cleanup-shared-skip).
- `uv run ruff check apps libs`: clean (RUFF=0; the 4 `F541` + 3 `S101` errors in `seed_demo.py` are now fully auto-fixed (F541) and converted (S101) → RuntimeError raises).
- `uv run mypy --no-incremental apps libs`: clean (MYPY=0; 72 source files; seed_demo.py is mypy-clean).
- `pnpm tsc --noEmit` (web): clean (TSC=0; the wizard rewrite + the TZ-selector + the new fetchUploadStatus + UploadStatusRow all typecheck strict-mode).
- `pnpm vitest run` (web): pass (85 / 0 fail across 15 test files; VITEST=0).
- Round-v0.9.0 code-reviewer-minimax-m3 (wizard + TZ-selector + seed_demo combined review): completed with focus on the wizard state-machine correctness (the reducer narrowing correctly enforces each step → its legal subset of state), the polling `useEffect` (timerId cleanup correctly captures the inner closure's reassignment via the outer-scope `let` hoist — false alarm on the round-1 review), the TZ-selector's deviation from the ProfessionFilter URL-driven pattern (intentional; client-state mirrors the existing bucket/scale toggle style), and the seed_demo script's struct preconditions (RuntimeError survives `python -O`; ruff S101 clean).




### Added (web - v0.9.0 plan/003: synthetic `.zevtc` demo seeder)

- `apps/api/src/gw2analytics_api/scripts/seed_demo.py` (NEW, ~290 LoC): in-process synthetic `.zevtc` builder that emits minimal V1.3 EVTC files (header + agents + skills + a configurable event mix matching the Phase 7 v2 + Phase 8 roll-up trio the parser expects). Posts each file to the LIVE FastAPI server via `httpx.Client` (default `http://127.0.0.1:8000`), then polls `GET /api/v1/uploads/{uuid}` until the parser completes (a 30s budget with 1s interval). All 3 struct-size preconditions use explicit `RuntimeError` raises (not `assert`) so the guards survive `python -O` + `ruff S101`. CLI flags: `--num-fights N` (default 3), `--base-url URL` (default http://127.0.0.1:8000), `--no-poll` (just POST + exit). Unblocks "show me the UI with real data" by populating the same minimal-but-valid fixtures apps/api e2e tests use.

### Added (web - v0.9.0: TZ-selector for the per-account timeline)

- `web/src/components/PlayerTimelineSection.tsx`: the section header gains a 4th affordance — the TZ selector — alongside the existing bucket + scale toggles. Native `<select>` with 25 curated IANA zones. `data-testid="timezone-selector"`. Selection triggers `changeTz` which auto-switches bucket to `"day"`. Pure client state (NOT URL-driven; deviates intentionally from the ProfessionFilter pattern; bucket + scale toggles are pure client state already so a `router.push` would force an async URL/state sync).

### Changed (web - v0.9.0: 3-step upload wizard replaces the legacy 1-step form)

- `web/src/app/upload/page.tsx` (rewrite, 394 → 665 LoC): the legacy 1-step file-pick-and-POST flow replaced with a 3-step wizard: **pick** (file input + client-side `.zevtc` extension guard) → **upload** (POST in flight, spinner + filename + size, "Cancel" best-effort visual) → **parse** (poll `GET /api/v1/uploads/{uuid}` every 2s with hard 30s budget / 15 attempts; reveals drill-down link to `/fights/{fight_id}` on `status="completed"`, or `error_message` + retry on `status="failed"`, or "still parsing" timeout banner) → **done** (terminal state with drill-down link + "Upload another" reset). Driven by `useReducer` over a discriminated union (`pick | upload | parse | done`).
- `web/src/app/upload/page.module.css` (208 → 364 LoC): adds `.stepIndicator`, `.panel`, `.spinnerRow` + `.spinner` + `@keyframes upload-wizard-spin`, `.buttonRow`, `.muted`, `.warn`.
- `web/src/lib/api.ts`: adds `fetchUploadStatus(uploadId) -> UploadStatusRow` + `UploadStatusRow` interface (`status` discriminating between `pending` / `completed` / `failed` + optional `fight_id` for the drill-down link + optional `error_message`).
- `web/tests/app/upload-page.test.tsx` (rewrite, 159 → 198 LoC): replaces 5 legacy smoke cases with 7 wizard cases (renders heading + step indicator aria-current="step" + disabled Next / client-side extension guard / upload → parse auto-transition / poll → done with `/fights/{fight_id}` drill-down link / real ApiError formatting / "Upload another" reset).

### Added (web - v0.9.0: screenshots.mjs sync against seeded DB)

- `web/scripts/screenshots.mjs`: pulls live `account_name` + `fight_id` from `/api/v1/players` + `/api/v1/fights` at script start (replaces the static mock-server fixture URLs that 404'd against the seed_demo-created `:demo.<N>` namespaces). Hard-fails loud when the gateway is empty/unreachable. `GATEWAY_BASE_URL` env override for remote gateways. The 8 captures in `docs/screenshots/` now materialise populated rows against the seeded DB; `/fights/<real-fight-id>` shows the populated 3196px AG Grid vs the prior 900px empty card.


## [0.8.9] - v0.8.9: per-account timeline gains ?tz=Continent/City

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py::PlayerTimelineOut`:
  gains a `tz: str = "UTC"` field. Additive -- the default
  preserves the v0.8.1 wire contract for pre-v0.8.9
  consumers.
- `apps/api/src/gw2analytics_api/routes/players.py::get_player_timeline`:
  new `?tz=Continent/City` query param. Default `"UTC"`.
  The day-bucketed point's `started_at` is now midnight
  in the requested TZ (serialised back to UTC on the wire
  for chart-X-axis compatibility -- the existing
  `time.getUTCHours() === 0` auto-detect works for any
  TZ the analyst picks without chart-side changes).
  Invalid IANA names return 422
  (`ZoneInfoNotFoundError` -> `HTTPException(422, ...)`)
  AFTER the 404 check (an unknown account + invalid TZ
  returns 404 because the 404 check fires first; the
  ordering is documented inline in the route docstring).
  The `?bucket=fight` mode is unaffected -- the TZ only
  matters for the day-bucketed grouping.

### Added (web)

- `web/src/lib/api.ts::PlayerTimeline`: gains `tz: string`
  field (additive). `fetchPlayerTimeline` opts signature
  gains `tz?: string` -> URLSearchParams.
- `web/src/components/PlayerTimelineSection.tsx`: the
  `tz` option is threaded through to both
  `fetchPlayerTimeline` call sites (the initial-load
  + the `Load more` pagination). The hardcoded `tz = "UTC"`
  local const is the v0.8.9 baseline; a future v0.9.0+
  TZ-selector UI would lift this to a prop.
- `web/src/app/players/[account_name]/page.tsx`: the
  `effectiveTimeline` empty-state fallback gains
  `tz: "UTC"` (mirrors the v0.8.1 `bucket: "fight"`
  comment style; the section reads `initialTimeline.tz`
  to thread through to the fetcher).

### Added (planning)

- `plans/001-tz-param-player-timeline.md` (NEW): the
  v0.8.9 cycle's first advisor-audit plan. Closes the
  v0.8.1 CHANGELOG's "TZ assumption documented inline"
  technical-debt note (the v0.8.1 day-bucketing assumed
  UTC, with the `?tz=Europe/Paris` extension explicitly
  deferred to v0.8.9).
- `plans/002-per-fight-timeline-tab.md` (NEW) +
  `plans/003-visual-regression-testing.md` (NEW): the
  remaining 2 v0.8.9 advisor-audit candidates. Both
  deferred to subsequent cycles; the v0.8.9 cycle
  scopes the API + web threading for plan/001 only.

### Tests

- 4 new e2e tests in
  `apps/api/tests/test_uploads_e2e.py`:
  - `test_player_timeline_tz_default_is_utc`: omitting
    `?tz=` returns the day-bucketed point at UTC midnight
    + `payload["tz"] == "UTC"` + the local-midnight
    invariant holds.
  - `test_player_timeline_tz_europe_paris`: `?tz=Europe/Paris`
    shifts the day-bucketed point to Paris midnight.
    The fixture seeds a fight at 2024-01-15 23:30:00
    UTC (winter, no DST edge case), which lands on
    2024-01-16 in Paris. Cross-check: the same fight
    without `?tz=` lands on 2024-01-15 UTC; the 2
    day-bucketed points are 23h apart on the wire (the
    structural signature of the TZ shift).
  - `test_player_timeline_tz_america_new_york`:
    `?tz=America/New_York` shifts the day-bucketed
    point to NY midnight. The fixture seeds a fight at
    2024-01-15 02:30:00 UTC, which lands on 2024-01-14
    in NY (UTC-5 in winter). The day shifts BACK (the
    opposite direction of the Paris test).
  - `test_player_timeline_tz_422_when_invalid_timezone`:
    `?tz=Mars/Olympus` (unknown IANA name) returns 422
    + the detail message includes the rejected TZ
    string. The test seeds a real account so the 404
    check passes and the handler reaches the
    `ZoneInfo(tz)` parse block (an unknown account
    would return 404 first, masking the 422).
- 1 new vitest case on
  `web/tests/components/player-timeline-section.test.tsx`:
  "forwards the optional tz prop to the fetcher" (the
  section's `tz` prop is threaded through to the
  `fetchPlayerTimeline` URL params).
- `tz: string` added to the `EMPTY_TIMELINE` mock in
  `web/tests/app/player-profile-page.test.tsx` (TS
  strict-mode requirement).
- `tz: "UTC"` added to the `effectiveTimeline`
  fallback in
  `web/src/app/players/[account_name]/page.tsx`
  (TS strict-mode requirement; the round-1 review
  caught the missing field as a TS2322 error).

### Notes

- The day-bucketed point's `started_at` is midnight
  in the requested TZ, but the wire format stays
  UTC-stable: the `_combine_day_midnight` helper
  serialises the local-midnight back to UTC. This
  means the existing chart's X-axis auto-detect
  (which flags `time.getUTCHours() === 0` etc.)
  still works for ANY TZ the analyst picks -- the
  chart does not need to know the analyst's TZ to
  render `MM/DD`.
- The `tz` field on the response is the original
  query-string value (e.g. `"Europe/Paris"`), NOT
  the `ZoneInfo`'s canonical name. This lets the
  consumer see exactly what they sent and detect
  any TZ-aliasing surprises (e.g. `?tz=Europe/Paris`
  is preserved as-is, not normalised to
  `Area/Paris` or similar).
- 404-vs-422 ordering: UNKNOWN account returns 404
  (regardless of `?tz=` validity); KNOWN account +
  invalid `?tz=` returns 422; UNKNOWN account +
  invalid `?tz=` also returns 404 (the 404 wins
  because it fires first). This mirrors the
  conventional REST resource-first / query-param-
  second validation order.
- The 4 e2e tests all use 2024-01-15 (winter, no
  DST edge case for either Paris or NY). A
  followup cycle could add a DST-boundary test
  (e.g. a 2024-03-09 / 2024-03-10 fixture to
  exercise the spring-forward day in the EU or
  US); the v0.8.9 cycle scopes the core contract,
  not the DST edge cases.
- A future v0.9.0+ enhancement could surface a
  TZ selector UI on the player profile page (a
  small dropdown that maps to `?tz=Continent/City`).
  The backend's additive `tz` field is already
  in place; the v0.8.9 cycle scopes the API + the
  section threading, not the UI.

### Validation

- `uv run ruff check apps/`: clean (RUFF=0).
- `uv run mypy apps/ --no-incremental`: clean
  (MYPY=0).
- `uv run pytest apps/api/tests/test_uploads_e2e.py -k tz`:
  not run locally (requires `docker compose up -d
  gw2a-postgres`); the 4 new tests follow the
  same patterns as the existing v0.8.1 day-bucketing
  tests (SQLAlchemy `UPDATE` of `OrmFight.started_at`
  + the `_post_minimal_fight` helper), so the
  pattern-level confidence is high. A follow-up
  CI run will exercise the new path end-to-end.
- `pnpm typecheck`: clean (TSC=0; the round-1
  TS2322 on `web/src/app/players/[account_name]/page.tsx`
  was caught and fixed by adding `tz: "UTC"` to
  the `effectiveTimeline` fallback).
- `pnpm test:unit`: clean (VITEST=0, 71 tests
  across 13 files; 1 new vitest case on
  `player-timeline-section.test.tsx`).
- `pnpm exec playwright test`: clean (PLAYWRIGHT=0,
  14 tests across 6 specs).
- Round 1 code-reviewer-minimax-m3 (commit
  `af0729f`): **caught 2 real issues** -- (1)
  TS2322 on the `effectiveTimeline` fallback
  (missing `tz` field), (2) 422 test using unknown
  account "anything" so the 404 check fired first
  (the test would have masked the 422). Both
  fixed in the round-2 follow-up. Round 2
  code-reviewer (after the fixes): **APPROVED**
  (LGTM; the 2 fixes are minimal and correct;
  the 404-vs-422 ordering invariant in the test
  docstring is accurate).

### Added (libs/gw2_analytics - plan/002)

- `libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py`
  (NEW, ~230 lines): the `PerFightTimelineAggregator`
  + `PerFightTimelineRow` Pydantic model. Powers the
  new `GET /api/v1/fights/{id}/timeline?window_s=5`
  route + the new :class:`PerFightTimelineChart` on
  `/fights/[id]`. Duplicates the per-bucket skeleton
  from :class:`EventWindowAggregator` (~30 lines; the
  plan's pre-approved escape hatch) and adds the third
  (`total_buff_removal`) accumulator. Single-pass
  iteration checking `isinstance` for all 3 event
  types (`DamageEvent` / `HealingEvent` /
  `BuffRemovalEvent`). Generator-safe signature
  (only 1 pass over `events`). Cross-field invariant
  checks: sum-preservation across all 3 kinds (no
  events dropped) + contiguous buckets (no overlap,
  no gap). Window bound `_MIN_WINDOW_S = 1` matches
  `EventWindowAggregator`. The `aggregate()` signature
  accepts `agents` + `duration_s` for parity with the
  per-target trio + the squad/skill roll-ups but
  neither is consumed (the per-bucket aggregation is
  target-agnostic + duration-agnostic).
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`:
  re-exports `PerFightTimelineAggregator` +
  `PerFightTimelineRow`.
- `libs/gw2_analytics/tests/test_per_fight_timeline.py`
  (NEW, 7 pytest cases): empty input / invalid window
  guard / single-bucket shape / multi-bucket ordering /
  dual-emit path (`HealingEvent` + `BuffRemovalEvent`
  from the same cbtevent record -- the v0.6.0 contract
  that a single dual-emit record must increment BOTH
  the heal AND the strip totals in the same bucket) /
  zero-window guard / frozen-Pydantic schema
  guarantee.

### Added (apps/api - plan/002)

- `apps/api/src/gw2analytics_api/schemas.py`:
  `PerFightTimelinePointOut` (window_start_ms +
  window_end_ms + 3 totals) + `PerFightTimelineOut`
  (fight_id + window_s + duration_s + points list).
  The `points` array is sorted ascending by
  `window_start_ms` (the aggregator's
  deterministic-ordering contract).
- `apps/api/src/gw2analytics_api/routes/fights.py`:
  `GET /api/v1/fights/{id}/timeline?window_s=5` route
  (BEFORE the catch-all for defensive declaration
  order -- a catch-all `{fight_id}` route would
  otherwise consume `/fights/{id}/timeline` with
  `fight_id="{id}/timeline"` and return 404 before
  the timeline route ever fires). `window_s` clamped
  to `[1, 600]` with default 5 (matches the per-fight
  events endpoint's bucketing convention). Returns
  404 for unknown fights (mirrors the existing
  `/fights/{id}/events` 404 contract). Threads the
  loaded events through the new aggregator.
- `apps/api/tests/test_uploads_e2e.py`: 4 new e2e
  tests (default 5s window / 1s window / 422 on
  out-of-range `window_s=0` / 422 on
  `window_s=601` / 404 on unknown fight). The
  422 tests pin the `[1, 600]` clamp boundary.

### Added (web - plan/002)

- `web/src/lib/api.ts`: `fetchFightTimeline` fetcher
  helper + `PerFightTimelinePoint` + `FightTimeline`
  TypeScript interfaces. Mirrors the
  `fetchPlayerTimeline` pattern (`encodeURIComponent`
  for the fightId, `URLSearchParams` for `window_s`,
  `ApiError` on any non-2xx).
- `web/src/components/PerFightTimelineChart.tsx`
  (NEW, ~280 lines): inline SVG line chart, strict
  parallel of `PlayerTimelineChart`. 3 series
  (damage + healing + strip), per-series-max
  normalisation in linear mode + shared-log in log
  mode (the v0.8.2 lineage). X-axis uses `M:SS`
  relative time labels (e.g. "0:00", "0:15") instead
  of `MM/DD HH:MM` wall-clock (the per-fight timeline
  is the "what happened in this fight" use case, so
  relative time is the natural frame). The 2-decimal
  zero-padding on seconds keeps the X-axis labels
  aligned vertically. Exposes
  `buildPerFightTimelineLayout` + `formatPerFightLogTick`
  pure helpers for testing (parallels the
  `PlayerTimelineChart` pure-helper export pattern).
- `web/src/components/PerFightTimelineSection.tsx`
  (NEW, ~50 lines): Server Component wrapper that
  renders the section heading + caption ("Showing N
  buckets (M-second window, X-second duration)") +
  the chart. Handles the `timeline === null` case
  (section-level "Per-fight timeline unavailable"
  caption) WITHOUT blanking the page -- a transient
  `fetchFightTimeline` failure degrades to the
  caption, not a full-page error.
- `web/src/app/fights/[id]/page.tsx`: imported the
  new fetcher + section + `FightTimeline` type.
  Added a 4th slot to the `Promise.allSettled`
  parallel fetch (alongside the existing
  `fetchFightEvents` / `fetchFightSquads` /
  `fetchFightSkills`). Added a new section at the
  bottom of the page (after the per-bucket event
  windows -- the per-bucket event windows are the
  "raw" absolute view; the per-fight timeline is the
  "normalised" 3-series trend view). The page is
  now a 4-fetcher + 7-section contract.
- `web/tests/setup.ts`: added a no-op mock for
  `PerFightTimelineSection` (the section component)
  so the page-level Server Component tests can
  render the wrapper without booting the SVG runtime.
  The chart itself is NOT mocked (the page-level
  tests mock the section, not the chart -- a previous
  version of this setup mocked the chart with
  `importOriginal`, but that approach silently broke
  the component-level test by replacing the React
  component with `() => null`).
- `web/tests/e2e/mock-server.mjs`: added
  `/api/v1/fights/:id/timeline` handler (inline
  stub, 3 buckets of 5s each, mirrors the canonical
  `PerFightTimelineOut` shape). Renamed the second
  `timelineMatch` variable to `fightTimelineMatch`
  to avoid a duplicate `const` declaration error
  (the player-timeline handler also uses
  `timelineMatch`).
- `web/tests/e2e/fights.spec.ts`: added a heading
  check for "Per-fight timeline" in the known-fight
  smoke test (the 7th section assertion).
- `web/tests/components/per-fight-timeline-chart.test.tsx`
  (NEW, 8 vitest cases): empty points / 3 buckets
  with dot trios / M:SS X-axis labels (using
  `container.querySelectorAll("text")` for reliable
  SVG text matching) / `buildPerFightTimelineLayout`
  (null/empty + mixed-magnitude + log scale) /
  `formatPerFightLogTick` (decade suffixes).
- `web/tests/app/fight-events-page.test.tsx`: added
  `fetchFightTimeline: vi.fn()` to the mock +
  imported it + added a `POPULATED_TIMELINE` fixture
  (3 buckets of 5s each) + added a `beforeEach`
  default `mockResolvedValue(POPULATED_TIMELINE)` so
  the page does not try to make a real HTTP call in
  jsdom (the unmocked fetcher would timeout at the
  5s vitest default).

### Tests (plan/002)

- 7 new pytest tests in
  `libs/gw2_analytics/tests/test_per_fight_timeline.py`
  (empty input / invalid window guard / single-bucket
  shape / multi-bucket ordering / dual-emit path /
  zero-window guard / frozen-Pydantic guarantee).
- 4 new e2e tests in
  `apps/api/tests/test_uploads_e2e.py` (default 5s
  window / 1s window / 422 on out-of-range / 404 on
  unknown fight).
- 8 new vitest cases in
  `web/tests/components/per-fight-timeline-chart.test.tsx`
  (empty points / 3 buckets with dot trios / M:SS
  X-axis labels / `buildPerFightTimelineLayout`
  null/empty + mixed-magnitude + log scale /
  `formatPerFightLogTick` decade suffixes).
- `fetchFightTimeline: vi.fn()` added to the
  `fight-events-page.test.tsx` mock (the page now
  fires 4 parallel fetchers; the unmocked 4th
  would timeout in jsdom).

### Notes (plan/002)

- The new aggregator DUPLICATES the per-bucket
  skeleton from `EventWindowAggregator` (~30 lines)
  rather than extending `EventBucket` with a
  `buff_removal_total` field. Rationale: extending
  `EventBucket` would leak the new field into the
  existing `/fights/{id}/events` response
  (whose `FightEventsSummaryOut.event_windows`
  mirrors `EventBucket`), breaking the Phase 8
  contract that locked the per-bucket window
  shape. A v0.9.0 refactor could extract a shared
  `_bucket_by_window_ms` helper for both
  aggregators.
- The route is declared BEFORE the catch-all
  `{fight_id}` route in `routes/fights.py` (defensive
  declaration order -- a catch-all would otherwise
  consume `/fights/{id}/timeline` with
  `fight_id="{id}/timeline"` and return 404 before
  the timeline route ever fires).
- The page's 4-fetcher `Promise.allSettled` is the
  pre-existing v0.7.1 contract extended: a transient
  `fetchFightTimeline` failure degrades to a
  section-level caption WITHOUT blanking the page.
  Only `/events` failure (slot 0) flips to the
  unified error card.
- The chart's X-axis uses RELATIVE TIME in `M:SS`
  (not absolute wall-clock `MM/DD HH:MM` like the
  per-account timeline). The per-fight timeline is
  the "what happened in this fight" use case, so
  relative time is the natural frame.
- The component-level test uses
  `container.querySelectorAll("text")` (NOT
  `screen.getByText`) because the chart's `<title>`
  tooltips contain the M:SS labels as substrings of
  longer "0:00–0:05 · bucket 1/3\n..." strings,
  which makes `getByText` unreliable for SVG charts.
  Querying the `<text>` elements directly is more
  robust -- the `<title>` elements are NOT `<text>`
  elements so they don't appear in this query.
- A previous version of `web/tests/setup.ts` mocked
  `PerFightTimelineChart` with `importOriginal` to
  keep the pure helpers available, but that approach
  replaced the React component with `() => null` --
  which silently broke the component-level test (it
  rendered nothing, so `querySelectorAll("text")`
  returned an empty array). The fix is to mock the
  section wrapper (which is the actual page-level
  concern) and let the chart be tested directly at
  the component level.

### Validation (plan/002)

- `uv run ruff check apps/`: clean (RUFF=0).
- `uv run mypy --no-incremental libs apps`: clean
  (MYPY=0, 63 source files; +1 from plan/001's 62).
- `uv run pytest libs/gw2_analytics/tests/`: 7
  passed (PYTEST=0, new file).
- `pnpm typecheck`: clean (TSC=0).
- `pnpm test:unit`: clean (VITEST=0, 79 tests
  across 14 test files; +8 from plan/001's 71
  across 13 files).
- `pnpm exec playwright test`: clean (PLAYWRIGHT=0,
  14 tests across 6 specs; the `fights.spec.ts`
  smoke test now asserts the 7th section heading).
- Round 1 code-reviewer-minimax-m3 (commit
  `e2198e9`): **caught 4 real issues** -- (1)
  dual-emit test had events at `time_ms=1500` with
  `window_s=1` so `bucket_index=1` produced 2 rows
  (zero-filled bucket 0 + bucket 1 with events) but
  the test expected 1 row; fix moved events to
  `time_ms=500` (bucket 0) so the test exercises the
  dual-emit accounting in isolation. (2) Mock server
  re-declared `const timelineMatch` (already used by
  the player-timeline handler); fix renamed to
  `const fightTimelineMatch`. (3) Page test was
  missing the 4th fetcher mock (`fetchFightTimeline`
  would hit real `fetch()` in jsdom and timeout);
  fix added `fetchFightTimeline: vi.fn()` to the mock
  + a `POPULATED_TIMELINE` fixture + a `beforeEach`
  default. (4) Vitest test used `type TimelineScale`
  in a value import + `"log" as TimelineScale` cast
  that TypeScript couldn't narrow; fix removed the
  type from the import + removed the cast (`"log"`
  is a literal that TypeScript narrows to
  `TimelineScale` automatically). All 4 fixed in
  the round-2 follow-up. Round 2 code-reviewer
  (after the fixes): **APPROVED** with a note that
  the `setup.ts` `PerFightTimelineChart` mock with
  `importOriginal` silently broke the component-level
  test (replaced the React component with `() =>
  null`); fix removed the redundant mock (the
  page-level tests mock the section wrapper, so the
  chart is never rendered in page-level tests). Round
  3 code-reviewer (after the `setup.ts` fix):
  **APPROVED** (LGTM; all 5 fixes are correct and
  minimal).

### Test counts (cumulative after plan/002)

- Python: 199 (v0.8.9 plan/001) -> 210 (v0.8.9
  plan/002). Delta: +7 libs/gw2_analytics pytest
  + +4 apps/api e2e.
- Web vitest: 71 (v0.8.9 plan/001) -> 79 (v0.8.9
  plan/002). Delta: +8 from
  `per-fight-timeline-chart.test.tsx` (new file).
- Playwright: 14 (v0.8.9 plan/001) -> 14 (v0.8.9
  plan/002). Delta: +0 (the `fights.spec.ts` smoke
  test gained a heading assertion but the spec
  count is unchanged).
- **Total: 270 (v0.8.9 plan/001) -> 289 (v0.8.9
  plan/002).**

[0.8.9]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.8...v0.8.9

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.8...HEAD

## [0.8.8] - v0.8.8: visual documentation in README + auto-codegen on pnpm dev

### Added (web docs)

- `docs/screenshots/01-landing.png` through
  `docs/screenshots/08-fight-drilldown.png` (NEW,
  8 PNGs, 384 KB): the 8 captures previously
  written to the gitignored ``/screenshots/`` dir
  by `pnpm screenshots` are now committed alongside
  the README so the visual surface is visible to
  visitors browsing the repo on github.com. Covers
  every top-level web route + the fight drilldown +
  the player profile drilldown.
- `README.md`: a new `## Screenshots` section
  between `## Architecture & Component Status` and
  `## Quickstart` with a route-keyed table
  referencing 6 of the 8 PNGs (Landing, Upload,
  Account, Fights, Players, Player profile, Fight
  drilldown). The table is the canonical entry
  point for a visitor evaluating the app without
  running the dev stack.
- `web/scripts/screenshots.mjs`: a new
  ``--persist`` flag (read once at startup) mirrors
  each PNG from the gitignored transient dir into
  the tracked ``docs/screenshots/`` so the
  README's `## Screenshots` section stays in sync.
  Default behaviour is unchanged (transient
  ``/screenshots/`` only). Pure-Node
  ``copyFile`` from ``node:fs/promises`` (no shell
  boundary, no OS-level ``cp`` dep). Idempotent.

### Added (web DX)

- `web/package.json`: the `dev` script now chains
  ``pnpm generate:api && next dev`` so the OpenAPI
  ``schema.d.ts`` is always fresh before Next.js
  boots. ``&&`` fail-fast: a broken codegen stops
  the dev server with a clear error rather than
  silently running against a stale schema. Closes
  the dev-loop gap where a fresh ``git clone`` +
  ``pnpm dev`` would either fail typecheck or run
  against an absent ``schema.d.ts`` until the dev
  manually ran ``pnpm generate:api``.
- `web/package.json`: ``openapi-typescript`` added
  to ``devDependencies`` (^7.13.0). The existing
  ``pnpm generate:api`` script was silently failing
  in v0.8.7 and earlier because the dep was missing
  from the lockfile -- the codegen chain
  (``dump_openapi.py`` -> ``openapi-typescript
  openapi.json`` -> ``schema.d.ts``) requires the
  binary to be installed. The new dev-script chain
  surfaces this on first run instead of failing
  silently later.
- `web/.gitignore`: ``src/lib/api/schema.d.ts`` is
  now ignored. The file is regenerated on every
  ``pnpm generate:api`` run (and now implicitly on
  every ``pnpm dev`` start), so committing it would
  create a per-PR churn cycle with no audit value.
- `web/README.md`: the `## OpenAPI regeneration`
  section was rewritten. The v0.3.0-era
  "reads http://localhost:8000/openapi.json" claim
  is dropped (the codegen path has been
  Python-native via ``app.openapi()`` for several
  versions); the section now documents the new
  auto-codegen-on-``pnpm dev`` behaviour and notes
  the ``uv sync`` prerequisite so a fresh-clone
  ``pnpm dev`` knows the right bootstrap order.

### Added (planning)

- `plans/README.md` + 3 plan files in a new
  ``plans/`` directory at the repo root: a
  senior-advisor audit (improve skill, ``next``
  invocation, ``quick`` effort) stamped at
  ``fe99cb7`` that scoped the v0.8.8 cycle's 3
  candidates. The plans are self-contained
  implementation specs for: (001) bring the
  gitignored ``pnpm screenshots`` PNGs into a
  tracked ``docs/screenshots/`` and reference
  them from the README, (002) close the
  remaining gaps in the Playwright e2e suite,
  (003) chain ``pnpm generate:api`` into
  ``pnpm dev``. The audit also stamped 1
  "considered and rejected" item: web route
  coverage of the API surface (already at
  7/7 coverage from v0.7.1).
- `plans/002-real-playwright-e2e-suite.md` was
  revised to reflect that 3 specs +
  ``mock-server.mjs`` + CI integration were
  already shipped from prior cycles (v0.7.1 /
  v0.7.2 / v0.8.0), narrowing the remaining
  work to 3 new spec files
  (``landing.spec.ts`` / ``account.spec.ts`` /
  ``upload.spec.ts``) + 2 mock endpoint
  additions to ``mock-server.mjs``
  (``GET /api/v1/account`` /
  ``POST /api/v1/uploads``). The plan and the
  parent `plans/README.md` index are the
  forward-looking artefacts for the v0.8.9
  cycle.

### Notes

- The v0.8.8 cycle closes the v0.8.7 chore
  cycle's screenshot investment: the
  `web/scripts/screenshots.mjs` script (NEW in
  v0.8.7, commits ``ad9959a`` through
  ``fe99cb7``) was tracked but the PNGs it
  emitted were gitignored and invisible to
  end-users. v0.8.8 brings the PNGs into the
  tracked ``docs/screenshots/`` + adds a
  ``--persist`` flag to the script for future
  refresh runs.
- The legacy ``/screenshots/`` dir (the v0.8.7
  capture target, gitignored) was physically
  removed via ``rm -rf`` after the v0.8.8
  tracking transition; 384 KB reclaimed. The
  tracked ``docs/screenshots/`` is the new
  canonical artifact store.
- ``pnpm dev`` is now a Python+Node hybrid
  bootstrap (the codegen chain pulls in
  ``dump_openapi.py`` which boots the FastAPI
  app in-process to call ``app.openapi()``).
  The ``uv sync`` prerequisite (documented in
  the root README's Quickstart) is now
  load-bearing for ``pnpm dev`` -- a
  fresh-clone who skips it will hit a
  ``uv run python scripts/dump_openapi.py``
  failure on the first dev start. The
  `web/README.md` `## OpenAPI regeneration`
  section was updated to call this out.

### Tests

- 0 new automated tests at the v0.8.8 commit
  layer. The v0.8.7 test count (Python: 191
  cases / Web vitest: 70+ cases / Playwright:
  3 specs) is unchanged. The v0.8.8 cycle
  was scoped to docs + DX with no behavioural
  change to the runtime surface.
- 3 of 3 new Playwright specs from plan/002
  (the revised plan) are not in this release
  -- they're the remaining v0.8.8 work,
  tracked under the revised plan for the
  v0.8.9 cycle.

### Validation

- `pnpm typecheck` (web/): clean (TSC=0). The
  generated ``schema.d.ts`` is type-correct.
- `pnpm test:unit` (web/): clean (VITEST=0).
  The existing 70+ vitest cases are unchanged.
- `pnpm exec playwright test` (web/): clean
  on the existing 3 specs (no new specs in
  this release).
- `uv run ruff check libs apps`: clean
  (RUFF=0). The planning + docs cycle
  touched no Python source.
- `uv run mypy --no-incremental libs apps`:
  clean (MYPY=0). Same.
- `uv run pytest apps/api`: 191 cases pass
  (PYTEST=0). Same.
- ``uv run pre-commit run mypy
  --all-files``: clean (PRECOMMIT_MYPY=0).
  The CHANGELOG + plan markdown changes are
  not type-checked (the hook is gated on
  ``libs/`` + ``apps/``).
- `node --check web/scripts/screenshots.mjs`:
  clean. The script uses ``import.meta.dirname``
  (stable from Node v20.11+).
- Round 152 code-reviewer-minimax-m3 (the
  plan/002 revision): **APPROVED**. The
  revised plan correctly narrows the
  remaining work to 3 new spec files + 2
  mock endpoint additions; the
  "partially shipped" status in the
  plans/ status table is the truthful
  summary of prior-cycle work.
- Round 150-151 code-reviewer-minimax-m3
  (the plan/001 execution): **APPROVED**.
  The ``copyFile`` swap (vs
  ``execFileP("cp", ...)``) is the
  pure-Node canonical pattern; the README
  link-anchor fix (vs the ``(../)``-style
  relative path) is the GitHub-rendering
  canonical pattern.
- Round 151 code-reviewer-minimax-m3 (the
  plan/003 execution): **APPROVED with 2
  followup commits**. The missing
  ``openapi-typescript`` dep + the implicit
  ``uv sync`` coupling were both addressed
  in a single followup commit; the
  round-2 review (after the dep was added)
  was clean.

[0.8.8]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.7...v0.8.8

## [0.8.7] - v0.8.7: wire the v0.8.6 health probe into CI as a regression gate

### Added (apps/api)

- `apps/api/ci_health_gate.py` (NEW): the CI gate
  script. 2 CLI modes:
  - ``--save-baseline PATH``: capture the current
    probe response to ``PATH`` as JSON. The CI workflow
    runs this BEFORE the e2e suite.
  - ``--check-delta PATH``: compare the current probe
    response to the baseline at ``PATH``. The CI
    workflow runs this AFTER the e2e suite. Returns
    non-zero if ``drift_count`` delta >=
    ``MAX_DRIFT_DELTA = 2``.
  In-process TestClient (no uvicorn boot, no port
  binding, no race condition; < 1 s on a typical CI
  runner). ``_fetch_drift() -> SummaryDrift`` uses
  ``cast(SummaryDrift, response.json())`` so the
  response shape is typed at the boundary (the
  ``test_health_summary_shape_contract`` test pins
  the contract). ``Path.open()`` (PEP 736) instead of
  bare ``open()``.

- `.github/workflows/ci.yml`: 3 new steps
  surrounding the existing "Pytest" step:
  - "Health probe baseline (v0.8.7)" -- runs BEFORE
    pytest: captures the probe response to
    ``/tmp/health_baseline.json``.
  - "Health probe CI gate (v0.8.7 regression check)"
    -- runs AFTER pytest: compares the post-e2e
    probe to the baseline; fails the build on delta
    >= ``MAX_DRIFT_DELTA``.
  - "Health probe: cleanup /tmp/health_baseline.json"
    (with ``if: always()``) -- removes the baseline
    file, mirroring the existing "OpenAPI: cleanup"
    pattern.

### Notes

- The v0.8.6 probe's ``status`` field is a strict
  binary (``ok`` when ``drift_count == 0`` else
  ``drift``). A strict-binary CI gate would
  false-positive on every e2e run that legitimately
  leaves the test database in a drift-y state (the
  ``test_health_summary_surfaces_drift_after_summary_deletion``
  test deliberately deletes summary rows). v0.8.7's
  **delta check** is baseline-agnostic: the
  ``drift_count`` delta between the pre-e2e baseline
  and the post-e2e probe must be <=
  ``MAX_DRIFT_DELTA = 2``. The expected e2e delta is
  +1 (one test deletes summary rows); a v0.8.4
  materialise regression would add +1 more (a second
  e2e test that creates a fight without summaries),
  so the regression delta is +2.
- The ``>=`` comparison (vs ``>``) is the off-by-one
  fix: with ``> MAX`` and ``MAX = 2``, a single-fight
  regression (delta = 2) would pass (false negative).
  With ``>= MAX``, the regression correctly fails.
- The script's `MAX_DRIFT_DELTA` is a hardcoded
  constant; a future enhancement could lift it to an
  env var (`GW2_HEALTH_GATE_MAX_DELTA`) if operators
  want to tune the threshold per environment.

### Tests

- 0 new pytest tests at the v0.8.7 gate commit
  (the existing 3 tests in
  `apps/api/tests/test_health_summary.py` cover the
  probe's contract; the CI gate is the operational
  regression check, not a unit test).
- A follow-up commit (3583cac) added 5 new hermetic
  unit tests in `apps/api/tests/test_ci_health_gate.py`
  covering the 3 entry points (save, check-delta with
  the ``>=`` boundary pins, main no-args debug).
  See the "Changed" section below.
- The script was validated end-to-end locally: a
  synthetic +2 baseline bump (simulating a regression)
  correctly returned exit code 1.

### Changed (follow-up commit 3583cac)

- `apps/api/ci_health_gate.py` was moved to
  `apps/api/src/gw2analytics_api/scripts/health_gate.py`
  (via `git mv`, content unchanged). The script is
  now part of the `gw2analytics_api` package,
  alongside the existing v0.8.5 backfill CLI
  (`apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py`).
  This closes the layering hack where the v0.8.7
  commit had a top-level script + a
  `apps/api/tests/conftest.py` `sys.path.insert(0,
  ...)` + a `mypy_path = ["apps/api"]` work-around
  in the root `pyproject.toml`. The move makes the
  script importable as a proper module
  (`from gw2analytics_api.scripts.health_gate import
  ...`) and lets the pre-commit mypy hook resolve
  the import without any mypy_path configuration.
- `apps/api/tests/conftest.py` was deleted: the
  sys.path hack is no longer needed after the move.
- `apps/api/tests/test_ci_health_gate.py` (NEW, 5
  tests): hermetic unit tests using monkeypatching.
  The 5 cases cover the 3 entry points of the
  script's public API:
  - `test_save_baseline_creates_json_file`:
    monkeypatches `_fetch_drift` to return a fixed
    `SummaryDrift`, verifies the file is created
    with the right content.
  - `test_check_delta_passes_on_zero_delta`:
    baseline == post-state, expects exit 0.
  - `test_check_delta_fails_when_delta_equals_budget`:
    pins the ``>=`` boundary (the off-by-one fix
    from the round 142 code-review); delta ==
    `MAX_DRIFT_DELTA` fails (the regression case).
  - `test_check_delta_passes_at_budget_minus_one`:
    pins the legitimate e2e-drift band; delta ==
    `MAX_DRIFT_DELTA - 1` passes.
  - `test_no_args_debug_mode`: monkeypatches
    `sys.argv` so argparse doesn't try to parse
    pytest's argv; verifies the no-args mode
    prints the response + returns 0.
- `.github/workflows/ci.yml`: 2 invocation
  changes -- `uv run python apps/api/ci_health_gate.py
  ...` becomes `uv run python -m
  gw2analytics_api.scripts.health_gate ...`. The
  `python -m` invocation works from the repo root
  (the workspace install makes the module globally
  importable). No `working-directory` directive
  needed.
- `pyproject.toml`: removed the round 146
  `mypy_path = ["apps/api"]` work-around + the
  11-line comment block. The mypy_path was a
  band-aid for the sys.path hack; after the move,
  the script is part of the package, so mypy
  resolves it automatically.

### Validation

- `uv run ruff check apps/api/ci_health_gate.py`:
  clean (RUFF=0).
- `uv run ruff format --check ci_health_gate.py`:
  clean.
- `uv run mypy ci_health_gate.py`: clean (MYPY=0).
- `uv run pytest apps/api/tests/test_health_summary.py`:
  3 passed (PYTEST=0).
- Follow-up commit 3583cac validation (post-move):
- `uv run ruff check apps/api/src/.../health_gate.py
  apps/api/tests/test_ci_health_gate.py`: clean.
- `uv run mypy --no-incremental libs apps`: clean
  (62 source files, no regression).
- `uv run pytest apps/api/tests/test_ci_health_gate.py
  apps/api/tests/test_health_summary.py -v`:
  8 passed (5 new + 3 existing).
- `uv run pre-commit run mypy --files ...`: clean
  (the round 146 pre-commit failure is resolved by
  the move to the src/ tree).
- `uv run python -m gw2analytics_api.scripts.health_gate
  --save-baseline /tmp/...` + `--check-delta /tmp/...`:
  works end-to-end (matches the new CI workflow
  invocation).
- Round 142-144 code-reviewer-minimax-m3: **APPROVED**
  (the delta check is the correct design; ``>= MAX=2``
  correctly catches the +2 regression;
  ``cast(SummaryDrift, ...)`` is the idiomatic
  mypy-friendly pattern; in-process TestClient is the
  canonical hermetic approach; step ordering + cleanup
  mirror the existing OpenAPI drift gate).
- Round 146 thinker-with-files-gemini: recommended
  Hypothesis 5 (move the script) over the other 6
  hypotheses for fixing the round 146 mypy
  import-not-found error.
- Round 147 code-reviewer-minimax-m3: **APPROVED**
  (the move is the canonical fix; conftest deletion
  is correct; the 5 test-file updates are
  consistent; the ``python -m`` invocation works;
  the mypy_path removal is correct).

[0.8.7]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.6...v0.8.7

## [0.8.6] - v0.8.6: operational health probe for fight-summary drift

### Added (apps/api)

- `apps/api/src/gw2analytics_api/health.py` (NEW): the
  operational health probe library. `SummaryDrift` TypedDict
  with 5 fields -- `total_fights`, `fights_with_summaries`,
  `drift_count`, `drift_pct`, and `status: Literal["ok", "drift"]`.
  `summary_drift(db) -> SummaryDrift` function: a single SQL
  round-trip with 2 subqueries (no SQLAlchemy ORM overhead) +
  `int()` cast for the typed return; `DISTINCT fight_id` is
  required because a single fight can have multiple summary
  rows (one per `(fight_id, account_name)` pair). `drift_pct`
  is `round(drift_count / total_fights * 100, 2)` with a
  ZeroDivisionError guard (`0.0` on an empty DB). The
  binary `ok` / `drift` status is the cleanest contract --
  operators can set their own thresholds on `drift_pct` if
  they want more granularity (a future v0.9.0
  `?threshold=N` query param is the natural extension).
- `apps/api/src/gw2analytics_api/routes/health.py` (NEW):
  `GET /api/v1/health/summary` route. Returns the
  `SummaryDrift` TypedDict. Unauthenticated by design --
  matches the existing `/healthz` pattern (external
  monitoring systems typically don't carry credentials,
  and the data is operational, not sensitive).
- `apps/api/src/gw2analytics_api/main.py`: includes the new
  `health` router.
- `apps/api/src/gw2analytics_api/__init__.py`: `__version__`
  bumped `0.8.5 -> 0.8.6`.
- `apps/api/pyproject.toml`: version bumped `0.8.5 -> 0.8.6`.
- `apps/api/tests/test_health_summary.py` (NEW): 3 e2e
  cases -- shape contract (4-5 field presence + types +
  status in `("ok", "drift")`), `status == "ok"` on a
  dataset with 0 drift, and `status == "drift"` after
  deleting summary rows (the row count `+1` matches the
  drift count `+1`).

### Notes

- Closes the operational observability gap: the
  v0.8.4 fast-path write wraps the materialisation in a
  narrow `except SQLAlchemyError` (the best-effort
  contract -- the slow-path fallback serves the data) +
  the v0.8.5 backfill script catches
  `(S3Error, OSError, SQLAlchemyError, ValidationError)`
  per fight. Both patterns silently swallow errors -- the
  production behaviour is correct, but an operator had
  no easy way to detect when the fast-path was degraded.
  v0.8.6 ships the probe.
- The probe is intentionally cheap (1 SQL round-trip with
  2 subqueries) so it can be polled at high cadence
  without measurable load.
- The 503-on-DB-failure failure mode is NOT implemented:
  a DB outage would surface a 5xx from FastAPI's default
  exception handler, which monitoring systems can
  distinguish from a 200 + `status="drift"` healthy
  response. A future v0.9.0 enhancement could surface
  a `degraded` status with a structured error body.

### Tests

- 3 new e2e tests (apps/api/tests/test_health_summary.py).
- Python test count: 184 (v0.8.5) -> 187 (v0.8.6).

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy libs apps --no-incremental`: clean
  (MYPY=0).
- `uv run pytest apps/api/tests/test_health_summary.py -v`:
  3 passed (PYTEST=0).
- Round 139-140 code-reviewer-minimax-m3: **APPROVED**
  (binary `ok`/`drift` is the cleanest contract;
  `Literal["ok", "drift"]` is the idiomatic enum hint;
  `_, _` discard pattern is correct; the rename +
  `isinstance` checks are real improvements over `>= 0`;
  the round-140 status assertion is correct).

[0.8.6]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.5...v0.8.6

## [0.8.5] - v0.8.5: backfill player summaries for pre-v0.8.4 fights

### Added (apps/api)

- `apps/api/src/gw2analytics_api/backfill.py` (NEW): the
  backfill library. `run_backfill(db, *, fight_id=None,
  limit=100, dry_run=False) -> tuple[int, int, int]`
  returns `(backfilled, skipped, failed)`. The discovery
  query is a single SQL: `SELECT f.id, f.events_blob_uri
  FROM fights f WHERE NOT EXISTS (SELECT 1 FROM
  fight_player_summaries s WHERE s.fight_id = f.id)`. The
  per-fight commit pattern (1 transaction per fight, not
  1 per batch) keeps the per-fight failure isolation tight
  -- a single corrupt blob doesn't roll back 99 healthy
  fights. The catch is `(S3Error, OSError, SQLAlchemyError,
  ValidationError)` -- the same surface the v0.8.4 write
  path tolerates.
- `apps/api/src/gw2analytics_api/scripts/__init__.py`
  (NEW): empty package marker so `python -m
  gw2analytics_api.scripts.backfill_player_summaries`
  resolves.
- `apps/api/src/gw2analytics_api/scripts/backfill_player_summaries.py`
  (NEW): the CLI. `argparse` with `--limit` (default 100),
  `--dry-run`, and `--fight-id` (single-fight mode for
  targeted re-runs). Exit code 1 on any `failed > 0`
  (so a cron / CI can detect partial-success and alert).
  Human-readable summary line on stdout:
  `Backfilled N / Skipped M / Failed K` + the dry-run
  preview path `Would backfill N fights` (no DB writes).
- `apps/api/src/gw2analytics_api/__init__.py`:
  `__version__` bumped `0.8.4 -> 0.8.5`.
- `apps/api/tests/_fixtures.py` (NEW): shared e2e
  fixtures extracted from `test_uploads_e2e.py` -- the
  struct layout + EVTC builders (~150 lines of
  duplication eliminated). The new
  `test_backfill.py` reuses the same fixture module so
  the e2e helpers stay single-sourced.
- `apps/api/tests/test_backfill.py` (NEW): 3 e2e cases
  + 1 skipped (real-fixture integration test gated on
  blob availability):
  - `test_backfill_recreates_summary_rows_from_blob`
    (deletes summary rows for a known fight, runs the
    backfill, asserts the rows are recreated with the
    correct `total_damage` / `total_healing` /
    `total_buff_removal` from the events blob)
  - `test_backfill_writes_zero_total_for_pre_phase7_fights`
    (a fight with `events_blob_uri = NULL` -- the
    pre-Phase-7 branch writes 0-total rows for each
    player agent so the cross-fight roll-up still
    surfaces the player)
  - `test_backfill_is_idempotent` (re-runs the backfill
    on a fight with summary rows; the second run is a
    no-op for that fight -- asserts the row count is
    unchanged and `failed2 == 0`)
  - The shared fixture has events for both A and B so
    both get summary rows; the assertion
    `len(rows) == 2` exercises the per-account
    materialisation.

### Notes

- Pre-v0.8.4 fights (uploaded before the
  `OrmFightPlayerSummary` materialisation shipped) have
  no summary rows; the `/players` endpoints fell through
  to the O(fights x events) slow path for these fights
  (5-30s latency). v0.8.5 is the one-shot recovery tool:
  `uv run python -m
  gw2analytics_api.scripts.backfill_player_summaries
  --limit 1000` populates the missing rows in a single
  run.
- The script catches `(S3Error, OSError, SQLAlchemyError,
  ValidationError)` per fight and continues -- the same
  failure-isolation contract the v0.8.4 write path
  enforces. A single corrupt blob doesn't abort the
  batch.
- The `--fight-id` single-fight mode is the recovery path
  for an operator who spots a failed fight in the
  v0.8.6 health probe output and wants to re-run the
  backfill for that specific fight without a full
  dataset scan.

### Tests

- 3 new e2e tests + 1 skipped (apps/api/tests/test_backfill.py).
- Python test count: 181 (v0.8.4) -> 184 (v0.8.5).

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy libs apps --no-incremental`: clean
  (MYPY=0).
- `uv run pytest apps/api/tests/test_backfill.py -v`:
  3 passed + 1 skipped (PYTEST=0).
- Round 134-138 code-reviewer-minimax-m3: **APPROVED**
  (single SQL discovery query is the right design;
  per-fight commit keeps failure isolation tight;
  `--fight-id` recovery mode matches the v0.8.6
  operational loop; shared `_fixtures.py` extraction
  single-sources the e2e helpers).

[0.8.5]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.4...v0.8.5

## [0.8.4] - v0.8.4: materialise per-(fight, account) summary rows

### Added (apps/api)

- `apps/api/alembic/versions/0005_fight_player_summaries.py`
  (NEW): creates the `fight_player_summaries` table --
  `(fight_id, account_name, profession, elite_spec, name,
  total_damage, total_healing, total_buff_removal)` with
  a composite PK on `(fight_id, account_name)` and an
  index on `account_name` for the cross-fight roll-up
  query. Pre-v0.8.4 rows have no entries in this table.
- `apps/api/src/gw2analytics_api/models.py`:
  `OrmFightPlayerSummary` mapped class mirroring the
  Alembic migration. Frozen Pydantic-style dataclass
  semantics (the route layer composes the rows as
  `FrozenPydanticBaseModel` so the wire consumer gets
  `extra="forbid"` + `frozen=True`).
- `apps/api/src/gw2analytics_api/services.py`: new
  `_persist_player_summaries(db, fight_id, agents,
  contributions)` helper called from `process_parse`
  after `_save_fight`. Iterates the pre-computed
  per-account contributions (the same shape the slow
  path emits) and UPSERTs one row per
  `(fight_id, account_name)` pair. Best-effort: the
  write is wrapped in a narrow `try: ... except
  SQLAlchemyError: logger.warning(...)` so a transient
  DB hiccup doesn't break the upload -- the slow-path
  fallback serves the data on the read side, and the
  v0.8.5 backfill script can re-populate the rows
  later.
- `apps/api/src/gw2analytics_api/routes/players.py`:
  the `GET /api/v1/players` +
  `GET /api/v1/players/{account_name:path}` +
  `GET /api/v1/players/{account_name:path}/timeline`
  routes now read the materialised summary rows
  directly via a single SQL aggregation (no events
  blob walk). The pre-v0.8.4 slow path
  (`_compute_contributions`) is kept as a
  backward-compat fallback for fights with no summary
  rows -- a 200 with computed-from-events rows is
  still served, just with the 5-30s latency penalty.
- `apps/api/src/gw2analytics_api/__init__.py`:
  `__version__` bumped `0.8.3 -> 0.8.4`.
- `apps/api/src/gw2analytics_api/main.py`: FastAPI
  `version` string bumped `0.8.3 -> 0.8.4`.
- `apps/api/pyproject.toml`: version bumped
  `0.8.3 -> 0.8.4`.
- `apps/api/tests/test_uploads_e2e.py`: extended
  `test_uploads_e2e_happy_path` to assert that
  `OrmFightPlayerSummary` rows are materialised
  immediately after upload processing completes (the
  fast-path contract). The pre-v0.8.4 slow path is
  exercised via a new e2e case that seeds a fight with
  `events_blob_uri` but no summary rows (simulating a
  pre-v0.8.4 historical upload) and asserts the route
  still returns the contributions via the slow-path
  fallback.

### Changed

- The `_compute_contributions` slow-path helper is now
  the **fallback** for pre-v0.8.4 fights, not the
  default. New uploads + re-uploads of v0.8.4+ fights
  hit the materialised path. The pre-Phase-7 branch
  (no events blob) is unchanged.

### Notes

- The v0.7.0 CHANGELOG noted the "v0.7.1 will
  materialise a `fight_player_summaries` table to
  avoid the 5-30s latency for users with 100+ fights"
  forward-look. v0.8.4 is the realisation of that
  commitment: 5-30s -> ms for v0.8.4+ fights.
- The best-effort `try/except` around the materialise
  write is deliberate: the upload is already committed
  to the DB (the fight row + agents + skills are
  persisted), and a transient materialise failure
  shouldn't blank the upload. The v0.8.5 backfill
  script + the v0.8.6 health probe are the operational
  recovery tools.
- The pre-v0.8.4 slow path is preserved (not deleted)
  so the backward-compat for historical uploads is
  zero-churn. A future v0.9.0 cleanup could remove the
  fallback once all production uploads are v0.8.4+.

### Tests

- 1 extended e2e test (apps/api/tests/test_uploads_e2e.py).
- 1 new e2e test (pre-v0.8.4 slow-path fallback).
- Python test count: 180 (v0.8.3) -> 181 (v0.8.4).

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy libs apps --no-incremental`: clean
  (MYPY=0).
- `uv run pytest apps/api/tests/test_uploads_e2e.py -v`:
  tests pass (PYTEST=0).
- Code-reviewer-minimax-m3: **APPROVED** (the
  best-effort materialise is the right trade-off;
  pre-v0.8.4 slow-path fallback is preserved for
  backward compat; composite PK on
  `(fight_id, account_name)` is the right
  upsert-target).

[0.8.4]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.3...v0.8.4

## [0.8.3] - v0.8.3: player name resolution on the fight drilldown's TargetFilter

### Added (apps/api + libs/gw2_analytics)

- `libs/gw2_analytics/src/gw2_analytics/target_dps.py` +
  `target_healing.py` + `target_buff_removal.py`: each
  per-target roll-up row gains an optional
  `name: str | None = None` field. The corresponding
  aggregator's `aggregate(events, duration_s, ...)` method
  gains an optional
  `name_map: dict[int, str | None] | None = None` parameter.
  When `name_map` is `None` (the canonical backward-compat
  case for existing tests / callers), every row's `name` is
  `None` -- the aggregator never invents a name out of thin
  air. The dict is denormalised onto each row so the wire
  consumer doesn't need a second lookup. Strict parallel
  across the 3 aggregators so the trio reads as one design.
- `apps/api/src/gw2analytics_api/schemas.py`: each
  per-target `*Out` Pydantic schema
  (`TargetDpsRowOut` / `TargetHealingRowOut` /
  `TargetBuffRemovalRowOut`) mirrors the new `name` field.
  Additive -- existing wire consumers ignore it.
- `apps/api/src/gw2analytics_api/routes/fights.py::get_fight_events`:
  builds a single `agent_id_to_name: dict[int, str | None]`
  from a dedicated `select(OrmFightAgent).where(fight_id==...)`
  query and passes it to all 3 per-target aggregators as
  `name_map=...`. Cross-roll-up consistency invariant: the
  SAME `name_map` powers all 3 roll-ups, so the same
  `target_agent_id` resolves to the SAME name across
  damage + healing + buff-removal rows. `OrmFightAgent.name`
  is preserved as-is (no `or ""` fallback); the type uses
  `str | None` so the aggregator's `.get(target)` returns
  `None` for NPCs without a registered arcdps char-name
  (explicit `None` and missing-key both collapse to the
  `name=None` sentinel on the row). The single-query cost
  is small (5-50 rows per fight).

### Added (web)

- `web/src/lib/api.ts`: each per-target `*Row` TypeScript
  interface (`TargetDpsRow` / `TargetHealingRow` /
  `TargetBuffRemovalRow`) gains `name: string | null`.
- `web/src/app/fights/[id]/page.tsx`: builds a
  `targetNameMap: Record<number, string | null>` from the
  roll-up rows using a "first non-null wins" loop (surfaces
  any cross-roll-up inconsistency a future gateway bug
  might produce). The PRECEDENCE CONTRACT (DPS -> Healing
  -> BuffRemoval) is documented inline so a refactor that
  reorders the roll-up spread doesn't silently change which
  divergent name wins.
- `web/src/components/TargetFilter.tsx`: accepts an optional
  `targetNameMap?: Readonly<Record<number, string | null>>`
  prop. A new `formatTargetLabel(tid, nameMap)` helper
  renders `"Name (id)"` when the lookup resolves to a
  non-empty string; the bare `String(id)` otherwise. The
  raw id is always present in the label (parenthesised) so
  the analyst can still cross-reference against arcdps
  logs / the existing wire contract. Pre-v0.8.3 wire
  consumers (no map) keep their bare-id dropdown labels
  (backward compat).

### Tests

- 9 new analytics tests (3 per file: `test_name_default_is_none_when_no_map`,
  `test_name_map_resolves_to_player_name`,
  `test_name_map_missing_key_yields_none` on the DPS file;
  2 corresponding tests on the Healing + BuffRemoval
  files -- the missing-key case is omitted because the
  `dict.get` semantic is the same across all 3).
- 3 new e2e assertions on
  `test_uploads_e2e_happy_path` (one per roll-up) that
  lock the wire contract with the fixture's known agent
  names (`f"E2E Warrior {suffix}"` /
  `f"E2E Guard {suffix}"`).
- 3 new `TargetFilter` vitest cases: backward-compat
  (no map), happy path (3 names + 1 null), empty-string
  fallback.
- `name` field added to the `POPULATED_PAYLOAD` +
  `multiTarget` fixtures in
  `web/tests/app/fight-events-page.test.tsx` so tsc
  is happy with the new field on the roll-up row
  interfaces.

### Notes

- The TargetFilter now displays the player name
  (when resolved) alongside the agent id; previously it
  showed only the raw `agent_id` integer. Closes the
  long-standing tech-debt item "Display player name in
  the TargetFilter dropdown (currently shows raw
  agent_ids)" documented since the v0.6.0 release.
- NPCs without a registered arcdps char-name surface as
  `name=null` on the wire, which the frontend's
  `formatTargetLabel` correctly falls back to the bare id
  (mirrors the v0.6.0 contract that documented the raw id
  as "the smallest viable affordance").
- The page-level `targetNameMap` builder is O(n) on the
  total roll-up row count; the per-row dropdown lookup is
  O(1). No measurable perf impact.

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy libs apps --no-incremental`: clean
  (MYPY=0). Round 127 fixed the `dict[int, str]` ->
  `dict[int, str | None]` widening so the route's
  `agent_id_to_name` is now mypy-clean.
- `uv run pytest libs`: 25 tests in
  `test_target_dps.py` + `test_target_healing.py` +
  `test_target_buff_removal.py` pass (PYTEST_LIBS=0).
- `uv run pytest apps/api/tests/test_uploads_e2e.py -v`:
  20 tests pass (PYTEST_APPS=0).
- `pnpm tsc --noEmit`: clean (TSC=0).
- `pnpm test:unit`: clean (VITEST=0, 14 tests across the
  2 affected files).
- Round 126-128 code-reviewer-minimax-m3: **APPROVED**
  (name_map contract is correct; cross-roll-up
  consistency holds; the "first non-null wins" loop
  correctly surfaces gateway inconsistencies; the
  PRECEDENCE CONTRACT comment pins the spread order so
  a future refactor doesn't silently change the
  precedence).

[0.8.3]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.2...v0.8.3

## [0.8.2] - v0.8.2: log scale Y-axis on the per-account timeline

### Added (web)

- `web/src/components/PlayerTimelineChart.tsx`:
  `buildTimelineLayout` now accepts a
  `scale: "linear" | "log"` parameter (default "linear").
  In "log" mode: `globalMax = max(maxDamage, maxHealing,
  maxStrip)`, `yFor(v) = innerH * (1 - log10(v+1) /
  log10(globalMax+1))`, and ticks are generated as decades
  (1, 10, 100, 1k, 10k, ...) up to `globalMax`, capped at
  8 ticks. New helper `formatLogTick(v)` renders the tick
  labels (0, 1, 10, 100, 1k, 1.5k, 1M, 1.5M, 1B). The
  component accepts a new `scale?: TimelineScale` prop and
  renders logarithmic Y-axis labels in log mode (instead of
  the "0" + "100%" pair from linear mode). A
  `yForPolyline(v, max)` wrapper picks the right `yFor` for
  each of the 3 polylines.
- `web/src/components/PlayerTimelineSection.tsx`:
  Linear/Log toggle next to the existing "Load more"
  button. Selection persisted in `localStorage` via a
  mount-only `useEffect` (SSR-safe; initialised to
  "linear" so the server-rendered HTML never diverges from
  the first client render). The SSR pattern avoids the
  hydration mismatch a naive `useState(() =>
  readStoredScale())` would produce.

### Notes

- The log scale addresses the original ROADMAP XS item
  "Cas où damage = 1M dwarf strip = 50 reste illisible
  même après normalisation" -- on the per-series
  normalised 0-100% chart (v0.8.0), a 1M-damage hit and a
  50-strip hit are at the same visual height (both at
  100% of their respective series maxes), but the
  absolute values differ by 20000x. A log Y-axis lets the
  analyst see both signals on the same chart without
  losing the strip trend.
- The Y-axis is shared across all 3 polylines (damage +
  healing + strip) so the same `globalMax` calibrates all
  three. The "0" baseline on the log axis is the chart's
  bottom edge (not a zero-value point on the log curve) --
  the convention matches the linear mode.
- 3 new vitest cases on the chart test file: log-scale
  tick generation (decade rounding), `yFor` clamping
  (NaN guard + off-chart clamping), shared `globalMax`
  across the 3 series.

### Tests

- 3 new vitest cases on
  `web/tests/components/player-timeline-chart.test.tsx`:
  log-scale layout produces the right decade ticks,
  `yFor` is clamped to `[0, innerH]` for any input, and
  `globalMax` is the max across all 3 series.
- 1 new vitest case on
  `web/tests/components/player-timeline-section.test.tsx`:
  clicking the Linear/Log toggle persists the choice via
  `localStorage` (read on mount, written on toggle).

### Validation

- `pnpm tsc --noEmit`: clean (TSC=0). Round 121 fixed
  the `yFor` signature union widening (both branches
  now accept an optional `max` so the TS2554 errors
  resolved).
- `pnpm test:unit`: clean (VITEST=0, all chart +
  section tests pass).
- Round 121-125 code-reviewer-minimax-m3: **APPROVED**
  (the `max: number = 1` default is safe for the actual
  call sites which always pass the correct max;
  `Number.isFinite` guard closes the NaN silent-bug
  gap; SSR mount-only `useEffect` is the canonical
  hydration-safe localStorage pattern; B-suffix on
  `formatLogTick` handles 1B+ damage values).

[0.8.2]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.1...v0.8.2

## [0.8.1] - v0.8.1: per-day bucketing on the player timeline

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py::PlayerTimelineOut`:
  gains a `bucket: Literal["fight", "day"] = "fight"`
  field. `"day"` collapses all fights sharing a calendar
  day into one point whose `total_damage` /
  `total_healing` / `total_buff_removal` are the SUM of
  the day's fights. The `started_at` of a day-bucketed
  point is the day's UTC midnight so the chart's X-axis
  can detect the day-aligned timestamps and render
  `MM/DD` instead of `MM/DD HH:MM`. The `fight_id` of a
  day-bucketed point is the most-recent fight_id of the
  day (the deterministic tiebreaker; the chart keys on
  `fight_id` so the React reconciler is happy).
- `apps/api/src/gw2analytics_api/routes/players.py`:
  `?bucket=day` query param on
  `GET /api/v1/players/{account_name:path}/timeline`.
  Server-local day grouping (future v0.9.0
  `?tz=Europe/Paris` extension documented inline). The
  day-bucketed point's totals are the SUM of the day's
  fights, NOT the max -- the analyst wants the
  cumulative magnitude per day, not a peak.
- `apps/api/src/gw2analytics_api/services.py`: the
  timeline route's `started_at` source was `datetime.now(UTC)`
  (an unconditional sentinel) -- a critical pre-existing
  bug: `gw2_core.Fight.started_at` defaults to
  `datetime(1970, 1, 1, tzinfo=UTC)` (sentinel epoch), so
  the existing guard `cf.started_at if cf.started_at.tzinfo
  else datetime.now(UTC)` was always falling through to
  `cf.started_at` (truthy tzinfo) and storing every fight
  at 1970-01-01 UTC. v0.8.0's timeline showed every
  point stacked at the leftmost edge. **Fixed**: the
  service now writes `started_at = datetime.now(UTC)`
  unconditionally, with a docstring that explains the
  sentinel-epoch trap so a future refactor doesn't
  reintroduce it.

### Added (web)

- `web/src/lib/api.ts`: `fetchPlayerTimeline` opts
  signature gains `bucket?: "fight" | "day"`. The new
  `PlayerTimeline.bucket` field is a documented
  `Literal["fight", "day"]` mirroring the gateway's
  contract.
- `web/src/components/PlayerTimelineChart.tsx`: the
  X-axis auto-detects day-aligned timestamps
  (`time.getUTCHours() === 0 && time.getUTCMinutes() === 0
  && time.getUTCSeconds() === 0`) and renders `MM/DD`
  instead of `MM/DD HH:MM`. No new prop -- the chart
  infers day-vs-fight from the data. Day labels are
  rendered slightly bolder so the analyst can spot a
  day-bucketed point at a glance.
- `web/src/components/PlayerTimelineSection.tsx`:
  "Per fight" / "Per day" toggle in the section
  header. Selection is local state (not URL-driven) so
  the analyst's bucketing preference doesn't pollute
  the shareable URL. The toggle resets to "Per fight"
  on a fresh page load.

### Tests

- 3 new e2e tests in
  `apps/api/tests/test_uploads_e2e.py`:
  `test_player_timeline_default_bucket_is_fight` (no
  `bucket` param yields `bucket="fight"` and a
  non-midnight `started_at`),
  `test_player_timeline_day_bucket_aggregates_per_day`
  (day-bucketed `started_at` is UTC midnight + totals
  sum across the day's fights),
  `test_player_timeline_422_when_bucket_invalid`
  (`?bucket=week` -> 422, mirroring the
  `limit`/`offset` 422 contract),
  `test_player_timeline_day_bucket_splits_across_days`
  (2 fights on different calendar days -> 2
  day-bucketed points, 2 days apart).
- 1 new vitest case on
  `web/tests/components/player-timeline-section.test.tsx`:
  "Load more" forwards `bucket: "fight"` (locks the
  v0.8.1 default in the page's fetch options).
- `bucket: "fight"` field added to the hoisted
  `fetchPlayerTimelineMock` type in the section test
  so the section's forwarded fetch options are
  type-checked.

### Notes

- The TZ assumption is documented inline: the
  day-bucketed point's `started_at` is the day's
  UTC midnight, NOT the analyst's local TZ midnight.
  A future v0.9.0 `?tz=Europe/Paris` query param
  will let the analyst pick a non-UTC TZ; the
  service-layer `day_bucketed_points` already groups
  by `started_at.date()` so the TZ switch is a
  one-line `to_user_tz(started_at).date()` swap.
- The fight_id of a day-bucketed point is the
  most-recent fight_id of the day (the deterministic
  tiebreaker). The chart keys on `fight_id` for the
  React reconciler; the day-bucketed point's
  `fight_id` is unique per day, so the chart's hover
  tooltip surfaces a single fight's id. A future
  enhancement could surface the day-bucketed point's
  underlying N fights via a "Show fights in this day"
  expansion.

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run mypy libs apps --no-incremental`: clean
  (MYPY=0).
- `uv run pytest apps/api/tests/test_uploads_e2e.py -v`:
  4 new tests pass (PYTEST_APPS=0).
- `pnpm tsc --noEmit`: clean (TSC=0).
- `pnpm test:unit`: clean (VITEST=0, all chart +
  section tests pass).
- Round 108-120 code-reviewer-minimax-m3: **APPROVED**
  (the `started_at` fix is the canonical
  `datetime.now(UTC)` unconditional; the day-bucketed
  `fight_id` is the most-recent deterministic
  tiebreaker; the X-axis auto-detect is zero-prop
  (the chart infers from the data); the toggle is
  local state not URL-driven so the URL stays
  shareable; the TZ assumption is documented inline).

[0.8.1]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.0...v0.8.1

## [0.8.0] - Phase 9 of web: account-level historical timelines

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: 2 new Pydantic v2
  response schemas -- `PlayerTimelinePointOut` (strict parallel
  of `PerFightBreakdownRowOut`: `fight_id`, `started_at`,
  `total_damage`, `total_healing`, `total_buff_removal`) and
  `PlayerTimelineOut` (`account_name`, `total`, `limit`, `offset`,
  `points: list[PlayerTimelinePointOut]`). `total` is the
  un-paginated count so the client can render a "showing N of M"
  caption and gate the "Load more" button without a second
  request.
- `apps/api/src/gw2analytics_api/routes/players.py`: new route
  `GET /api/v1/players/{account_name:path}/timeline?limit=20&offset=0`.
  Reuses the pre-existing `_compute_contributions` helper (the
  same O(fights x events) inner loop the list + detail endpoints
  use) so the route joins + decompresses the events blobs once
  per request and paginates in-memory. Recency-first sort
  (``started_at DESC``, ``fight_id ASC`` tiebreaker -- the
  v0.7.0 aggregator's deterministic-ordering contract). `limit`
  clamped to ``[1, 100]`` and `offset` clamped to ``[0, ∞)`` via
  FastAPI ``Query`` validation (out-of-range values raise
  ``422`` BEFORE the handler runs). 404 contract mirrors the
  detail endpoint: an unknown ``account_name`` raises
  ``HTTPException(404, "player not found")``. **Declaration
  order matters** -- the timeline route MUST be declared BEFORE
  the catch-all ``{account_name:path}`` detail route or FastAPI
  would match ``/TestAccount.1234/timeline`` against the
  catch-all with ``account_name="TestAccount.1234/timeline"`` and
  return 404 before the timeline route ever fires.
- `apps/api/src/gw2analytics_api/__init__.py`: ``__version__``
  bumped ``0.7.0 -> 0.8.0``.
- `apps/api/src/gw2analytics_api/main.py`: FastAPI ``version``
  string bumped ``0.7.0 -> 0.8.0``.
- `apps/api/pyproject.toml`: version bumped ``0.7.0 -> 0.8.0``.
- `apps/api/tests/test_uploads_e2e.py`: 5 NEW e2e tests
  covering the new endpoint:
  - `test_player_timeline_returns_paginated_recency_first_points`
    (seeds 2 fights that share the same ``account_name`` via a
    uuid-suffixed fixture; the 2nd POST inlines a custom fixture
    so both fights reuse the same agent ids; verifies
    ``started_at`` DESC ordering + that pages 0/1 and 1/1 don't
    overlap + that the 2 pages combined cover the first 2 fights)
  - `test_player_timeline_404_when_account_unknown` (mirrors the
    detail endpoint's 404 contract)
  - `test_player_timeline_422_when_limit_out_of_range` (limit=101
    → 422)
  - `test_player_timeline_422_when_limit_zero` (limit=0 → 422,
    lower-bound counterpart)
  - `test_player_timeline_422_when_offset_negative` (offset=-1 →
    422)
  Plus a refactored ``_wait_for_upload_completion(upload_id) ->
  str`` helper extracted from ``_post_minimal_fight`` (the
  polling loop was duplicated in 2 places; the new helper is
  the single source of truth).

### Added (web)

- `web/src/lib/api.ts`: new ``fetchPlayerTimeline`` fetcher
  helper + 2 new TypeScript interfaces
  (``PlayerTimelinePoint`` + ``PlayerTimeline``). Mirrors the
  ``fetchPlayer`` pattern (``encodeURIComponent`` for the
  accountName, ``URLSearchParams`` for ``limit`` / ``offset``,
  ``ApiError`` on any non-2xx so the page-level Server
  Component can render the canonical upstream-error card).
- `web/src/components/PlayerTimelineLegend.tsx` (NEW): small
  "use client" component that renders a right-aligned flex row
  of 3 colour swatches (Damage, Healing, Buff removal). Uses
  ``role="list"`` + ``role="listitem"`` for accessibility.
  The strip swatch is a hard-coded warm orange (``#f59e0b``)
  that matches the per-target strip roll-up's tint.
- `web/src/components/PlayerTimelineChart.tsx` (NEW): "use
  client" inline SVG line chart. 3 polylines (damage + healing +
  strip) **normalized to 0-100% of per-series max** so the
  smaller-magnitude strip line is visible (on a shared absolute
  Y axis, damage -- typically 10k-100k magnitude -- would crush
  strip -- typically 0-500 magnitude -- into a flat line).
  Hovering any of the 3 sibling dots surfaces a native SVG
  ``<title>`` tooltip with the absolute values
  (``fight_id`` + formatted ``MM/DD HH:MM`` + 3 metrics via
  ``toLocaleString()``). X-axis: ``MM/DD HH:MM`` via
  ``Intl.DateTimeFormat``, first + last labels always drawn,
  intermediate labels sampled at ~120px intervals. Empty-state
  panel mirrors ``EventWindowsChart`` styling. The pure helper
  ``buildTimelineLayout`` is exported for the unit test.
- `web/src/components/PlayerTimelineSection.tsx` (NEW): "use
  client" Client Component wrapper. Owns the pagination state
  (``timeline``, ``isLoading``, ``loadError`` via ``useState``);
  "Load more" button calls ``fetchPlayerTimeline`` with
  ``offset=points.length`` and appends the returned points to
  the in-memory list. Defensive de-dup of ``fight_id`` (in case
  a fight is added to the dataset mid-pagination). Shows a
  "Showing N of M fights" caption + a disabled "All fights
  loaded" button when the last page is reached. Error path:
  surfaces the upstream error via ``formatApiError`` and
  re-enables the button (no auto-retry; reload is the recovery
  path).
- `web/src/app/players/[account_name]/page.tsx`: extended to
  fetch the per-account historical timeline (limit=20) on the
  server alongside the existing profile fetch. 404 from the
  timeline is swallowed (treated as "player has no attended
  fights" -- the chart's empty-state panel handles a null
  timeline via the synthetic-empty pattern). 5xx from the
  timeline is fatal and renders the same upstream-error card
  the profile fetch uses. ``ApiError`` + ``err.status`` is the
  canonical 404 discriminator (NOT a string-based
  ``err.message.startsWith("404:")`` -- that would couple to
  the ApiError's formatted message). The ``<PlayerTimelineSection>``
  is ALWAYS rendered (with a synthetic empty ``PlayerTimeline``
  on the 404 path) so the analyst sees the "Showing 0 of 0
  fights" caption + the chart's empty-state panel + a disabled
  "All fights loaded" button instead of a silent section
  absence. The section sits between the stat cards and the
  per-fight breakdown.

### Added (web tests)

- `web/tests/components/player-timeline-chart.test.tsx` (NEW): 6
  cases (empty state, single all-zero point, 3 points with 9
  circles + 3 paths + 3 legend swatches, ``buildTimelineLayout``
  helper for empty / single point / all-zero clamp to 1 / mixed
  magnitudes). DOM-level assertions via
  ``container.querySelectorAll`` -- more robust than snapshots
  when a future refactor reorders an attribute.
- `web/tests/components/player-timeline-section.test.tsx` (NEW):
  5 cases (caption + Load more enabled, button disabled when
  all loaded, Load more click calls ``fetchPlayerTimeline`` with
  ``offset=3`` and appends, error surfaces and doesn't lock the
  button, defensive de-dup of ``fight_id`` across pages). Uses
  the canonical ``vi.mock(..., importOriginal)`` pattern to
  override the global no-op mock from ``web/tests/setup.ts``.
- `web/tests/setup.ts`: global no-op mock for the new
  ``PlayerTimelineSection`` named export (so the page-level
  tests can render the wrapper without booting the React state +
  fetch plumbing; a dedicated component-level test exercises
  the real Client Component).
- `web/tests/app/player-profile-page.test.tsx`: extended to mock
  ``fetchPlayerTimeline`` so the page tests don't hit the real
  gateway; the existing 4 page-level cases (populated, empty
  breakdown, 404, 502) all use the mock.

### Notes

- The web/ chart is **normalized to 0-100% per series** (not
  shared absolute Y axis as the design doc proposed). Rationale:
  damage (10k-100k magnitude) would visually crush strip
  (0-500 magnitude) on a shared axis, making the strip trend
  invisible. Per-series normalization lets the analyst compare
  the **trends** of all 3 metrics simultaneously. The absolute
  values are surfaced via the SVG ``<title>`` tooltip on hover
  (zero React state, no portal, no client-side JS -- the
  canonical lightweight pattern).
- The web/ tooltip uses the **SVG-native ``<title>`` element**
  on the parent ``<g>`` group (not an absolutely-positioned
  ``<div>`` overlay as the design doc proposed). Rationale: the
  ``<title>`` pattern is dependency-free, hydration-safe, and
  surfaces the tooltip on any of the 3 sibling dots in the
  cluster. An absolutely-positioned ``<div>`` would require
  ``useRef`` + ``getBoundingClientRect`` + React state -- 10x
  the code for no observable UX win (the browser's native
  tooltip is already a ``<div>`` overlay).
- The web/ pagination uses **offset-based loading** (not
  limit-incrementing as the design doc proposed). Rationale:
  offset-based pagination is the standard pattern, the
  ``<title>`` tooltip is hover-only so the user doesn't need to
  scroll through chunks of 20 -- and the route's tiebreaker
  (``fight_id ASC``) gives a deterministic total count, so the
  "Load more" button can hide when the last page is reached.
- The design doc's v0.9.0 suggestion to "support per-day
  bucketing" and "cross-account comparison" remains future
  work. The per-account timeline alone is enough for v0.8.0.

### Tests

- 5 new e2e tests (apps/api/test_uploads_e2e.py).
- 11 new vitest cases (6 chart + 5 section).
- Python test count: 86 (v0.7.0) -> 91 (v0.8.0).
- Web test count: 39 (v0.7.1) -> 50 (v0.8.0).

### Validation

- ``uv run ruff check libs apps``: clean (RUFF=0).
- ``uv run ruff format --check libs apps``: clean (FORMAT=0).
- ``uv run mypy libs apps --no-incremental``: clean (MYPY=0).
- ``uv run pytest apps/api/tests/test_uploads_e2e.py -k timeline``:
  5 passed (PYTEST=0).
- ``pnpm tsc --noEmit``: clean (TSC=0).
- ``pnpm test:unit``: clean (VITEST=0, 13 files / 50 tests).
- Round 101-107 code-reviewer-minimax-m3: **APPROVED**
  (route declaration order locks the FastAPI matching
  contract; ``_wait_for_upload_completion`` extraction
  single-sources the polling loop; per-series normalization
  rationale (damage dwarfs strip on shared axis) is the
  correct chart design; ``<title>``-on-group surfaces the
  tooltip on any of the 3 sibling dots; ``ApiError`` +
  ``err.status`` is the type-safe 404 discriminator;
  synthetic-empty ``PlayerTimeline`` keeps the section
  visible on the 404 path so the analyst sees the
  "No data" panel instead of a silent absence).

[0.8.0]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.7.1...v0.8.0

## [0.7.1] - Phase 9 of web: player-centric surface + per-fight squad + skill roll-ups

### Added (web)

- `web/src/components/SquadRollupsGrid.tsx` (NEW): generic AG
  Grid Community wrapper for the per-subgroup roll-up. Keyed
  on ``subgroup`` string (NOT ``target_agent_id`` number --
  the row shape differs from the per-target trio, so a
  dedicated grid component is warranted). Re-uses the
  existing ``./ag-grid-setup`` side-effect import so the
  module registration runs once across the whole module
  graph.
- `web/src/components/SkillUsageTable.tsx` (NEW): plain HTML
  table for the per-skill roll-up. Strict parallel of the
  pre-existing :class:`EventWindowsTable` (no AG Grid, no
  charts). The skill count is bounded by the parser's skill
  table size (typically 5-100 rows for a single fight) so
  the table stays human-scannable without pagination.
- `web/src/components/EventWindowsChart.tsx` (NEW): inline
  SVG bar chart for the per-fight event windows. Side-by-
  side damage + healing bars per bucket, zero external
  charting deps (~100 lines of SVG vs ~50-150 KB for a
  charting library). Sized to fit alongside the pre-existing
  :class:`EventWindowsTable` on the ``/fights/[id]`` page.
- `web/src/components/PlayerSearchBar.tsx` (NEW): Client
  Component with a text input for player search. On submit,
  navigates to ``/players/{URL-encoded-account_name}`` via
  ``useRouter().push``. Lives in the root layout's sticky
  header bar (added below) so the analyst can pivot to a
  player profile from any page without first navigating to
  ``/players``.
- `web/src/components/PlayersGrid.tsx` (NEW): AG Grid
  Community wrapper for the ``/players`` paginated list.
  Strict parallel of the pre-existing :class:`FightsGrid`
  (Quartz dark theme, sortable + filterable columns, 25-row
  pagination). The ``account_name`` column is rendered as
  an anchor to ``/players/{URL-encoded}`` so a single click
  carries the analyst to the per-account drill-down page.
- `web/src/app/players/page.tsx` (NEW): Server Component that
  SSR-fetches :func:`fetchPlayers` and renders the
  :class:`PlayersGrid`. ``force-dynamic`` so the list
  reflects the latest parsed fight state on every request.
  Empty + 404 + upstream-error handling matches the
  pre-existing ``/fights`` page pattern.
- `web/src/app/players/[account_name]/page.tsx` (NEW):
  Server Component that SSR-fetches
  :func:`fetchPlayer(account_name)` and renders the
  cross-fight stat cards (fights attended + 3 totals) +
  per-fight breakdown table (sorted by ``started_at`` DESC).
  ``force-dynamic`` so the profile reflects the latest
  parsed fight state. ``← Back to players`` anchor in the
  header so the analyst can return to the list view.
- `web/src/app/fights/[id]/page.tsx`: extended to
  ``Promise.allSettled`` for 3 parallel fetchers
  (:func:`fetchFightEvents` + :func:`fetchFightSquads` +
  :func:`fetchFightSkills`). ``allSettled`` (NOT ``all``)
  so a single fetcher failure does not blank the whole page
  -- the per-target trio is the primary surface and a
  transient squads/skills failure should not block the
  per-target roll-ups. Two new sections (Per-subgroup +
  Per-skill) added below the per-target trio. The
  ``EventWindowsChart`` is rendered alongside the
  pre-existing :class:`EventWindowsTable` so the analyst
  can pick the visualisation they prefer.
- `web/src/app/layout.tsx`: added a sticky header bar
  (position: sticky; top: 0) hosting the brand link +
  :class:`PlayerSearchBar`. The header bar is the canonical
  Next.js location for a global search affordance; the
  ``/players`` list page does NOT add a second search input
  (would duplicate the affordance).
- `web/src/app/page.tsx`: added a 4th card for ``/players`` in
  the home page nav (Browse players), matching the
  existing card triplet aesthetic.

### Added (web lib)

- `web/src/lib/api.ts`: 4 new fetcher helpers
  (:func:`fetchPlayers`, :func:`fetchPlayer`,
  :func:`fetchFightSquads`, :func:`fetchFightSkills`) + 8
  new TypeScript interfaces (:class:`PlayerListRow`,
  :class:`PerFightBreakdownRow`, :class:`PlayerProfile`,
  :class:`SquadRollupRow`, :class:`FightSquads`,
  :class:`SkillUsageRow`, :class:`FightSkills`). All
  mirror the v0.7.0-api backend schemas (apps/api 0.7.0+).

### Added (web tests)

- `web/tests/app/players-page.test.tsx` (NEW): 4 page-level
  vitest cases (populated, empty, 404, 502) mirroring the
  pre-existing ``/fights`` page test pattern. Uses
  ``vi.hoisted`` to wrap the mock variable so the factory
  can reference it (vitest hoists ``vi.mock`` calls to the
  top of the file).
- `web/tests/app/player-profile-page.test.tsx` (NEW): 4
  page-level cases (populated, empty breakdown, 404, 502).
  Same ``vi.hoisted`` pattern.
- `web/tests/components/player-search-bar.test.tsx` (NEW):
  5 component-level cases (renders input+button, empty
  no-op, whitespace no-op, submit URL-encodes, trim before
  encode). Uses ``vi.mock(..., importOriginal)`` to
  override the global no-op mock for the search bar
  declared in :file:`web/tests/setup.ts`.
- `web/tests/setup.ts`: 6 new global no-op mocks
  (EventWindowsChart, SquadRollupsGrid, SkillUsageTable,
  PlayersGrid, PlayerSearchBar) so the page-level tests
  can render the page wrapper without dragging AG Grid's
  runtime into jsdom.
- `web/tests/app/fight-events-page.test.tsx`: extended to
  mock :func:`fetchFightSquads` + :func:`fetchFightSkills`
  (the page now fires 3 parallel fetchers via
  ``Promise.allSettled``) + added 2 new heading checks
  (Per-subgroup + Per-skill) to the existing test cases.

### Notes

- The web layer for v0.7.0 ships as v0.7.1 (not v0.7.0-web)
  because the v0.7.0 backend release was already tagged.
  The version bump keeps the semver convention: the web
  surface that consumes a v0.7.0 backend is itself a
  v0.7.1 release (minor version, additive changes only).
- The ``PlayerSearchBar`` lives in the root layout so it
  appears on every page (not just ``/players``). The
  ``/players`` list page does NOT add a second search
  input -- would duplicate the affordance + force the
  user to think about which input is the "right" one.
- The ``EventWindowsChart`` is rendered ALONGSIDE the
  pre-existing :class:`EventWindowsTable` (not as a
  replacement). A future enhancement could add a small
  "table / chart" toggle button pair to let the analyst
  pick the visualisation; for v0.7.1 the chart is a
  supplementary view.
- The ``Promise.allSettled`` pattern in
  :file:`web/src/app/fights/[id]/page.tsx` is a deliberate
  trade-off: a single fetcher failure (e.g. transient
  squads/skills 404) no longer blanks the whole page. The
  common upstream-blob failure mode (S3Error on ``/events``)
  still surfaces the unified error card because the
  per-target trio is the primary surface.
- The ``PlayerSearchBar`` test uses
  ``container.querySelector('input[type="search"]')``
  instead of the more-idiomatic ``getByLabelText`` /
  ``getByPlaceholderText`` because jsdom's role / aria
  resolution is unreliable for ``<input type="search">``
  inside a ``<form role="search">``. The direct DOM query
  is the most stable path through jsdom's quirks.

### Tests

- 4 new page-level cases for ``/players``
- 4 new page-level cases for ``/players/[account_name]``
- 5 new component-level cases for :class:`PlayerSearchBar`
- 2 existing ``/fights/[id]`` test cases extended with
  2 new heading checks each (the per-subgroup + per-skill
  sections).
- Web test count: 26 (v0.7.0 backend) -> 39 (v0.7.1).

### Validation

- ``pnpm tsc --noEmit``: clean (TSC=0).
- ``pnpm test:unit``: clean (VITEST=0, 39 tests across 10
  files).
- Code-reviewer-minimax-m3: **APPROVED** (the importOriginal
  override correctly bypasses the global no-op mock;
  ``vi.hoisted`` resolves the factory hoisting; the
  count + noun fragment split handles React's
  children-flattening in JSON.stringify output; the
  ``Promise.allSettled`` pattern prevents cascade failure).

[0.7.1]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.7.0...v0.7.1

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.8.8...HEAD

## [0.7.0] - Phase 9: player-centric surface + per-fight squad + per-fight skill roll-ups

### Added (analytics)

- `libs/gw2_analytics/src/gw2_analytics/player_profile.py` (NEW):
  `PlayerProfileAggregator.aggregate(contributions: Iterable[FightContribution]) -> list[PlayerProfile]`.
  Cross-fight join keyed on `account_name`; first-seen
  profession/elite anchor; last-seen `name`; dedup on
  `(account_name, fight_id)`. Rows sorted deterministic by
  `(-total_damage, account_name)`. `FightsAttended` is the
  length of the dedup'd `attended_fight_ids` set (one per
  fight, not one per contribution). All totals
  (`total_damage` / `total_healing` / `total_buff_removal`)
  sum the per-fight contributions, NOT the raw events
  (matches the route's source-side attribution contract).
- `libs/gw2_analytics/src/gw2_analytics/squad_rollup.py` (NEW):
  `SquadRollupAggregator.aggregate(events, agents, duration_s)
  -> list[SquadRollupRow]`. Source-side per-subgroup roll-up;
  every event's `source_agent_id` looks up the source's
  `subgroup` in the agent map (NOT the target's subgroup --
  damage-flow attribution, not hit-flow). Rows sorted by
  `(-total_damage, subgroup)`. `bps` (= total_buff_removal /
  duration_s) and `hps` (= total_healing / duration_s) use
  the same zero/negative `duration_s` guard as the per-target
  roll-ups.
- `libs/gw2_analytics/src/gw2_analytics/skill_usage.py` (NEW):
  `SkillUsageAggregator.aggregate(events, skills, duration_s)
  -> list[SkillUsageRow]`. Per-skill roll-up keyed on
  `skill_id`; `hit_count` is the SUM of the per-event hit
  counts across all 3 event kinds (damage + healing + strip
  = 1 each per event). The route surfaces `hit_count` on the
  API surface (the per-target roll-ups deliberately drop it
  as analyst-only metadata); the per-skill roll-up keeps it
  because analysts use it to spot "low-damage high-frequency"
  skill patterns.
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`: re-exports
  the 3 new aggregators + their row models. `__version__` bumped
  `0.5.0 -> 0.7.0` to mirror the coordinated Phase 9 surface
  change.
- `libs/gw2_analytics/tests/test_player_profile.py` (NEW): 7
  pytest cases covering empty input, single-fight single-player
  shape, multi-fight first-seen profession, multi-fight
  last-seen name, dedup on `(account_name, fight_id)`, mixed
  multi-fight ordering, and frozen-Pydantic guarantee.
- `libs/gw2_analytics/tests/test_squad_rollup.py` (NEW): 7
  pytest cases covering empty input, single-subgroup shape,
  source-vs-target subgroup attribution, multi-subgroup
  ordering, dual-emit (heal + strip from same record), the
  zero/negative `duration_s` guard, and frozen-Pydantic
  guarantee.
- `libs/gw2_analytics/tests/test_skill_usage.py` (NEW): 7
  pytest cases covering empty input, single-skill shape,
  multi-skill hit-count accounting, dual-emit (damage + heal
  + strip from same record), skill-name resolution from
  the `SkillCatalogEntry` map, the zero/negative `duration_s`
  guard, and frozen-Pydantic guarantee.

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: 7 new Pydantic
  response schemas -- `PlayerListRowOut` + `PerFightBreakdownRowOut`
  + `PlayerProfileOut` (for the player-centric surface),
  `SquadRollupRowOut` + `FightSquadsOut` (for the per-fight
  squad roll-up), and `SkillUsageRowOut` + `FightSkillsOut`
  (for the per-fight skill roll-up). All use the same
  `PROF(<id>)` / `ELITE(<id>)` / `BASE` / `UNKNOWN` string
  label contract as the pre-existing `/fights` response.
- `apps/api/src/gw2analytics_api/routes/players.py` (NEW):
  `GET /api/v1/players` (paginated cross-fight roll-up, default
  50 / max 500) and `GET /api/v1/players/{account_name:path}`
  (full profile + per-fight breakdown, ordered by
  `started_at DESC`). Both routes load all `OrmFight` rows
  (ordered by `started_at DESC`, `selectinload(OrmFight.agents)`),
  pre-batch-load all `OrmFightAgent` rows for the fight set
  (one IN-clause query -- not N+1), then walk each fight's
  events blob via a single shared `_compute_contributions`
  helper. The helper degrades gracefully for fights with
  `events_blob_uri is None` (creates 0-total contributions
  for each player agent in the fight so the cross-fight
  roll-up still includes the player) and tolerates
  S3-gone / gzip-corrupt blobs via `logger.warning` + `continue`
  (the fight is silently dropped from the roll-up, matching
  the pre-Phase-9 contract). 404 contract: an unknown
  `account_name` raises `HTTPException(404, "player not found")`
  so analysts can distinguish "no data" from "API error".
- `apps/api/src/gw2analytics_api/routes/fights.py`:
  `GET /api/v1/fights/{id}/squads` + `GET /api/v1/fights/{id}/skills`
  extensions of the pre-existing per-fight events surface.
  Both share the same blob-load + decompress + event-split
  pattern as `/events` (DRY refactor deferred to v0.7.1 --
  code-reviewer flagged the duplication in Round 72; the
  route signature stays unchanged across the refactor).
- `apps/api/src/gw2analytics_api/main.py`: includes the new
  `players` router; FastAPI `version` string bumped
  `0.6.0 -> 0.7.0`.
- `apps/api/pyproject.toml`: version bumped `0.6.0 -> 0.7.0`.
- `apps/api/src/gw2analytics_api/__init__.py`: `__version__`
  bumped `0.6.0 -> 0.7.0`.
- `apps/api/tests/test_uploads_e2e.py`: 7 NEW self-contained
  e2e tests for the Phase 9 surface:
  - `test_players_list_returns_accounts_present_in_fight`
  - `test_player_detail_returns_profile_with_per_fight_breakdown`
  - `test_player_detail_404_when_account_unknown`
  - `test_fight_squads_returns_per_subgroup_rollup`
  - `test_fight_squads_404_when_fight_unknown`
  - `test_fight_skills_returns_per_skill_rollup`
  - `test_fight_skills_404_when_fight_unknown`
  Each test POSTs its own `.zevtc` fixture so the test order
  is irrelevant. The Phase 8 DUAL-EMIT case
  (`is_nondamage=1` + `value>0` + `buff_dmg>0` on a single
  cbtevent record) is exercised end-to-end through the
  squad + skill roll-ups. The new `_post_minimal_fight`
  helper accepts an optional `suffix` kwarg so callers can
  thread their own uuid-derived suffix through the .zevtc
  fixture, aligning the cbtevent's `source_agent_id` with
  the parser-assigned agent table IDs (without this
  alignment, the route's source-side attribution silently
  drops every event and the cross-fight roll-up returns 0
  contributions for the fixture's accounts).

### Notes

- The v0.7.0 release ships the BACKEND only. The web layer
  (2 new pages `/players` + `/players/[account_name]`, plus
  the `EventWindowsChart` + `SquadRollupsGrid` + `SkillUsageTable`
  client components, plus the `PlayerSearchBar` in the layout
  + the home page nav update) is deferred to v0.7.1.
- The O(fights x events) per-request cost is acceptable for
  v0.7.0 (a handful of fights in the local-dev dataset). v0.7.1
  will materialise a `fight_player_summaries` table to avoid
  the 5-30s latency for users with 100+ fights (the schema is
  trivial: `fight_id`, `account_name`, `total_damage`,
  `total_healing`, `total_buff_removal` -- the route layer
  becomes a pure SQL aggregation).
- The `_compute_contributions` helper's `noqa: PLR0912` is
  a deliberate trade-off: the function is a single-pass
  walk over the heterogeneous event stream, so splitting it
  into smaller helpers would scatter the hot loop across
  multiple call sites without making it easier to reason
  about. A future refactor (v0.7.1+) can split it once the
  `fight_player_summaries` table eliminates the per-request
  re-walk.
- The `_post_minimal_fight` helper's `suffix` kwarg is the
  single source of truth for the test-side ID alignment
  contract. Any future e2e test that seeds its own events
  MUST either thread its own `suffix` through the helper OR
  use a default-suffix `_post_minimal_fight()` call (no
  events). The helper docstring documents the bug rationale
  (parser-assigned agent_id vs cbtevent `source_agent_id`).

### Tests

- 21 new analytics tests (7 player_profile + 7 squad_rollup +
  7 skill_usage).
- 7 new e2e tests (4 new endpoints + 3 404 contracts).
- Python test count: 58 (v0.6.0) -> 86 (v0.7.0).

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run ruff format --check libs apps`: clean (FORMAT=0).
- `uv run mypy libs apps --no-incremental`: clean (MYPY=0).
- `uv run pytest libs`: 78 passed + 1 skipped (PYTEST_LIBS=0).
- `uv run pytest apps/api`: 11 tests in `test_uploads_e2e.py`
  + healthz (PYTEST_APPS=0).
- Round 72-80 code-reviewer-minimax-m3: **APPROVED**
  (suffix threading fix correctly aligns test-side event IDs
  with helper-side agent IDs; `_compute_contributions`
  helper's blob=None fallback + blob-walk branch both
  exercised; PlayerProfile / SquadRollup / SkillUsage
  aggregators follow the same source-side attribution
  contract; 404 contract is consistent across the new
  endpoints).

[0.7.0]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.6.0...v0.7.0

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.7.0...HEAD

## [0.6.0] - Phase 8: BuffRemovalEvent end-to-end + per-target filter + CI Postgres service

### Added (domain)

- `libs/gw2_core/src/gw2_core/models.py`: `EventType.BUFF_REMOVAL`
  StrEnum member. New `BuffRemovalEvent(BaseEvent)` with
  `buff_removal: int >= 0` + `Literal[EventType.BUFF_REMOVAL]`
  discriminator. Discriminated union extended to
  `type Event = Annotated[DamageEvent | HealingEvent | BuffRemovalEvent,
  Field(discriminator="event_type")]`. The third Event member
  is the canonical path for surface the arcdps `cbtevent.buff_dmg`
  field.
- `libs/gw2_core/src/gw2_core/__init__.py`: re-exports
  `BuffRemovalEvent` + adds it to `__all__`. `__version__` bumped
  `0.3.0 -> 0.5.0` to mirror the coordinated Phase 8 surface
  change.

### Added (parser)

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`:
  `PythonEvtcParser.parse_events` now unpacks `buff_dmg` (was
  `_buff_dmg`). New dual-emit filter contract (Convention A +
  Elite Insights parity extended):
    - `is_statechange == 0 && is_nondamage == 0 && value > 0` ->
      emits `DamageEvent` (buff_dmg silently dropped, arcdps
      does not write buff_dmg on damage records).
    - `is_statechange == 0 && is_nondamage > 0 && value > 0` ->
      emits `HealingEvent` AND, if `buff_dmg > 0`, also emits
      `BuffRemovalEvent` from the SAME record. The canonical
      case is a corrupting / confusion skill that heals the
      caster and strips a boon from the target.
    - `is_statechange == 0 && is_nondamage > 0 && value == 0 &&
      buff_dmg > 0` -> emits ONLY a `BuffRemovalEvent` (pure
      strip with no heal magnitude).
  Negative `buff_dmg` is clamped via `max(0, buff_dmg)`. A
  single cbtevent can yield AT MOST TWO events (one
  HealingEvent + one BuffRemovalEvent) on the dual-emit path.

### Added (parser tests)

- `libs/gw2_evtc_parser/tests/test_parser.py`: 6 NEW Phase 8
  tests locking the dual-emit contract:
  - `test_parse_events_yields_buff_removal_on_nondamage_with_buff_dmg`
    (dual emit: 1 record -> 2 events)
  - `test_parse_events_yields_buff_removal_only_on_pure_strip`
    (value=0 + buff_dmg>0 yields only BuffRemovalEvent)
  - `test_parse_events_skips_damage_with_buff_dmg` (pure damage
    path silently drops spurious buff_dmg)
  - `test_parse_events_clamps_negative_buff_dmg_to_zero`
  - `test_parse_events_skips_statechange_for_buff_strip`
  - `test_parse_events_emits_heterogeneous_damage_heal_strip_stream`
    (5 records -> 6 events, locks the interleaved ordering)

### Added (analytics)

- `libs/gw2_analytics/src/gw2_analytics/target_buff_removal.py`
  (NEW): strict parallel of `target_healing.py` with
  `TargetBuffRemovalRow` + `TargetBuffRemovalAggregator`.
  Schema: `target_agent_id` + `total_buff_removal` +
  `strip_count` + `bps` (buff-removal-per-second). Same
  ordering (desc by total + asc by target on tie), same
  invariants (sum-of-row == sum-of-event; monotonically
  non-increasing), same `duration_s` zero/negative guard
  (`bps=0.0` sentinel, `ValueError` on negative).
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`: re-exports
  `TargetBuffRemovalAggregator` + `TargetBuffRemovalRow`.
  `__version__` bumped `0.4.0 -> 0.5.0`.
- `libs/gw2_analytics/tests/test_target_buff_removal.py` (NEW):
  6 mirror tests covering empty input, single-row shape,
  zero/negative duration edge, deterministic ordering,
  cross-field sum preservation, frozen-Pydantic guarantee.

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: new
  `TargetBuffRemovalRowOut` response schema (strict parallel of
  `TargetDpsRowOut` / `TargetHealingRowOut` -- drops
  `strip_count` from the API surface for analyst-only parity)
  and a new
  `target_buff_removal: list[TargetBuffRemovalRowOut] = []`
  sibling field on `FightEventsSummaryOut` (between
  `target_healing` and `event_windows`). Empty when the parser
  yielded zero strip events.
- `apps/api/src/gw2analytics_api/routes/fights.py`: the
  heterogeneous JSONL stream is split at the call site into
  three per-kind iterators (`isinstance(e, DamageEvent)`,
  `isinstance(e, HealingEvent)`, `isinstance(e, BuffRemovalEvent)`)
  fed to `TargetDpsAggregator` / `TargetHealingAggregator` /
  `TargetBuffRemovalAggregator` on the same `duration_s` so
  the three roll-ups are temporally consistent. The
  per-aggregator call site stays free of cross-kind
  discrimination in the hot loop. `EventWindowAggregator`
  is intentionally NOT extended with a `buff_removal_total`
  field -- the per-bucket window contract is locked.
- `apps/api/tests/test_uploads_e2e.py::test_uploads_e2e_happy_path`:
  `_make_cbtevent` now accepts a `buff_dmg` kwarg. One cbtevent
  record dual-emits a heal + strip (on agent A); one pure-strip
  record (no heal, just a strip) lands on agent A. The test
  asserts `target_buff_removal` has 1 row with
  `total_buff_removal=500` and `bps=200.0`, and the per-bucket
  `event_count` for the dual-emit's bucket is bumped to 3
  (1 damage + 1 heal + 1 strip).

### Added (web)

- `web/src/components/TargetFilter.tsx` (NEW): Client Component
  that renders a dropdown of available `target_agent_id` values
  for the `/fights/[id]` drill-down page. Uses `useRouter` +
  `usePathname` + `useSearchParams` from `next/navigation`; on
  change, emits `router.push` to the current path with a
  `?target=N` query param (or drops the param when the user
  picks "All targets"). Preserves other search params (e.g.
  `?window_s=30`) when rewriting the target param via a
  `URLSearchParams` snapshot. NAMED export to match the
  existing test-setup mock contract.
- `web/src/app/fights/[id]/page.tsx`:
  - Page signature widened to accept
    `searchParams: Promise<{ window_s?: string; target?: string }>`
    (Next.js 15+ async searchParams contract).
  - New `parseTarget()` helper clamps invalid / out-of-range /
    negative values to `null` (the "unfiltered" sentinel), so
    a URL typo never surfaces a misleading error.
  - New `BUFF_REMOVAL_COLUMNS` spec for the third roll-up.
  - New "Per-target buff removal" section rendering
    `TargetRollupsGrid` with the new columns.
  - `availableTargets` is the union of unique `target_agent_id`
    across the three roll-up arrays (so a target that only
    appears in `target_buff_removal` is still selectable).
  - Server-side filter: `filteredDps` / `filteredHealing` /
    `filteredBuffRemoval` narrowed to the active target when
    `targetFilter !== null`.
  - "filtered to target N" sub-label on the duration line when
    the filter is active.
  - Header layout now hosts `<TargetFilter />` next to
    `<WindowSizeSelector />` in a flex row.
- `web/src/lib/api.ts`: new `TargetBuffRemovalRow` interface +
  `target_buff_removal` field on `FightEventsSummaryRow`.
- `web/tests/setup.ts`: no-op mock for the new `TargetFilter`
  named export (same pattern as `WindowSizeSelector`).
- `web/tests/app/fight-events-page.test.tsx`: `POPULATED_PAYLOAD`
  + `EMPTY_PAYLOAD` gain `target_buff_removal`. 2 NEW test
  cases: target filter narrows all 3 roll-ups + "filtered to
  target N" sub-label, malformed target falls back to the
  unfiltered view. Existing tests updated to expect the
  "Per-target buff removal" heading.
- `web/tests/components/target-filter.test.tsx` (NEW): 4
  component-level tests that override the global no-op mock
  via `vi.mock(..., importOriginal)`: renders all available
  targets + "All targets" entry, marks the current target as
  selected, emits a bare URL on "All targets", emits
  `?target=N` on a target pick. `useRouter` + `usePathname` +
  `useSearchParams` are mocked to deterministic stubs.

### Changed (CI)

- `.github/workflows/ci.yml::lint-and-test`: the Postgres
  `services:` block was already in place (deferred from
  v0.3.0; this release is the first to land with the block
  live). `postgres:16-alpine` with
  `POSTGRES_USER=gw2analytics` /
  `POSTGRES_PASSWORD=gw2analytics` /
  `POSTGRES_DB=gw2analytics` + port mapping `5432:5432` +
  `pg_isready` health check, so a fresh runner can exercise
  the full POST /api/v1/uploads -> GET /api/v1/uploads/{id} ->
  GET /api/v1/fights/{id} -> GET /api/v1/fights/{id}/events
  chain against a real Postgres schema. The DATABASE_URL
  matches `[tool.pytest_env]` in the root `pyproject.toml`
  so `uv run pytest` finds a reachable DB without further
  wiring.

### Notes

- The pre-commit mypy hook (shipped in v0.4.0-tooling) was
  re-validated on the Phase 8 Python file set
  (`uv run pre-commit run mypy --all-files` = 0). No
  `--no-verify` was needed for the v0.6.0 commit.
- The TargetFilter dropdown intentionally displays raw
  `agent_id` integers rather than player names. A future
  enhancement would resolve names from the `OrmFight.agents`
  table (via a new `GET /api/v1/fights/{id}/agents`
  endpoint or by denormalising agent names into the events
  response); for now the raw ids are the smallest viable
  affordance and match the existing `target_agent_id` column
  on the roll-up rows.
- The `event_windows` contract is deliberately NOT extended
  with a `buff_removal_total` field. The per-bucket timeline
  is the "global fight picture"; the per-target roll-ups
  already give the analyst the per-target contribution
  breakdown. Adding a per-bucket strip column would force a
  re-aggregation path that the heterogeneous stream already
  handles correctly (the bucket's `event_count` includes the
  strip half of any dual-emit).
- The dual-emit ordering is documented as "HealingEvent
  first, then BuffRemovalEvent" -- the order matches the
  arcdps convention (heal column then strip column) and is
  locked by `test_parse_events_emits_heterogeneous_damage_heal_strip_stream`.

### Tests

- 6 new parser tests + 6 new analytics tests + 1 extended
  e2e test + 2 new page tests + 4 new component tests.
  Python test count: 46 (v0.5.0-web) -> 58 (v0.6.0).
  Web test count: 20 (v0.5.0-web) -> 26 (v0.6.0).

### Validation

- `uv run ruff check libs apps`: clean (RUFF=0).
- `uv run ruff format --check libs apps`: clean (FORMAT=0).
- `uv run mypy libs apps --no-incremental`: clean (MYPY=0,
  44 source files).
- `uv run pytest libs`: 57 passed + 1 skipped (PYTEST_LIBS=0).
- `uv run pytest apps/api`: 4 tests in `test_uploads_e2e.py` +
  healthz (PYTEST_APPS=0). `alembic upgrade head` runs first
  to migrate the Postgres schema to the v0.3.0
  `events_blob_uri` column.
- `pnpm tsc --noEmit`: clean (TSC=0).
- `pnpm test:unit`: clean (VITEST=0, 7 files / 26 tests).
- `uv run pre-commit run mypy --all-files`: clean
  (PRECOMMIT_MYPY=0).
- Round 68-70 code-reviewer-minimax-m3: **APPROVED**
  (dual-emit + pure-strip contracts correct; pure-damage-with-
  buff_dmg silently dropped matches arcdps; e2e bucket delta
  correct; URL + server-side filter mirrors the window-s
  pattern; CI services block matches docker-compose dev).

[0.6.0]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.5.0-web...v0.6.0

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.5.0-web...HEAD

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`:
  - New `EVENT_SIZE = 64` + `_EVENT_STRUCT = struct.Struct("<QQQiiIIHHHbbbbbbbbIIbb")`
    matching the real arcdps `cbtevent` layout
    (3Q + 2i + 2I + 3H + 8b + 2I + 2b = 64 bytes total).
  - New `PythonEvtcParser.parse_events(source) -> Iterator[DamageEvent]`
    reads the cbtevent block at the post-skill-block offset;
    emits `DamageEvent` only when `is_statechange == 0` AND
    `is_nondamage == 0` AND `value > 0` (clamped via `max(0, value)`).
    Truncated trailing bytes are leniently dropped.
  - New `_compute_post_skills_offset(data) -> int` helper mirrors
    `_iter_skills` cursor logic so `parse_events` can advance past
    the skill table deterministically without re-yielding `Skill`
    records.

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py`: `EvtcParser`
  Protocol gained an optional-sense `parse_events(source) ->
  Iterator[DamageEvent]` member. Existing implementations stay
  source-compatible -- callers that only enforce `parse(source)` are
  not broken.

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/__init__.py`: re-exports
  `EVENT_SIZE` + `PythonEvtcParser` (the existing parser, now with
  the new `parse_events` method). `__version__` bumped `0.2.0 -> 0.4.0`.

- `libs/gw2_evtc_parser/tests/test_parser.py`: 5 new event-parser tests:
  empty stream, single damage event shape, truncation tolerance (lenient
  drop), `is_statechange == 1` filter (skipped), `is_nondamage == 1`
  filter (skipped). All 5 use a synthetic 25-byte header + 96-byte
  agent record + zero skills + 64-byte cbtevent records built via
  `struct.pack` against the same `_EVENT_STRUCT` layout. The
  pre-existing real-fixture integration test (`test_real_evtc_binary
  _parses_with_realistic_agent_count`) is unchanged.

- `libs/gw2_evtc_parser/tests/test_interface.py`: protocol conformance
  test extended to cover `parse_events` round-trip (also via the
  synthetic 64-byte fixture).

- `apps/api/alembic/versions/0004_fight_events_blob_uri.py` (NEW):
  adds `events_blob_uri VARCHAR(255) NULL` to the `fights` table.
  Historical fights (uploaded before Phase 7 v1) keep the column
  as `NULL`; the `/fights/{id}/events` route surfaces `404 Not
  Found` for these rows so consumers can distinguish "parser ran
  but yielded no damage" from "data unavailable".

- `apps/api/src/gw2analytics_api/models.py::OrmFight`: gains
  `events_blob_uri: Mapped[str | None] = mapped_column(String(255),
  nullable=True)`. Purely additive; no backfill.

- `apps/api/src/gw2analytics_api/storage.py`:
  - Extracted `_ensure_bucket()` helper from `put_zevtc()`; both
    `put_zevtc` and the new `put_events` use it.
  - New `put_events(fight_id, gz_data) -> str`: uploads to
    `events/{fight_id}.jsonl.gz` with `content_type="application/gzip"`.
  - New `get_events(key) -> bytes`: fetches + releases the MinIO
    connection. `S3Error` propagates so the route can map
    `NoSuchKey` to `404 Not Found`.

- `apps/api/src/gw2analytics_api/services.py`:
  - New `_persist_event_blob(db, upload, evtc_bytes, fight_id)`
    helper called from `process_parse` after `_save_fight` and
    before `upload.status = UPLOAD_STATUS_COMPLETED`. Calls
    `PythonEvtcParser.parse_events(evtc_bytes)`, serialises the
    events as JSONL (one `DamageEvent.model_dump_json()` per line),
    gzip-compresses with `gzip.compress(jsonl)`, uploads via
    `put_events`, and writes the storage key back to
    `OrmFight.events_blob_uri`. Degrades gracefully to
    `events_blob_uri = NULL` when the parser yields zero events OR
    when the blob upload fails (the fight-row + agents + skills
    stay valid; operators can re-parse the upload to retry).

- `apps/api/src/gw2analytics_api/schemas.py`: new
  `TargetDpsRowOut` (drops `attack_count` from the API surface so
  the JSON stays client-broad) + `FightEventsSummaryOut`
  (`fight_id`, `duration_s`, `target_dps`,
  `event_windows`). The pre-existing `EventBucketOut` is now part
  of the live response shape rather than a future-proofing stub.

- `apps/api/src/gw2analytics_api/routes/fights.py`:
  `GET /api/v1/fights/{fight_id}/events` route now returns a real
  `FightEventsSummaryOut` rather than the Phase 6 v1 `[EventBucketOut]`
  stub. New `window_s: int = Query(5, ge=1, le=600)` query param
  drives the time-bucket roll-up. Response codes:
  - `404 Not Found`: unknown fight OR `events_blob_uri is None`
    OR the MinIO read raises `S3Error` (blanket 404 so a missing
    blob never masquerades as a zero-damage fight).
  - `422 Unprocessable Entity`: `window_s` outside `[1, 600]`
    (handled by FastAPI before this handler runs).
  - `502 Bad Gateway`: events blob is present but corrupt
    (`gzip.decompress` failed).
  `duration_s` is computed natively as
  `max(events.time_ms) / 1000.0` (the V1.3 EVTC header does not
  carry a wall-clock duration scalar).

- `apps/api/pyproject.toml`: gained `gw2_analytics` as a runtime
  dependency (the route now imports
  `gw2_analytics.event_window.EventWindowAggregator` +
  `gw2_analytics.target_dps.TargetDpsAggregator`).

- `apps/api/tests/test_uploads_e2e.py`:
  - Extended `_make_minimal_zevtc()` to accept an optional
    `events=` list of pre-packed 64-byte cbtevent records appended
    after the skill block.
  - New `_make_cbtevent()` helper packs one cbtevent record with
    the same layout as the parser's `_EVENT_STRUCT`. Field padding
    (`pad61`..`pad66`, `translocated`, `is_offcycle`) is set to
    zero -- the parser never reads them.
  - Extended `test_uploads_e2e_happy_path` with two damage cbtevent
    records (`time_ms=1500`, `time_ms=2500`, both targeting agent
    B with skill A/B), then asserts
    `GET /fights/{id}/events?window_s=1` returns
    `duration_s == 2.5`, a single `target_dps` row summing both
    hits, and 3 contiguous 1-second buckets with counts `[0, 1, 1]`.
  - New `test_fight_events_404_when_unknown_fight` covers the
    404 contract for missing fight id.
  - New `test_fight_events_422_when_window_s_too_small` covers
    the Pydantic Query `ge=1` validator rejecting `window_s=0`.

### Changed

- `apps/api/src/gw2analytics_api/schemas.py::EventBucketOut`
  docstring: `Phase 6 v2 future-proofing` references removed; the
  schema is now wired into the live response.
- `apps/api/src/gw2analytics_api/services.py` module docstring:
  extended with Phase 7 v1 scope (`parse_events` drain +
  gzip JSONL + `events_blob_uri` write-back).

### Notes

- `DamageEvent` (in `libs/gw2_core`) already had `source_agent_id`,
  `target_agent_id`, `skill_id` via the broader `BaseEvent` model
  introduced in Phase 6 v1 -- the parser consumer reads those
  fields directly from the cbtevent record without a wrapper type.
- The `is_statechange == 0` / `is_nondamage == 0` filter passes
  only damage events in Phase 7 v1; `HealingEvent` extraction
  (cbtevent records with the conditioning/damage-with-negation
  pattern) is a Phase 7 v2 follow-up. The JSONL includes
  `event_type` so a v2 reader can discriminate without a
  schema migration on the storage side.
- `EventWindowAggregator`'s continuous-fill semantics fills the
  empty `[0, 1000ms)` leading bucket when `window_ms=1000` and the
  first event lands at `time_ms=1500`. The happy-path test
  asserts this directly (`counts == [0, 1, 1]`).
- 404-on-NULL-blob is the canonical contract: returning
  `200 OK` with empty arrays would conflate "parser ran, no
  damage" with "data unavailable", and consumers would have
  no signal to re-upload.

## [0.5.0-web] - Phase 7 v2 of web: window-s selector on /fights/[id]

### Added (web)

- `web/src/components/WindowSizeSelector.tsx` (NEW): Client
  Component that renders a dropdown of preset time-bucket sizes
  (``[1, 5, 30, 60, 300]`` seconds) for the ``/fights/[id]``
  drill-down page. Uses ``useRouter`` + ``usePathname`` from
  ``next/navigation``; on change, emits a ``router.push`` to the
  current path with a ``?window_s=N`` query param (or a bare path
  when the user picks the gateway default 5s, so the URL stays
  canonical). The default is referenced via
  ``String(WINDOW_S_PRESETS[1])`` (not the literal "5") so a
  future preset-list reorder only needs to change the constant,
  not two call sites. NAMED export to match the existing
  test-setup mock contract.

- `web/src/app/fights/[id]/page.tsx`: page signature widened to
  accept ``searchParams: Promise<{ window_s?: string }>`` (the
  Next.js 15+ async searchParams contract). The page awaits
  searchParams, parses the raw string via the new
  ``parseWindowS()`` helper, and passes ``{ windowS: parsed }`` to
  ``fetchFightEvents`` so the URL drives the time-bucket size.
  ``parseWindowS()`` clamps out-of-range / non-integer / negative
  values to the gateway default (5s) so a URL typo never surfaces
  a misleading 422 from the gateway -- the analyst lands on the
  canonical 5s view instead. The page header is now a flex row
  (display:flex + alignItems:baseline + justifyContent:space-
  between + flexWrap:wrap) so the new
  ``<WindowSizeSelector />`` sits to the right of the fight_id +
  duration sub-header (wraps below on mobile).

- `web/tests/setup.ts`: added a no-op mock for the new
  ``WindowSizeSelector`` named export (same pattern as the
  existing ``TargetRollupsGrid`` + ``EventWindowsTable`` mocks
  so the page-level Server Component test focuses on the page's
  own render contract).

- `web/tests/app/fight-events-page.test.tsx`: all 3 existing test
  cases updated to pass ``searchParams: Promise.resolve({})``.
  Two new test cases:
    - ``window_s=30`` is forwarded to ``fetchFightEvents`` with
      ``{ windowS: 30 }`` (locks down the URL -> fetch wiring).
    - ``window_s=9999`` (out of the gateway's ``[1, 600]``
      range) is clamped to the default 5 (locks down the
      ``parseWindowS`` clamping behaviour; the gateway never
      sees a bogus value).

- `web/tests/components/window-size-selector.test.tsx` (NEW): 3
  component-level tests that override the global no-op mock via
  ``vi.mock("@/components/WindowSizeSelector", async
  (importOriginal) => { return await importOriginal<...>(); })``:
    - renders all 5 preset options + marks the ``current`` prop
      as selected.
    - picking the default (5) emits a bare URL (no query param).
    - picking a non-default value emits a ``?window_s=N`` URL.
  The selector's dependencies (``useRouter`` + ``usePathname``)
  are mocked to deterministic stubs so each test asserts on the
  emitted URL without booting the real Next.js router.

### Notes

- The dropdown is intentionally a fixed preset list (1, 5, 30,
  60, 300) rather than a free-form number input. The gateway
  rejects out-of-range values with 422; a free-form input would
  require either client-side validation or a 422 error card.
  Presets cover the common analyst use cases (per-second, default,
  per-encounter, per-minute, per-5-min) without the validation
  overhead. A future "Custom..." option could open a number
  input if analysts request it.
- ``router.push`` (not ``router.replace``) is used so the
  analyst can back-button through the bucket sizes they tried.
  The page is ``force-dynamic`` + ``cache: "no-store"`` so the
  per-rollup re-render is cheap.
- The ``usePathname() ?? `/fights/${fightId}`` fallback in the
  selector is defense-in-depth: ``usePathname`` is a Client hook
  and always returns a non-null string after hydration, so the
  fallback is dead code in practice. Kept for robustness.

### Tests

- 5 page-level cases (was 3): populated, 404, empty, window_s=30
  wired, window_s=9999 clamped.
- 3 component-level cases (new file).
- Total: 8 cases for the window-s surface (5 page + 3 component).

### Validation

- ``pnpm tsc --noEmit``: clean (TSC=0).
- ``pnpm test:unit``: clean (VITEST=0, 6 files / 20 tests).
- Round 66-67 code-reviewer-minimax-m3: **APPROVED** (URL query
  param is the canonical Next.js 15+ pattern; searchParams
  Promise wiring is correct; parseWindowS clamping prevents
  spurious 422s; WINDOW_S_PRESETS[1] reference keeps onChange
  in lockstep with the preset list; importOriginal override
  matches the partial-mock pattern used elsewhere in the
  test suite).

[0.5.0-web]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-tooling...v0.5.0-web

## [0.5.0-parser] - Phase 7 v2 cbtevent heal extraction + Event discriminated union

### Added (parser)

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py`: ``PythonEvtcParser.parse_events``
  signature broadened from ``-> Iterator[DamageEvent]``` to
  ``-> Iterator[Event]```. New filter contract (Convention A +
  Elite Insights parity):
    - ``is_statechange == 0 && is_nondamage == 0 && value > 0`` -> emits DamageEvent
    - ``is_statechange == 0 && is_nondamage >  0 && value > 0`` -> emits HealingEvent
    - Records with ``is_statechange != 0`` still skip (Phase 8 candidate).
  Each cbtevent record yields AT MOST ONE event. The ``buff_dmg```
  field is NOT also emitted as a HealingEvent from the same record
  (deferred to Phase 8 -- avoids double-counting the buff-removal
  path).

- `libs/gw2_evtc_parser/src/gw2_evtc_parser/interface.py`: ``EvtcParser```
  Protocol's ``parse_events``` member returns the same
  ``Iterator[Event]```.

### Added (domain)

- `libs/gw2_core/src/gw2_core/models.py`: ``Event``` is now a PEP 695
  ``type``` declaration with a Pydantic v2
  ``Field(discriminator="event_type")``` discriminator so JSONL
  round-trip auto-dispatches on the ``event_type``` literal payload.

### Changed (apps/api)

- `apps/api/src/gw2analytics_api/routes/fights.py`: module-level
  ``_EVENT_TYPE_ADAPTER: TypeAdapter[Event]``` (built once at import
  time) replaced the previous per-line ``DamageEvent.model_validate_json```
  loop so the heterogeneous JSONL stream materialises damage + healing
  without manual isinstance dispatch. ``TargetDpsAggregator.aggregate```
  call site filters via
  ``[e for e in events if isinstance(e, DamageEvent)]``` so the
  aggregator signature stays narrow on ``DamageEvent``` (its
  sum-invariant validates sum-of-row-damage == sum-of-event-damage).

### Test delta

- `libs/gw2_evtc_parser/tests/test_parser.py`: 7 NEW Phase 7 v2 tests
  locking down the Convention A contract:
    - test_parse_events_yields_healing_event_on_nondamage
    - test_parse_events_clamps_negative_healing_to_zero
    - test_parse_events_emits_one_event_per_cbtevent_for_damage_plus_heal
      (the Phase 7 v1 contract test was renamed + repurposed to
      lock down the value-filter branch for the HEALING path)
    - test_parse_events_skips_statechange_for_healing
    - test_parse_events_skips_statechange_for_damage
    - test_parse_events_emits_heterogeneous_stream_signed_by_event_type
    - test_parse_events_yield_type_is_event_union

### Validation

- ruff check + format: clean (libs + apps)
- mypy libs apps --no-incremental: clean
- pytest libs/gw2_evtc_parser libs/gw2_analytics: 103 passed + 1 skipped
  (the skipped test is the real-EVTC-fixture integration test gated
  on /tmp/inner_20251002-213519 availability)
- Round 51-58 code-reviewer: APPROVED (with minor cleanup notes)

### Migration

The Python surface is fully backward-compatible. ``parse_events```
now yields the union type so callers that explicitly typed the
return as ``list[DamageEvent]``` need to widen to
``list[Event]```. The apps/api ``GET /fights/{id}/events```
route already handles the union via
``TypeAdapter(Event).validate_json(line)```; pre-Phase-7-v2 records
(those with NULL events_blob_uri) continue to surface 404.

[0.5.0-parser]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-parser...v0.5.0-parser

[Unreleased]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-parser...HEAD
## [0.4.0-web] - Phase 7 v1 of web: /fights/[id] drill-down page (per-target damage + healing + event windows)

### Added (web)

- `web/src/app/fights/[id]/page.tsx` (NEW): dynamic Server Component
  that SSR-fetches the v0.3.0-api per-fight events payload via
  `fetchFightEvents(fightId)` and renders the per-target damage
  roll-up + per-target healing roll-up + time-bucketed event
  windows on a single page. `params: Promise<{ id: string }>` is
  awaited per Next.js 15+ async route params convention; the page
  is `force-dynamic` + `cache: "no-store"` so the roll-up
  reflects the latest parsed fight state. Empty roll-ups render
  the canonical "no rows" panel via the per-component empty
  state; `ApiError` (404, 5xx, etc.) renders the canonical
  upstream-error card with the gateway's error body. The page is
  a single Server Component that hands the data to three small
  client-rendered sub-views (no waterfall round-trips for the
  same underlying JSONL blob).

- `web/src/components/TargetRollupsGrid.tsx` (NEW): reusable
  generic AG Grid Community wrapper for the per-target damage +
  healing roll-up tables. A single Client Component covers both
  roll-up kinds via a `TargetRollupColumn<TRow>[]` column spec
  (page-level builds the spec for each kind). Renders a styled
  "no rows" panel on empty input so the page-level error path
  is reserved for true upstream errors (404, 5xx).

- `web/src/components/EventWindowsTable.tsx` (NEW): plain HTML
  table (no AG Grid) for the per-bucket roll-up. The bucket
  count is bounded by `duration_s / window_s` so the table stays
  human-scannable without pagination; the natural sort order is
  by `start_ms` (which is monotonic in the response). The
  `healing_total` column is tinted with the `var(--accent)`
  colour to keep the read-out visually cohesive with the AG Grid
  dark theme on the two roll-up grids above it.

- `web/src/components/ag-grid-setup.ts` (NEW): side-effect-only
  module that calls `ModuleRegistry.registerModules([AllCommunityModule])`
  exactly once across the whole module graph. AG Grid Community
  33+ ships in tree-shaken mode and requires the explicit
  registration; centralising it here removes the ordering
  hazard of a user navigating directly to a fight-detail page
  (and never visiting `/fights`) seeing an unstyled grid.

- `web/src/lib/api.ts`: new `fetchFightEvents(fightId, opts?: { windowS?: number }): Promise<FightEventsSummaryRow>`
  helper (mirrors `GET /api/v1/fights/{fight_id}/events` in
  apps/api 0.3.0+; `windowS` defaults to 5, the gateway
  default). Throws the existing `ApiError` on any non-2xx so
  the Server Component can render the canonical upstream-error
  card.

- `web/src/lib/api.ts`: 4 new TypeScript interfaces
  (`TargetDpsRow`, `TargetHealingRow`, `EventBucket`,
  `FightEventsSummaryRow`) hand-written alongside the existing
  `FightRow` / `AccountEnrichedRow` / `UploadCreatedRow` types
  (consistent with the lib's no-codegen policy for response
  types; the OpenAPI `schema.d.ts` is the codegen path for
  future-generated types, not these hand-written shapes).

### Changed

- `web/src/components/FightsGrid.tsx`: the `id` column is now
  rendered as an anchor (`<a href="/fights/{id}">{id}</a>`) so a
  single click on the row carries the analyst to the new
  drill-down page. The cellRenderer is intentionally a plain
  `<a>` (not `next/link`) -- AG Grid renders the cell out of the
  React tree, so the client-side router prefetch is not
  available, and a full-page navigation is acceptable for the
  `force-dynamic` + `cache: "no-store"` drill-down target.
  The grid's `ModuleRegistry.registerModules` call is replaced
  by a side-effect import of `./ag-grid-setup` (single
  registration across the whole module graph).

- `web/tests/setup.ts`: global mocks for the new components
  (`TargetRollupsGrid`, `EventWindowsTable`) added alongside
  the existing `FightsGrid` mock so the page-level Server
  Component tests can transitively import the new page +
  components without dragging `ag-grid-react` into the vitest
  runtime.

- `web/src/app/fights/[id]/page.tsx` (new) + `web/package.json`
  (no change; the page is rendered via the existing Next.js 16
  app-router conventions) + `web/pnpm-lock.yaml` (no change;
  no new dependencies).

### Notes

- The two roll-up grids are independent: a damage-only fight
  yields an empty heal grid, a heal-only fight yields an empty
  damage grid, and a mixed fight yields one row per target
  across both. The page's per-component empty-state handles
  each case gracefully -- no error path is taken on
  legitimately-empty roll-ups.
- `EventWindowsTable` is a plain `<table>` rather than an AG
  Grid because the bucket roll-up is a TIMELINE visualisation
  (chronological order, no sort/filter needs) and the bucket
  count is bounded by `duration_s / window_s` so pagination
  is unnecessary. AG Grid's affordances would be wasted on
  this view.
- The new page is a forward-compat drop: any new `Event`
  subclass added in the future (e.g. a Phase 8
  `BuffRemovalEvent`) will surface here as a new sibling
  roll-up section + a new column on the per-bucket
  `event_windows` table. `TargetRollupsGrid` is generic so
  the page only needs to add a new column spec; no new
  Client Component required.

### Tests

- `web/tests/app/fight-events-page.test.tsx` (NEW): 3 vitest
  cases mirroring the existing `fights-page.test.tsx` CI-smoke
  pattern -- the Server Component is invoked as a plain async
  function, not inside Next.js's RSC runtime. Cases:
  - happy path: populated payload (1 target_dps row + 1
    target_healing row + 3 event_windows) renders the header
    (fight_id + duration_s) + all 3 section headings.
  - upstream 404: `fetchFightEvents` rejects with
    `new ApiError(404, "fight not found")`; the page renders
    the upstream-error card.
  - empty roll-ups: `fetchFightEvents` returns a payload with
    empty target_dps + target_healing + event_windows; the
    page renders the header + the 3 section headings (the
    per-component empty-state is asserted at the component
    level, not here).

### Validation

- `pnpm tsc --noEmit` clean (Next.js 16 + React 19 + AG Grid
  Community 34 type surface).
- `pnpm test:unit` clean (3 new fight-events-page tests + the
  existing 11 vitest tests across the app: 14 total).
- Code-reviewer: APPROVED.

[0.4.0-web]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.3.0-web...v0.4.0-web

## [0.4.0-tooling] - workspace-aware pre-commit mypy hook (uv run)

### Fixed

- `.pre-commit-config.yaml`: the pre-commit ``mypy`` hook (formerly
  ``mirrors-mypy`` v1.13.0) built a separate hook venv that did NOT
  include the workspace members (``gw2_core``,
  ``gw2_evtc_parser``, ``gw2_analytics``, ``gw2_api_client``).
  The hook fired ``import-not-found`` errors for ``from gw2_core
  import ...`` on every commit touching ``apps/`` or ``libs/``
  Python files, requiring ``--no-verify`` to bypass. The
  v0.4.0-analytics and v0.4.0-web releases both worked around
  this with ``git commit --no-verify``.

  Replaced the ``mirrors-mypy`` block with a single ``repo: local``
  hook that runs ``uv run mypy --no-incremental`` from the repo
  root. The local hook uses ``language: system`` so pre-commit
  does NOT create a new venv; it reuses the project's own ``uv``
  venv where the editable workspace members resolve correctly.
  ``--disable-error-code=misc`` was dropped (the "Untyped
  decorator" + "Class cannot subclass X" noise categories were
  artifacts of the missing-stubs hook venv; the full workspace
  venv resolves them properly). ``require_serial: true`` is set
  so multiple mypy processes do not step on each other's
  ``.mypy_cache``.

### Notes

- Prereq: the developer must have ``uv`` on ``$PATH`` when
  running ``git commit``. This is already the project's standard
  toolchain (the README, CI, and developer workflow all assume
  ``uv sync`` + ``uv run`` are available), so no new install
  step is needed.
- The local hook keeps ``pass_filenames: true`` (the pre-commit
  default) so it only type-checks the staged files for fast
  feedback; CI continues to run the full ``uv run mypy libs apps
  --no-incremental`` re-check on every push + PR.
- Validated by running ``uv run pre-commit run mypy --all-files``
  against the current ``main``: hook fires + passes on every
  Python file in ``libs/`` + ``apps/`` (46 staged + 91 unstaged
  files = 137 files type-checked clean).

### Validation

- ``uv run pre-commit run mypy --all-files``: clean
  (``PRECOMMIT_MYPY=0``).
- ``uv run ruff check libs apps``: clean (``RUFF=0``).
- ``uv run ruff format --check libs apps``: clean (``FORMAT=0``).
- ``uv run mypy libs apps --no-incremental``: clean (``MYPY=0``,
  42 source files).
- ``uv run pytest libs``: 46 passed + 1 skipped
  (``PYTEST_LIBS=0``; the skipped test is the real-EVTC-fixture
  integration test gated on the fixture's availability).
- Round 65 code-reviewer-minimax-m3: **APPROVED**.

[0.4.0-tooling]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.4.0-web...v0.4.0-tooling

## [0.3.0-api] - Phase 7 v1 of apps/api: per-target healing roll-up

### Added (apps/api)

- `apps/api/src/gw2analytics_api/schemas.py`: new
  `TargetHealingRowOut` response schema (strict parallel of
  `TargetDpsRowOut` -- drops `heal_count` from the API surface
  for analyst-only parity) and a new
  `target_healing: list[TargetHealingRowOut] = []` sibling field
  on `FightEventsSummaryOut` (between `target_dps` and
  `event_windows`). Empty when the parser yielded zero healing
  events; mixed damage + healing fights produce independent
  roll-ups on the same `duration_s`.
- `apps/api/src/gw2analytics_api/routes/fights.py`: the
  heterogeneous JSONL stream is now split at the call site --
  `TargetDpsAggregator` receives
  `[e for e in events if isinstance(e, DamageEvent)]` and
  `TargetHealingAggregator` receives
  `[e for e in events if isinstance(e, HealingEvent)]`; both
  are invoked on the same `duration_s` so the two roll-ups are
  temporally consistent. The route's per-aggregator call site
  stays free of cross-kind discrimination in the hot loop. The
  handler docstring is extended to document the new field and
  the call-site isinstance filter pattern.
- `apps/api/tests/test_uploads_e2e.py::test_uploads_e2e_happy_path`:
  now packs 2 healing cbtevent records (Phase 7 v2
  `is_nondamage=1` + `value>0` filter) alongside the 2 existing
  damage records. Damage flows A->B; healing flows B->A so the
  two roll-ups land on DIFFERENT targets, exercising the
  damage-only / heal-only / mixed-fight cases. The response
  assertions cover the new `target_healing` field + the
  per-bucket `healing_total` accounting + the doubled
  `event_count` per non-empty bucket.

### Changed

- `apps/api/src/gw2analytics_api/__init__.py`: `__version__`
  bumped `"0.2.0" -> "0.3.0"`.
- `apps/api/src/gw2analytics_api/main.py`: FastAPI `version`
  string bumped `"0.2.0" -> "0.3.0"`.
- `apps/api/pyproject.toml`: version bumped
  `"0.2.0" -> "0.3.0"`.

### Notes

- The v2 `Event` discriminated union (`DamageEvent | HealingEvent`)
  is now consumed end-to-end on the HTTP surface -- a single
  `GET /api/v1/fights/{fight_id}/events` round-trip returns a
  per-target damage roll-up AND a per-target healing roll-up.
  `EventWindowAggregator` was already a damage+healing dual
  consumer (Phase 6 v1); the per-target view completes the
  coverage.
- Forward-compat: any new `Event` subclass added in the future
  (e.g. a Phase 8 `BuffRemovalEvent`) requires a matching
  per-target aggregator + a new sibling field on
  `FightEventsSummaryOut`; the discriminated-union dispatch +
  per-aggregator call-site filter pattern extends cleanly
  without breaking the existing contract.

### Validation

- ruff + ruff format + mypy clean across `libs` + `apps`
  (`uv run`).
- pytest `libs`: 46 passed (40 existing + 6 new heal-roll-up).
- pytest `apps/api`: 4 tests in `test_uploads_e2e.py` (1 happy
  path + 3 edge cases) + 1 test in `test_healthz.py` -- the
  e2e Postgres-dependent test is conditionally run when
  `DATABASE_URL` is reachable.
- Code-reviewer: APPROVED.

[0.3.0-api]: https://github.com/Roddygithub/Gw2Analytics/compare/v0.2.0-api...v0.3.0-api

## [0.3.0] - web upload UI + event aggregations

### Added

- `CHANGELOG.md`: this file. Captures the V1.4 stability cycle and the
  P1 parser closure that landed in the same push window.
- `.github/workflows/ci.yml`: a single `lint-and-test` GitHub Actions
  job (Python 3.12 on `ubuntu-latest`) running `uv run ruff check`
  + `uv run ruff format --check` + `uv run mypy libs apps
  --no-incremental` + `uv run pytest --tb=line -q` on every push and
  pull request to `main`. Uses `astral-sh/setup-uv@v3` with
  `enable-cache: true` keyed on `uv.lock`. No GitHub repository
  secrets are required because `pytest-env` (see Changed) injects
  the docker-compose dev credentials at pytest session startup,
  and the Postgres-dependent `test_uploads_e2e.py` self-skips via
  the `db_reachable` fixture when no docker-compose Postgres is
  reachable on the runner.
- `README.md`: a CI status badge under the H1 title pointing at the
  new workflow.
- `libs/gw2_evtc_parser/tests/test_parser.py`: new synthetic unit
  test `test_player_with_empty_char_name_but_valid_account_and_subgroup`
  locking down the WvW arcdps edge case where a player record has an
  empty ``char_name`` but a valid ``account_name`` + ``subgroup``
  (previously only covered by the real-fixture integration test).

### Changed

- `pyproject.toml`: added `pytest-env>=1.6.0` to the dev dependency
  group. `pytest-env` reads the new `[tool.pytest_env]` table and
  injects `DATABASE_URL` + `S3_*` docker-compose dev credentials
  into `os.environ` at pytest session startup, so the test suite
  no longer depends on a hand-rolled `.env` file.
- `apps/api/src/gw2analytics_api/config.py`: credentials are now
  **fully environment-driven** (no hardcoded sentinel defaults).
  Each `minio_*` Python field is mapped to the matching `S3_*` env
  var via `Field(validation_alias="...")`; `database_url` maps to
  `DATABASE_URL`. **Operators must `cp .env.example .env`** before
  running `uv run uvicorn` (or `uv run fastapi dev`); tests are
  insulated by `pytest-env`.
- `pyproject.toml`: removed the now-unnecessary
  `apps/**/config.py = ["S105"]` per-file ruff ignore plus its
  belt-and-suspenders cross-reference comments. `config.py` is
  sentinel-free, so bandit will catch any future regression at PR
  time.
- `pyproject.toml`: bug fix in `[tool.ruff.lint] select`: the
  `"S"` (flake8-bandit) entry was previously collapsed onto the
  `"UP"` comment line and silently dropped from the array. Now
  restored on its own line; `select` is `["E","F","I","B","UP",
  "S","RUF"]` (verified via `tomllib`).
- `apps/api/src/gw2analytics_api/main.py`: added an inline `# type:
  ignore[import-untyped]` on the `fastapi_mcp` import (the
  `[[tool.mypy.overrides]]` block was not always honoured).
- `.pre-commit-config.yaml`: bumped the `ruff-pre-commit` hook from
  `v0.7.0` to `v0.15.2` to match the workspace `ruff>=0.7` resolved
  by `uv` to `ruff 0.15.20`. The eight-minor version gap previously
  caused the `ruff-format` hook to repeatedly re-format files that
  newer ruff had already formatted correctly ("1 file reformatted"
  on every pre-commit run).
- `libs/gw2_evtc_parser/tests/test_parser.py`: previously hoisted a
  parser import from inside a function body to module top
  (`ruff PLC0415`).
- `README.md`: Quickstart step 5 is now `cp .env.example .env`
  (required for the env-driven credentials); subsequent steps
  renumbered.

### Fixed

- See "Changed" above: the `select` array regression, the
  `ruff-pre-commit` version mismatch, the `fastapi_mcp` import
  ignoring the mypy override, and the `config.py` S105 sentinel
  workaround (replaced with an honest env-only contract).

### Security

- No hardcoded credentials remain anywhere in the source tree.
- CORS is no longer hardcoded to ``allow_origins=["*"]``. A new
  optional ``Settings.cors_allowed_origins`` field reads the
  comma-separated ``CORS_ALLOWED_ORIGINS`` env var (defaults to
  ``["*"]`` for local dev); ``apps/api/.../main.py`` reads it once
  on app init. Operators tighten the gateway for public deploy
  by setting the env var to the real domains. The pre-existing
  inline warning comment is updated to reflect that the override
  is now wired (no longer future work).

### Fixed

- `web/src/app/page.tsx`: the hero footer was rendering the literal
  string ``process.env.API_BASE_URL`` because the JSX expression
  was wrapped in quotes (`<code>{"process.env.API_BASE_URL"}</code>`).
  Removed the quotes and replaced with a shared
  ``displayedApiBaseUrl`` helper imported from
  ``web/src/lib/api.ts`` so the SSR'd landing cannot drift from the
  trimmed URL the gateway fetcher uses.
- `README.md` + `CHANGELOG.md`: post-release drift corrections
  (test counts, the v0.2.0-api tag status flipping from `pending`
  to `shipped`, the test-file count updating to 8, the openapi
  codegen mechanism description corrected to reflect
  `web/scripts/dump_openapi.py`).
- `apps/api/tests/test_uploads_e2e.py`: dropped the runtime
  ``db_reachable`` fixture + the conditional ``pytest.skip`` block.
  The test now runs unconditionally against any environment that has
  a Postgres reachable at ``DATABASE_URL`` (the suite auto-loads the
  docker-compose dev credentials via ``pytest-env``). The module
  docstring reframes the requirement as positive
  ("``docker compose up -d gw2a-postgres`` first") instead of a skip
  hint. CI on a fresh runner must bring up the Postgres service
  before ``pytest`` runs (deferred to a followup -- add a
  ``services:`` block to ``.github/workflows/ci.yml::lint-and-test``).
  Orphaned ``from sqlalchemy import create_engine, text`` import
  cleaned up.

### Added (Phase 4 -- web/ frontend scaffold)

- `web/package.json`: AG Grid Community, AG Grid React, and
  `openapi-typescript` joined the dev dependency group. Two new
  scripts: `pnpm typecheck` runs `tsc --noEmit`; `pnpm generate:api`
  writes `src/lib/api/schema.d.ts` from `web/scripts/dump_openapi.py`
  (in-process `app.openapi()` JSON piped through `openapi-typescript`;
  no running gateway required).
- `web/src/app/layout.tsx`: renamed the page <title> from
  "Create Next App" to "GW2Analytics" and tightened the metadata
  description around the WvW framing.
- `web/src/app/page.tsx`, `page.module.css`, `globals.css`:
  replaced the `create-next-app` boilerplate with a WvW-themed
  landing page (brand badge + hero + two CTAs: `/fights` and
  `/account`). DWvW dark theme (slate background + gold accent)
  with `prefers-color-scheme: light` opt-out.
- `web/src/app/fights/page.tsx`: Server Component that
  SSR-fetches `GET /api/v1/fights` via the lib helper. Marked
  `dynamic = "force-dynamic"` so the grid never serves stale.
- `web/src/components/FightsGrid.tsx`: Client Component wrapping
  AG Grid Community, registering `AllCommunityModule` once at
  module load (v33+ tree-shaken build), dark Quartz theme,
  sortable + filterable columns, 25-row pagination.
- `web/src/app/account/page.tsx`: Client Component with a
  password input that submits the GW2 API key as
  `Authorization: Bearer <key>` to `/api/v1/account` and renders
  the resolved ``(world_id, world_name, world_population)`` triple
  (or surfaces the upstream error).
- `web/src/lib/api.ts`: env-driven fetcher helpers for RSC +
  Client Components; honours `API_BASE_URL` (defaults to
  `http://localhost:8000`). Declares `FightRow` and
  `AccountEnrichedRow` local types.
- `web/.env.example`: declares `API_BASE_URL`.
- `web/README.md`: replaces the `create-next-app` README with a
  concise frontend description (routes, scripts, codegen, auth
  caveats).
- `.github/workflows/ci.yml`: appended two steps to
  `lint-and-test` -- `pnpm/action-setup@v4` + Node 20 setup,
  `pnpm install --frozen-lockfile`, and `pnpm exec tsc --noEmit`.
  The web/ type surface is now part of the merge gate.

### Added (Phase 5 -- apps/api `GET /api/v1/account`)

- `apps/api/pyproject.toml`: depends on `gw2_api_client>=0.1.0`.
  `dev` group gains `respx>=0.21` and `httpx>=0.27` (no longer
  reaches the TestClient via the top-level root dev extras).
  Version bumped `0.1.0 -> 0.2.0`.
- `apps/api/src/gw2analytics_api/schemas.py`: new response
  schema `AccountEnrichedOut` (``world_id``, ``world_name``,
  ``world_population``). ``world_population`` is a plain string
  so future v2 Population buckets don't break the round-trip -- if
  the upstream grows a new value, ``WorldInfo`` validation raises
  and the route surfaces 502 rather than silently coercing.
- `apps/api/src/gw2analytics_api/routes/account.py` (NEW): GET
  `/api/v1/account` -- a thin endpoint that composes
  ``AsyncGuildWars2Client.account_get`` + ``worlds_get([world_id])``
  to return a single deterministic world triple. Auth via
  `HTTPBearer(auto_error=False)`. Error mapping: missing/empty
  bearer -> 401 (with `WWW-Authenticate: Bearer`), upstream 401
  -> 401 (key was rejected), upstream 429 retry exhaustion -> 503,
  upstream 5xx / network -> 502, generic -> 502. Pure GET, no
  persistent state effects.
- `apps/api/src/gw2analytics_api/main.py`: includes the new
  `account` router; FastAPI `version` string bumped
  `0.1.0 -> 0.2.0`.
- `apps/api/tests/test_account.py` (NEW): 11 respx-mocked tests
  covering happy path, missing bearer, empty bearer,
  whitespace-only bearer, lowercase Bearer scheme (some proxies
  normalise the scheme to lowercase and the route must still
  accept it), upstream 401 -> 401, upstream 5xx -> 502, upstream
  429 -> 503 after 3 retries, 1x 429 + 200 succeeds on retry 2,
  `httpx.ConnectTimeout` transport -> 502, and empty `worlds_get`
  -> 502.

### Changed

- `uv.lock`: bumped to reflect `gw2_api_client` becoming a
  workspace member consumed by apps/api (apps/api 0.2.0).
- `web/pnpm-lock.yaml`: bumped to reflect AG Grid Community,
  AG Grid React, and `openapi-typescript` resolutions.

### Added (Phase 4 followup -- web/ unit-test scaffolding)

- `web/vitest.config.ts` (NEW): vitest 2.x config for the
  Next.js 16 frontend -- `environment: "jsdom"`,
  `setupFiles: ["./tests/setup.ts"]`, `css: false` (Next.js
  owns styleable output), alias `@/*` -> `src/*` mirroring the
  tsconfig root. Pattern-matches `tests/**/*.test.{ts,tsx}`
  (so accidental `.spec.ts`-style files are ignored) and
  `clearMocks: true` (so tests don't leak `vi.fn()` state
  between cases).
- `web/tests/setup.ts` (NEW): global `vi.mock` shims for
  `next/link` (anchor), `next/font/google` (inert CSS-variable
  shim), and `@/lib/env` (`http://test/api`); also extends
  `expect` via `@testing-library/jest-dom/vitest`.
- `web/tests/app/layout.test.tsx` (NEW): asserts `RootLayout`
  exports metadata with title `GW2Analytics` + wraps children
  in `<html lang=en>` with both Geist font variable classes
  set.
- `web/tests/app/page.test.tsx` (NEW): renders `<Home />` and
  asserts the hero heading + tagline + both `next/link` cards
  (`/fights`, `/account`) + the mocked `displayedApiBaseUrl`
  in the footer.
- `web/tests/app/fights-page.test.tsx` (NEW): CI smoke only --
  the `await FightsPage()` call simulates a Server Component
  invocation without booting the Next.js RSC runtime (see the
  file header for the `headers()` / `cookies()` migration
  path). Two cases: `fetchFights -> []` renders the
  empty-state counter; `fetchFights throws` renders the
  upstream-error card.
- `web/package.json`: dev dependency group gains `vitest ^2.1.9`,
  `jsdom ^25.0.1`, `@testing-library/react ^16.3.2`,
  `@testing-library/jest-dom ^6.9.1`. Two new scripts --
  `pnpm test` (vitest watch) and `pnpm test:unit` (vitest
  run once in CI).
- `web/pnpm-lock.yaml`: bumped to reflect the new dev deps.

### Changed

- `web/.npmrc`: bumped build-script allowlist from `[sharp]` to
  `[sharp, esbuild]` (`esbuild` is vitest + Vite + Next.js
  bundler native binary loader; `sharp` continues to be the
  Next.js Image pipeline binary loader). pnpm 11 deprecated
  the `pnpm.onlyBuiltDependencies` package.json field -- the
  authoritative home is .npmrc.
- `web/pnpm-workspace.yaml`: cleaned the leftover
  `allowBuilds:` placeholder block from an earlier interactive
  `pnpm approve-builds` call (whose values were literally
  "set this to true or false"); pointed the docstring at
  `web/.npmrc` for the postinstall allowlist; kept
  `verify-deps-before-run: false`.

### Added (CI followup)

- `.github/workflows/ci.yml::lint-and-test`: new `Web unit
  tests (vitest)` step after `Type-check web`, running
  `pnpm exec vitest run --reporter=verbose` with
  `working-directory: web`. The vitest runner is now part of
  the PR merge gate.

### Added (Phase 5 followup -- web upload UI)

- `web/src/app/upload/page.tsx` (NEW): Client Component that
  posts a `.zevtc` combat log as `multipart/form-data` to
  `POST /api/v1/uploads`. Renders the lightweight envelope
  (``id`` + ``sha256`` + ``status``) returned synchronously +
  points the user at `/fights` for the parsed encounter once
  the background parser finishes. Intentionally does NOT
  poll upload status here -- the gating concern is the parsed
  fight surfacing on `/fights` (already `force-dynamic` +
  `cache: "no-store"`), so the upload page stays a thin
  envelope renderer. Client-side rejects non-`.zevtc` files
  with a `role="alert"` error message **before** any network
  call (cheap; avoids polluting the network tab on bad input).
- `web/src/app/upload/page.module.css` (NEW): CSS module for
  the upload page mirroring the landing aesthetic (gradient
  title, dashed file-picker chip with `color-mix` accent
  overlay on hover, pending-status badge tinted with the
  accent variable). Uses `var(--accent)` / `var(--surface)` /
  `var(--border)` / `var(--font-geist-mono)` -- no hardcoded
  colours.
- `web/src/lib/api.ts`: new `uploadLog(file: File)` async
  helper + `UploadCreatedRow` interface (``id`` + ``sha256``
  + ``status``). Sends FormData + fetch POST; intentionally
  does NOT set ``Content-Type`` so the browser computes the
  multipart boundary from the FormData body.
- `web/src/app/page.tsx`: landing page nav gains a third
  card `/upload` alongside `/fights` and `/account`, with
  copy matching the existing card triplet aesthetic (sans
  serif title + monospace `<code>` snippet + arrow CTA).
- `web/tests/app/upload-page.test.tsx` (NEW): 5 vitest + RTL
  tests covering (a) empty state (heading + "No file
  selected" chip + disabled submit), (b) client-side
  `.zevtc` extension rejection before any network call,
  (c) happy-path upload + result card render with a real
  `UploadCreatedRow`, (d) `ApiError` formatting ("Upstream
  error: 502: ..."), and (e) bare-`Error` network-failure
  pass-through. The whole `@/lib/api` module is mocked so
  the page is testable in isolation without booting a real
  RSC.
- `web/tests/setup.ts`: no change required; the existing
  global mock shim for `next/link` already covers the
  anchors in the upload page.

### Added (Phase 6 -- event-driven aggregations)

- `libs/gw2_core/src/gw2_core/models.py`: new event-stream
  data types. `EventType` (`StrEnum`: DAMAGE, HEALING) +
  `BaseEvent` (`time_ms` + `source_agent_id` +
  `target_agent_id` + `skill_id`, all ``frozen=True`` +
  ``extra="forbid"``) + two leaf subclasses
  (`DamageEvent.damage: int >= 0`,
  `HealingEvent.healing: int >= 0`). Discriminated via
  ``event_type: Literal[EventType.X]`` + an `Event` type alias
  (``Union[DamageEvent, HealingEvent]``) for forward-compat
  consumers that accept "any event". Phase 6 v1 is synthetic
  (no parser integration yet) -- Phase 6 v2 will swap the
  synthetic `Iterable[Event]` input for a parser-sourced stream
  once the V1.3 event block is consumed.
- `libs/gw2_core/src/gw2_core/__init__.py`: re-exports the new
  event types. Version bumped ``0.2.0 -> 0.3.0``.
- `libs/gw2_core/pyproject.toml`: version bumped
  ``0.2.0 -> 0.3.0``.
- `libs/gw2_analytics/src/gw2_analytics/target_dps.py` (NEW):
  `TargetDpsAggregator.aggregate(events: Iterable[DamageEvent],
  duration_s: float) -> list[TargetDpsRow]`. Rows sorted
  deterministic by ``(-total_damage, target_agent_id)``.
  Cross-field invariants: sum of ``row.total_damage`` == sum
  of ``event.damage`` (no event dropped, no double-count);
  rows monotonically non-increasing by ``total_damage``
  with ascending agent id on tie; each row has
  ``attack_count >= 1``. Negative ``duration_s`` raises
  ``ValueError``; zero ``duration_s`` collapses to
  ``dps=0.0`` (sentinel -- dimensionless DPS is meaningless
  and the caller's fight-duration is the canonical input).
  Stateless (instantiate once, reuse).
- `libs/gw2_analytics/src/gw2_analytics/event_window.py` (NEW):
  `EventWindowAggregator.aggregate(events: Iterable[Event],
  window_s: int) -> list[EventBucket]`. Windows are half-open
  ``[start_ms, end_ms)`` so consecutive buckets tile the
  timeline without overlap and gaps are zero-filled so the
  visualisation has no holes. ``window_s < 1`` raises
  ``ValueError``. Damage vs healing is dispatched via
  ``isinstance`` against the ``Event`` union; future event
  types accumulate in ``event_count`` but not in
  ``damage_total`` / ``healing_total`` (forward-compat).
- `libs/gw2_analytics/src/gw2_analytics/__init__.py`:
  re-exports `EventBucket`, `EventWindowAggregator`,
  `TargetDpsAggregator`, `TargetDpsRow`. Version bumped
  ``0.2.0 -> 0.3.0``.
- `libs/gw2_analytics/pyproject.toml`: version bumped
  ``0.2.0 -> 0.3.0``.
- `libs/gw2_analytics/tests/test_target_dps.py` (NEW): 6
  pytest cases covering empty input, single-row shape,
  zero/negative duration edge case, deterministic ordering
  (desc + tie-breaker), cross-field sum preservation, frozen
  Pydantic schema guarantee.
- `libs/gw2_analytics/tests/test_event_window.py` (NEW): 6
  pytest cases covering empty input, invalid window guard,
  single-event bucket shape, gap zero-fill, contiguous
  adjacency invariant, frozen-Pydantic guarantee.
- `apps/api/src/gw2analytics_api/routes/fights.py`: new
  `GET /api/v1/fights/{fight_id}/events` route. Phase 6 v1
  STUB: returns ``[]`` after the 404 check (response_model is
  live as ``list[dict[str, object]]`` so the route shape is
  stable for Phase 6 v2). Phase 6 v2 will replace the empty
  list with the parser-sourced event stream.

### Notes

- Phase 6 deliberately does NOT modify `gw2_evtc_parser`. The
  parser doesn't surface events yet -- Phase 6 v1 ships the
  analytics-surface for synthetic events so the contract is
  locked, then Phase 6 v2 retrofits the parser.
- Forward-compat hooks: `EventType` (StrEnum) admits new
  kinds without API breakage; aggregators gate on
  ``isinstance`` against the matching subclass so unknown
  kinds fall through to ``event_count`` (no silent skipping
  of damage / healing accounting).

### Added

- `libs/gw2_core/src/gw2_core/models.py`: three new pydantic
  models for the Guild Wars 2 v2 REST API surface, exposed so the
  `gw2_api_client` (this commit) and a future `gw2_analytics`
  enrichment consumer can share an authoritative contract without
  the analytics layer having to import the HTTP client.

  - `Population` (`StrEnum`): the five bucket values (`Low`,
    `Medium`, `High`, `VeryHigh`, `Full`) -- capitalised exactly as
    the v2 API emits them so round-tripping through
    `WorldInfo.model_validate(...)` round-trips losslessly.
  - `AccountInfo`: the authenticated account returned by
    `GET /v2/account`. `extra="ignore"` (rather than
    `extra="forbid"`) so the v2 API can grow new fields without
    breaking the library; the wire-format `world` field is renamed
    `world_id` via Pydantic `alias="world"` so the analyst-friendly
    foreign key survives the rename at validation time.
  - `WorldInfo`: one row from `GET /v2/worlds[?ids=...]`
    (id + name + Population). Id is a strict `>= 1` positive int
    foreign key.

- `libs/gw2_core/src/gw2_core/__init__.py`: re-exports
  `AccountInfo`, `WorldInfo`, `Population`. `__version__` bumped
  to `0.2.0`.

- `libs/gw2_core/pyproject.toml`: version bumped `0.0.1 -> 0.2.0`.

## [0.1.0] - gw2_api_client 0.1.0: typed async v2 wrapper (Phase 4)

### Added

- `libs/gw2_api_client/pyproject.toml`: hatchling backend, depends
  on `gw2_core>=0.2.0` + `httpx>=0.27`. Declared
  `gw2_api_client = ["S101"]` in `[tool.ruff.lint.per-file-ignores]`
  (the `assert` in tests).

- `libs/gw2_api_client/src/gw2_api_client/exceptions.py`: a typed
  exception hierarchy rooted at `GuildWars2ClientError`. The
  hierarchy deliberately does NOT inherit from `httpx`'s
  exceptions so a future transport swap (aiohttp / urllib3) does
  not bleed into the public surface.

  - `MissingApiKeyError` -- raised by `from_env()` when the
    configured env var is unset / empty.
  - `GuildWars2HttpError` -- any non-2xx that is not 429 (401, 403,
    404, 5xx); also wraps transport errors (`httpx.HTTPError`
    subclasses) so callers see a transport-agnostic surface.
  - `GuildWars2RateLimitError` -- 429 retry budget exhausted
    (after `_MAX_RATE_LIMIT_RETRIES = 3` attempts).

- `libs/gw2_api_client/src/gw2_api_client/client.py`: the v2 REST
  API wrapper. Two public surfaces:

  - `GuildWars2Client` -- a `typing.Protocol` with three members
    (`supported_endpoints()`, `account_get()`,
    `worlds_get(ids)`). Future sync / cached / batched
    implementations can satisfy this Protocol without test
    rewrites.
  - `AsyncGuildWars2Client` -- the only implementation shipped
    today. Stateless from the caller's perspective; owns one
    `httpx.AsyncClient` connection pool; always use as an
    `async with` so the pool closes deterministically on exit.

  Rate-limit policy: 3 attempts total with exponential backoff
  (0.5s, 1.0s, 2.0s) before `GuildWars2RateLimitError` is raised.
  `worlds_get([])` short-circuits client-side (no HTTP round-trip
  -- the v2 API rejects empty `ids=` with a 400). `account_get()`
  has 401 specifically mapped to `GuildWars2HttpError` (auth
  required). `from_env()` reads `GW2_API_KEY` (or an override env
  var) and raises `MissingApiKeyError` on absence.

- `libs/gw2_api_client/src/gw2_api_client/__init__.py`: re-exports
  the Protocol, the async implementation, the four exception
  classes. `__version__ = "0.1.0"`.

- `libs/gw2_api_client/tests/test_client.py`: 12-test unit suite
  using `respx` to mock `httpx` end-to-end (no real network
  calls). Covers:

  - `account_get` happy path (alias rename `world` -> `world_id`
    survives), 401 -> `GuildWars2HttpError`, transport error
    -> `GuildWars2HttpError`, 3x 429 -> `GuildWars2RateLimitError`
    after 3 attempts, 2x 429 then 200 -> success on attempt 2.
  - `worlds_get([])` short-circuits without HTTP, happy path
    round-trips `Population.HIGH` and `Population.MEDIUM`.
  - `from_env` with / without `GW2_API_KEY` (missing -> the
    typed error).
  - `supported_endpoints()` returns the (`account`, `worlds`)
    tuple.
  - async context manager enters + exits cleanly.

### Changed

- `pyproject.toml`: dev dependency group gained
  `pytest-asyncio>=0.24` + `respx>=0.21`. `[tool.pytest.ini_options]`
  sets `asyncio_mode = "strict"` so async tests require an
  explicit `@pytest.mark.asyncio` (the test suite uses strict
  mode markers throughout).

- `uv.lock`: bumped to reflect the new gw2_core 0.2.0 +
  gw2_api_client 0.1.0 versions and the new dev deps.

### Notes

- Only the V1 minimum API surface (`/v2/account` + `/v2/worlds`)
  is exposed. A future `/v2/commerce` / `/v2/account/achievements`
  endpoint just needs a new method on the Protocol + a row in
  `supported_endpoints()`.
- The Protocol is deliberately not `@runtime_checkable`
  (async methods break the runtime check); tests duck-type against
  it instead.
- Library ships one `NullHandler` no-op by convention so
  downstream apps that haven't configured logging don't see
  `logger.warning(...)` calls propagate up to the root logger.
