# Plan 170 — Failed-upload-row TTL cleanup sweep (closes plans/160 audit gap)

**Source:** SHOULD-CONSIDER raised against the option-(a) idempotent decision filed in :file:`plans/160-fight-id-collision-handling.md` (commit `301b880`). The option-(a) variant creates a `"failed"` UploadRow when a re-zipped log triggers a `fight_id` collision; these rows persist indefinitely per the decision's `Orphaned-UploadRow policy`.

**Severity:** MED (operational hygiene + DB growth).
**Effort:** S (~50 LoC Python + 1 optional Alembic migration + 1 pytest).
**Drift base:** Post commit `301b8809`.
**Cycle anchor:** Wave 1 — v0.10.26-pre per `plans/167-v01026-pre-cycle-anchor.md`.

## Problem

The plan 160 decision (option (a) idempotent, No-Alembic) accepts that `"failed"` UploadRows accumulate indefinitely. After N analyst re-upload retries in a busy cycle, the `uploads` table can grow by `N × bytes_per_failed_row` without a cleanup mechanic. Three failure modes emerge:

1. **Storage growth** — failed UploadRows with `error_message LIKE 'duplicate fight%'` grow unbounded.
2. **Operator confusion** — a fresh operator paged on a `WHERE status='failed'` query sees 90-day-old rows interleaved with today's retries.
3. **Audit trail value erosion** — the longer the failed-rows sit, the harder it is to answer "what was the user trying to do at time T".

## Solution: extend the existing `stuck_upload_sweeper.py`

The project already has a sweeper at :file:`apps/api/src/gw2analytics_api/workers/stuck_upload_sweeper.py` that polls stale PENDING rows (plan 014) on a configurable interval (`STUCK_SWEEPER_INTERVAL_S` + `STUCK_SWEEPER_THRESHOLD_S`). Adding a parallel failed-row sweep re-uses the same polling infrastructure + the same `metrics` instrumentation pattern (`STUCK_SWEEPER_ITERATION_DURATION`).

**Implementation outline** (:file:`apps/api/src/gw2analytics_api/workers/stuck_upload_sweeper.py`):

