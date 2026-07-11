# Advisor Plans (senior-advisor audit followups)

Senior-advisor audit (post-R1-R4 batch, 2026-07-10). Each plan is self-contained for an executor with zero context from this session. Status is updated by the executor.

## Plans (ordered by priority / leverage)

| # | Slug | Priority | Impact | Effort | Confidence | Status |
|---|---|---|---|---|---|---|
| 001 | `[api-tests-player-compare](#plan-001--add-api-test-coverage-for-routesplayer_comparepy)` | **P1** | High (used API surface) | M | 1.0 | open |
| 002 | `[fix-typing-any-leakage-analytics](#plan-002--fix-typing-any-leak-in-cross_account_timelinepy)` | **P2** | Medium (strips mypy --strict bypass) | XS | 1.0 | open |
| 003 | `[bootstrap-core-domain-tests](#plan-003--bootstrap-unit-tests-for-libsgw2_coretes)` | **P3** | High (dependency-stability base) | M | 0.9 | open |
| 004 | `[cleanup-stale-audit-plans](#plan-004--archive-stale-plans-in-plansdir)` | **P4** | Low (DX: reduce navigation noise) | XS | 1.0 | open |
| 026 | `[webhook-dns-executor-do-max-workers](#plan-026--v01010-webhook-dns-executor-dos-fix-max_workers1--bounded-concurrency)` | **P1** | HIGH (security DoS) | XS | 1.0 | open |
| 027 | `[event-iterator-streaming-gzip](#plan-027--v01010-stream-_event_dispatchbuild_event_iterator-via-gzipgzipfile-eliminates-the-gzipdecompress--splitlines-memory-peak)` | **P1** | HIGH (perf/OOM) | XS | 1.0 | open |
| 028 | `[players-sql-aggregations](#plan-028--v01010-sql-aggregations-on-ormfightplayersummary-for-apiv1players--apiv1playersaccount_name--apiv1playersaccount_nametimeline-eliminates-full-db-ram-load)` | **P2** | HIGH (perf/scaling) | L | 1.0 | open |
| 029 | `[blob-cache-thundering-herd-latch](#plan-029--v01010-_cached_get_events-thundering-herd-latch-serialize-concurrent-minio-gets-for-the-same-blob_uri)` | **P2** | MED-HIGH (perf) | S | 1.0 | open |
| 030 | `[schema-guard-alembic-script-location](#plan-030--v01010-schema_guardcheck_schema_drift-must-set-absolute-script_location-on-alembicconfig-closes-the-cwd-dependent-alembic-resolution-bug)` | **P3** | MED (dx) | XS | 1.0 | open |
| 031 | `[schema-guard-fresh-db-handling](#plan-031--v01010-schema_guardcheck_schema_drift-must-catch-undefinedtable-on-a-fresh-db-graceful-startup-before-migrations)` | **P4** | LOW-MED (dx) | XS | 1.0 | open |

> **Note:** the numeric gap 005-025 reflects plans shipped and archived over the v0.9.4 + v0.9.5 + v0.9.6 + v0.10.9 cycles. Their index links live in `plans/README.md` (the 24 plans covered by [`plans/AUDIT-2026-07-10-79c4501.md`](plans/AUDIT-2026-07-10-79c4501.md) + [`plans/AUDIT-2026-07-11-f0249ef.md`](plans/AUDIT-2026-07-11-f0249ef.md)).

## Dependency graph

- **P1 (001, 026, 027)** MUST be first-class. The route surface (001) + the security DoS (026) + the OOM read-path (027) are blocking-class.
- **P2 (002, 028, 029)** independent and can run in parallel with P1 if executors are isolated.
- **P3 (003, 030)** are dependency-stability + a single DX defect. Land before P3 here (analytics typing cleanup).
- **P4 (004, 031)** are cheap DX. Run last.

Within the **v0.10.10 cycle (026-031)** the order is:

