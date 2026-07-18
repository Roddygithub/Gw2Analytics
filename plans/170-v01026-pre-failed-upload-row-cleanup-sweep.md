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