1. Add a second `select + delete` batch in the existing sweep loop, with configuration:
   - `STUCK_SWEEPER_FAILED_RETENTION_DAYS` (default: 90 days; matches the audit gap's "post-test-fail retention tracés" line).
   - The select query joins on `error_message LIKE 'duplicate fight%'` (the canonical signature of a category-(a) collision row) to ensure NON-collision failures (network errors, parser bugs) are NOT swept.

2. The sweep uses a server-side timestamp delta (no client clock skew):
   ```sql
   DELETE FROM uploads
   WHERE status = 'failed'
     AND created_at < NOW() - INTERVAL '90 days'
     AND error_message LIKE 'duplicate fight%';
   ```

3. Add a Prometheus counter `FAILED_UPLOAD_SWEEP_ITERATION_DELETED_COUNT` + a histogram of deleted-row ages so the operator can spot a misconfigured TTL (e.g., 90d → 1d accidental) at-a-glance.

4. Document the SQL in the sweeper's docstring so the next maintainer can verify the LIKE clause without re-reading plans/160.

## Why the LIKE clause (not blanket DELETE on `status='failed'`)

The audit's category-(a) collision rows are characterized by `error_message` starting with `"Duplicate fight: existing fight_id = ..."` (the string the plan 160 implementation writes). The sweeper deletes ONLY those rows because:

- Network-error failed rows (gateway 502, zlib decompression failure, schema drift) are operator-actionable — sweeping them silently loses the diagnostic signal for a still-open bug.
- Parser-version rejected failed rows are likewise operator-actionable.
- Only the collision rows have a clear, finite retention horizon (they will never match anything; the canonical fight already exists; the analyst can re-derive from the canonical `fight_id` if needed).

## Optional Alembic migration (deferred)

If a future audit prefers `soft_deleted_at` over `DELETE` + `LIKE`, add a small Alembic migration:

```python
# apps/api/alembic/versions/0015_failed_upload_soft_delete.py
def upgrade() -> None:
    op.add_column(
        "uploads",
        sa.Column("soft_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_uploads_failed_dedup_soft_delete",
        "uploads",
        ["status", "error_message", "created_at"],
        postgresql_where=sa.text("status = 'failed' AND soft_deleted_at IS NULL"),
    )
```

This is deferred to a future PR — the `DELETE + LIKE` path is sufficient for the v0.10.26-pre cycle and avoids the migration surface.

## Acceptance criterion

`pnpm vitest run` (web) returns 0 failing tests AFTER `pytest apps/api/tests/test_stuck_upload_sweeper.py -x` runs the new sweep-query tests successfully (≥3 cases: empty table → 0 deletes; 1 stale collision → 1 delete; 1 fresh collision (1-day-old) → 0 deletes).

## Risk: in-flight poll during sweep

The plan 160 contract has the client polling `GET /uploads/{id}` to discover a `"failed"` collision. If the sweep deletes the row mid-poll, the client gets a 404 instead of the "duplicate fight" error message. **Mitigation**: the sweeper selects the deletion candidates first, then deletes in a transaction block bounded to the matched IDs (no race window for newly-mutating rows). The poll window is `1-5s` per cycle; sweep interval (`STUCK_SWEEPER_INTERVAL_S`) is `300s` default — a sweep at the top of the minute rarely overlaps a client poll.

## Cycle anchor + dependency

- Wave 1 — v0.10.26-pre (per plans/167). Lands BEFORE the plan 160 implementation (commit pending) so the sweep is in place when the first collision-row is created.
- No blocker: this plan is INDEPENDENT of plans/164, 161, 162, 163.
- Operator handoff chose **DELETE + LIKE** (no Alembic required for the v0.10.26-pre cycle); the soft-delete variant is documented above for future cycle use.

## Estimated LoC

- Sweeper extension: ~40 LoC Python (select + delete + metrics counter).
- Pytest: ~60 LoC (3-4 cases covering empty/stale/fresh/non-collision).
- Total: ~100 LoC + 0 LoC Alembic.

## Implementation refinement during cycle (commit bce9675)

The v0.10.26 cycle refined this design during implementation because the ground-truth FK relationships discovered during the pre-implementation audit constrained the option matrix.

### FK cascade 4-deep discovery

The pre-implementation reader of this plan assumed the simple ORM cascade via `Upload.fight` (`back_populates="upload"`, `cascade="all, delete-orphan"`). The actual ORM + DB relationship is deeper:

- `OrmFight.upload_id`: `ForeignKey("uploads.id", ondelete="CASCADE")` — DB-level CASCADE deletes dependent `OrmFight` rows when the parent `Upload` row is deleted.
- `OrmFight` → `OrmFightAgent` / `OrmFightSkill` / `OrmFightPlayerSummary` — 3 downstream FKs each with `ondelete="CASCADE"`.

A naive `DELETE` of an `Upload` row would orphan 4 levels of analytical summary data (fights + per-fight agents + per-fight skills + per-player summaries).

### Option matrix reinterpretation

The 4 candidate options from this plan's "Optional Alembic migration" section were evaluated against the FK reality:

| Option | Status | Reason |
| --- | --- | --- |
| (a) hard DELETE | not viable | Cascades 4 levels of analytical summary data |
| (b) soft delete via `status` field flip | not viable | Blocked by `CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_uploads_status")` — flipping status to `"archived"` violates the CHECK |
| (c) hard DELETE with `NOT EXISTS` subquery guard | chosen | Safe + no schema change + atomic at the SQL level |
| (d) archival table | not viable | Requires Alembic migration (banned for v0.10.26-pre cycle per plans/160) |

Option (c) was implemented via a TOCTOU-safe single-statement DELETE WHERE id IN (SELECT ... AND NOT EXISTS (...) LIMIT 1000) — see `apps/api/src/gw2analytics_api/workers/stuck_upload_sweeper.py::_sweep_failed_once` for the canonical implementation reference.

### LIKE signature correction: `'Duplicate fight:%'` (not `'duplicate fight%'`)

The plan's "Implementation outline" SQL example used `'duplicate fight%'` (lowercase, no colon). The actual implementation uses `error_message.like("Duplicate fight:%")` (capital D + colon + percent) because the plan/160 idempotency layer writes the canonical collision string as:

```
error_message = "Duplicate fight: <canonical_fight_id>"
```

Any future correction in plan/160's error-message string format must be mirrored here.

### Test coverage expanded from 3 to 5 cases

The plan's "Acceptance criterion" specifies 3 pytest cases (empty table / 1 stale / 1 fresh). The actual implementation shipped 5 cases to lock down all 5 logical branches of the helper:

1. no-eligible rows (huge retention window) → 0 deletes
2. stale collision without dependents → 1 delete (happy path)
3. stale collision WITH dependent `OrmFight` → NOT deleted (safety guard verification)
4. stale non-collision failure → NOT deleted (LIKE clause verification)
5. fresh collision (inside retention window) → NOT deleted (cutoff gate verification)

UUID-keyed assertions sidestep count brittleness against pre-existing test DB rows.

### New config + metrics instrumentation

- `Settings.stuck_sweeper_failed_retention_days` — default 90 days, env `STUCK_SWEEPER_FAILED_RETENTION_DAYS`, Pydantic `ge=1` floor (an operator typo of 0 cannot silently become "delete immediately").
- `STUCK_SWEEPER_FAILED_SWEPT` Prometheus counter — `stuck_sweeper_failed_swept_total` cumulative count of hard-deleted rows.

### Forward-blockers (rider-next-cycle)

The implementation shipped 3 reviewer-flagged NICE-to-HAVE followups that ride next cycle:

- **`_BATCH_DELETE_SIZE = 1000` magic constant** (reviewer's NICE-to-HAVE on the F5 sweeper commit). Thread through `Settings.stuck_sweeper_failed_batch_size` (env `STUCK_SWEEPER_FAILED_BATCH_SIZE`, default 1000, `ge=10`, `le=100_000`).
- **`STUCK_SWEEPER_ITERATION_DURATION` conflation** (reviewer's NICE-to-HAVE). Split into `_pending_` + `_failed_` per-sweep histograms so operators can attribute SLA breaches per sweep.
- **CHANGELOG `### Fixed` subsection** (v0.10.26 release reviewer's NICE-to-HAVE). The 2 `fix(web)` commits (SectionErrorChip import placement + comment trim + explicit React import to SectionErrorChip) shipped inside their feature `### Added` blocks; a future retro-split could move them into a dedicated `### Fixed` block under v0.10.26.

## Resolved during cycle (F-series — commits 12d3fdf + 0e6d20a + F7 polish)

The v0.10.26 cycle's reviewer-flagged NICE-to-HAVE on the F5 sweeper commit (`bce9675`) was the `_BATCH_DELETE_SIZE = 1000` magic constant. The F-series polish commits closed it across 3 atomic moves:

### Closed: thread `_BATCH_DELETE_SIZE` through `Settings` (F7)

**Commit `12d3fdf`** (`feat api: plan 170 follower -- operator-tunable failed-upload sweep batch size`):

- Added `Settings.stuck_sweeper_failed_batch_size: int = Field(default=1000, validation_alias="STUCK_SWEEPER_FAILED_BATCH_SIZE", ge=100, le=100_000)`.
- Added module-level `_BATCH_DELETE_SIZE: int = 1000` constant in `stuck_upload_sweeper.py` (after the logger; reference default for the helper's Python signature).
- Updated `_sweep_failed_once(session_factory, retention_days, batch_size: int = _BATCH_DELETE_SIZE)` signature. The default-arg injection keeps the existing 5 pytest cases backward-compatible (they don't pass `batch_size`).
- Wired lifespan ticker to pass `settings.stuck_sweeper_failed_batch_size` on every sweep tick.
- Added `test_failed_sweep_respects_explicit_batch_size_override` pytest case seeding 3 eligible rows + sweeping with `batch_size=2` + asserting exactly 2 deleted + 1 survivor (set-membership) + sweeping again with default to verify across-tick completeness.
- Cross-reference comments in both spots (Settings field + module constant) flag the intentional `1000` duplication so a future default change touches both.

### Closed: defensive polish on F7 (F7 polish)

**Latest F-series commit** (`chore api: F7 polish -- raise floor to ge=100 + add test teardown guard`):

- Raised `stuck_sweeper_failed_batch_size` floor from `ge=10` to `ge=100` (closes the F7 reviewer's NICE-to-HAVE flagging the original `ge=10` as too low -- batches below ~100 rows barely amortize FK lock costs and approach per-row DELETE territory). Updated docstring with the new rationale (1-2 orders-of-magnitude cost reduction at the floor).
- Wrapped `test_failed_sweep_respects_explicit_batch_size_override` body in try/finally. The finally block hard-deletes any seeded row still present (idempotent: no-op on the happy path when all 3 are already deleted by the 2nd sweep tick; cleans up leaked rows on any assertion failure). Added `delete` to the existing `from sqlalchemy import select` import line.

### Closed: F8 audit re-run leftover + cosmetic verification

**Commit `0e6d20a`** (`chore web: F6 audit re-run leftover -- explicit React import in 7 missed files`):

- 7 files (`web/src/app/_styles.ts` + 4 error pages + 2 page.tsx) gained `import React from "react";` as the first import. Files landed after the original F6 audit commit `2cd4048` (4 Next.js error pages from the v0.10.25 error-page rollout + 2 page.tsx + 1 styles helper).
- Defensive regex collapse (same F6 pattern from `2cd4048`) applied to the 7 files: zero files modified (all 7 already had exactly 1 blank line after the React import). F8 audit re-run confirms zero remaining misses.

### Forward-blockers remaining (2 items, ride next cycle)

- **`STUCK_SWEEPER_ITERATION_DURATION` conflation** -- still OPEN. Split into `_pending_` + `_failed_` per-sweep histograms so operators can attribute SLA breaches per sweep (the current conflated histogram measures BOTH sweeps + sleep).
- **CHANGELOG `### Fixed` subsection** -- still OPEN. The 2 `fix(web)` commits (SectionErrorChip import placement + comment trim + explicit React import to SectionErrorChip) shipped inside their feature `### Added` blocks; a future retro-split could move them into a dedicated `### Fixed` block under v0.10.26.