1. **026** (webhook DNS executor DoS) — XS effort, the highest-leverage single fix.
2. **027** (event iterator streaming gzip) — XS effort, the second highest-leverage.
3. **029** (blob cache thundering-herd latch) — S effort, pairs naturally with 027 for the canonical /fights/{id} page-load perf story.
4. **028** (players SQL aggregations) — L effort, the biggest refactor. Independent.
5. **030 + 031** (schema_guard adjustments) — XS effort each. Land together for review convenience.

There are NO inter-plan dependencies across 026-031. All 6 are independent and could ship in any order. The recommended order is by leverage (security > perf > perf > perf > dx/dx).

## Discarded scope (intent: avoid re-auditing in the next cycle)

These came up in Phase 2 but were vetted out:

- **A03/B03/B04/B05/D04** — by-design patterns (frozen=True, Fernet envelope, BaseSettings fail-fast, MinIO race-handled, minimal env validation). NOT findings.
- **A02** (`isinstance` chain in `event_window.py`) — Pythonic discriminated-union dispatch; introducing a Visitor pattern is over-engineering for 3 event types.
- **A04** (`_MIN_WINDOW_S=1` duplicated across 3 modules) — 1-line tech debt; not worth a dedicated PR.
- **B01** (SSRF via `getaddrinfo`) — already mitigated since v0.9.1 plan 005 (universal private-IP gate via `is_private`/`is_loopback`/`getaddrinfo`).
- **B02** (Content-Length middleware deferred from R3.4) — already known; will re-surface if fix-004 explicitly handles it.
- **C02** (floating `>=` deps) — `uv.lock` pins versions; out of scope.
- **D01** (no structlog/OTel) — stdlib `logging` fits current scale.
- **D02/D05** (codegen / changelog insert scripts) — workflow operational, ROI negligible.

## Re-investigation pending

- **C03** (potential Alembic ↔ ORM structural drift beyond the v0.10.1 `check_schema_drift()` version-pointer guard) — needs an `alembic revision --autogenerate --sql` dry-run on a fresh DB to confirm whether the guard catches `String(128)` vs `String(64)`-style drift. If drift is real, this becomes plan 005.

## v0.10.10 cycle (2026-07-11, working diff at `f0249ef`)

**Scope:** Per-feature audit on the current working-tree diff (the uncommitted changes that include the `_event_dispatch` consolidation, the new `_cached_get_events` LRU cache, the new webhook DNS-executor pattern, the new `route_helpers.format_profession`/`format_elite_spec`, the new `list_webhook_dlq` route, and the schema_guard log wording tweak). The 6 plans are self-contained implementation specs that a different, less-context-aware executor can ship without further clarification.

### Status (v0.10.10, working diff at `f0249ef`)

