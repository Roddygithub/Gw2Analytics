# Advisor Plans (senior-advisor audit followups)

Senior-advisor audit (post-R1-R4 batch, 2026-07-10). Each plan is self-contained for an executor with zero context from this session. Status is updated by the executor.

## Plans (ordered by priority / leverage)

| # | Slug | Priority | Impact | Effort | Confidence | Status |
|---|---|---|---|---|---|---|
| 001 | `[api-tests-player-compare](#plan-001--add-api-test-coverage-for-routesplayer_comparepy)` | **P1** | High (used API surface) | M | 1.0 | open |
| 002 | `[fix-typing-any-leakage-analytics](#plan-002--fix-typing-any-leak-in-cross_account_timelinepy)` | **P2** | Medium (strips mypy --strict bypass) | XS | 1.0 | open |
| 003 | `[bootstrap-core-domain-tests](#plan-003--bootstrap-unit-tests-for-libsgw2_coretes)` | **P3** | High (dependency-stability base) | M | 0.9 | open |
| 004 | `[cleanup-stale-audit-plans](#plan-004--archive-stale-plans-in-plansdir)` | **P4** | Low (DX: reduce navigation noise) | XS | 1.0 | open |

## Dependency graph

- **P1** MUST be first. The route is the contract surface; testing it pins behavior before any analytics refactor (P2) or core tests (P3) touch downstream contracts.
- **P2** is independent of P1 but should run before P3 — P3 introduces new strict-type assertions in the core shape layer, so a clean P2 commit avoids chasing the same signature twice.
- **P3** is independent and can run in parallel with P1/P2 if executors are isolated. Ordering with P4 is free.
- **P4** is purely docs (workspace ops). Run last.

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