| Plan | Finding | Category | Impact | Effort | Confidence | Status |
|------|---------|----------|--------|--------|------------|--------|
| 026  | `_DNS_EXECUTOR.max_workers=1` thread-starvation DoS on `/api/v1/webhooks` POST | security, perf | HIGH | XS | 1.0 | open |
| 027  | `build_event_iterator` materialises full gzip via `decompress + splitlines` (defeats the docstring's "no upfront cost" claim) | perf, correctness | HIGH | XS | 1.0 | open |
| 028  | `routes/players.py` 3 endpoints load the FULL `OrmFight` table + agents + skills per request (scales linearly with dataset) | tech_debt, perf | HIGH | L | 1.0 | open |
| 029  | `_cached_get_events` thundering herd: 4 parallel `/fights/{id}/*` fetches trigger 4 independent MinIO GETs (concurrent stampede defeats the cache) | perf | MED-HIGH | S | 1.0 | open |
| 030  | `schema_guard.py` Alembic `script_location` resolution relies on operator CWD (crashes on `uvicorn` from repo root, the README quickstart pattern) | dx, correctness | MED | XS | 1.0 | open |
| 031  | `schema_guard.py` crashes with opaque `psycopg.errors.UndefinedTable` on a fresh DB before migrations (masked behind a Postgres-outage-like traceback) | dx | LOW-MED | XS | 1.0 | open |

### Recommended execution order (v0.10.10)

1. **026** (webhook DNS executor) — XS effort, the highest-leverage single fix. Closes a CVSS-class DoS hot path.
2. **027** (event iterator streaming gzip) — XS effort, the second highest-leverage. ~64 KB memory peak vs ~300 MB current.
3. **029** (blob cache thundering-herd latch) — S effort, completes the canonical /fights/{id} page-load perf story with 027.
4. **028** (players SQL aggregations) — L effort, the biggest refactor. The cache-vs-compute pivot: the SQL layer becomes the source of truth for `/players/*` endpoints. Pairs naturally with re-running the existing 10k-fixtures benchmark to validate the win.
5. **030 + 031** (schema_guard adjustments) — XS effort each. Land in the same PR for review convenience.

All 6 plans are independent. Could ship in any order. The recommended order is by leverage (security > perf > perf > perf > dx > dx).

### Considered and rejected (v0.10.10)

- **Bundle 026 + 029 into one plan**: tempting (both are about webhook / blob cache concurrency). The two plans are independently testable (026 has its own `_DNS_EXECUTOR` mock pattern; 029 has its own `ThreadPoolExecutor` mock pattern). Bundling would conflate security-defense invariants with perf invariants, making them harder to revert if the security fix regresses.
- **027 alternative: keep `gzip.decompress` + a streaming splitlines() helper** — `str.splitlines()` cannot stream (it MUST materialise the whole str). The `gzip.GzipFile` wrapper is the canonical streaming alternative.
- **028 alternative: keep the Python loop but add a `LIMIT 200` recent-fights filter** — the user-selected scope is SQL aggregations complètes. The LIMIT plan is a M-effort follow-up acceptable for a future cycle if the dataset scale turns out to be smaller than 100k fights.
- **029 alternative: replace `functools.lru_cache` with `cachetools.LRUCache`** — adds a dependency. The 5-line `lru_cache` is sufficient; the missing latch is the actual bug.
- **030 alternative: edit `apps/api/alembic.ini` to use an absolute `script_location`** — would lock the operator to in-`apps/api/` launches. The Python `set_main_option(...)` override keeps the `.ini` portable + the schema-guard portable.
- **031 alternative: auto-run missing migrations from the schema_guard** — the helper is fail-fast by design; auto-running migrations blurs the boundaries (the operator's deploy-runbook is the canonical migration driver).
- **`_cached_get_events` doesn't cache exceptions** — by-design and correct Python `functools.lru_cache` semantics. NOT a finding. (Note: re-audit in a future cycle to confirm this remains correct after PyO3 or async-migration changes.)
- **`list_webhook_dlq` lacks tenant filtering** — single-tenant contract per ROADMAP §3. NOT a finding.

### Test inventory (cumulative v0.10.10)

| Plan | NEW hermetic | NEW integration |
|------|--------------|-----------------|
| 026  | 8 | 0 |
| 027  | 6 | 0 |
| 028  | 8 | 1 |
| 029  | 6 | 0 |
| 030  | 5 | 0 |
| 031  | 5 | 0 |
| **Total** | **38** | **1** |

### Style conventions

- All 6 plans mirror the `## Finding → ## Fix → ## Tests → ## Out of scope → ## Done criteria → ## Maintenance note → ## Escape hatches → ## Dependency graph → ## Cross-references` structure established in the v0.9.x plans.
- All 6 plans name the **real** audit finding (the line + the duplicated concept + the SOURCE comment if it documents the violated contract).
- All 6 plans surface a **cross-cutting hook** to adjacent plans (security-DoS / perf-OOM / SQL-aggregation / cache-latch / CWD-resilience / DB-freshness).
