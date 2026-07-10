# advisor-plan 014 — Stuck-upload sweeper for arq pending (operational resilience)

## Problem

If the arq worker process dies mid-parse, the corresponding `uploads.status = 'pending'` row can stay pending indefinitely. `apps/api/src/gw2analytics_api/services.py` has 4 `UPLOAD_STATUS_FAILED` assignments (lines 88, 98, 104, 111) but these only fire for IN-REQUEST failures with the FastAPI process as owner. Worker crash recovery is silent — no stuck-upload sweeper. `apps/api/src/gw2analytics_api/workers/parser_worker.py:7` even notes this as a known regression source ("uploads all stuck on `pending` after 20s").

## Context

- Verified `grep -n 'status.*FAILED' apps/api/src/gw2analytics_api/services.py` → 4 matches (lines 88/98/104/111).
- `apps/api/src/gw2analytics_api/workers/parser_worker.py:46-48` explains: "process_parse raises: the Arq job re-raises; Arq's on-job-error handler re-queues up to max_tries=3". After 3 retries, the job is dropped; the Postgres row is left in `pending`.
- `apps/api/src/gw2analytics_api/main.py:125` already runs `asyncio.create_task(lifespan_scheduler(_open_session))` for the webhook scheduler. The lifespan-task pattern is established.

## Approach

Add a new lifespan task `lifespan_stuck_upload_sweeper(_open_session)` that:
1. On a configurable interval (default 300s), queries `uploads WHERE status='pending' AND created_at < now() - <threshold_s>`.
2. Marks them as `failed` with error string `"stuck-pending-sweeper: no completion signal within <N>s (worker died or Redis lost the job)"`.
3. Logs a WARNING per sweep so the operator can grep their logs.

Configure via `STUCK_SWEEPER_INTERVAL_S=300` and `STUCK_SWEEPER_THRESHOLD_S=300` env (env-driven via Settings, see plan 016).

## Files

**In scope**:
- NEW `apps/api/src/gw2analytics_api/workers/stuck_upload_sweeper.py`
- MODIFIED `apps/api/src/gw2analytics_api/main.py` (add lifespan task + cleanup)
- MODIFIED `apps/api/src/gw2analytics_api/config.py` (add 2 Settings fields)
- MODIFIED `apps/api/.env.example` (document env vars)
- NEW `apps/api/tests/test_stuck_upload_sweeper.py`

**Out of scope**:
- Existing webhook scheduler lifespan task (parallel pattern; do not merge).
- The arq worker process (`parser_worker.py`).

## Steps

1. Create `apps/api/src/gw2analytics_api/workers/stuck_upload_sweeper.py` (~80 lines):
   ```python
   async def lifespan_stuck_upload_sweeper(_open_session) -> None:
       settings = get_settings()
       while True:
           try:
               async with _open_session() as session:
                   cutoff = datetime.utcnow() - timedelta(seconds=settings.stuck_sweeper_threshold_s)
                   stmt = (
                       update(OrmUpload)
                       .where(OrmUpload.status == "pending", OrmUpload.created_at < cutoff)
                       .values(
                           status="failed",
                           error=(
                               "stuck-pending-sweeper: no completion signal within "
                               f"{settings.stuck_sweeper_threshold_s}s (worker died or Redis lost the job)"
                           ),
                       )
                   )
                   result = await session.execute(stmt)
                   await session.commit()
                   if result.rowcount:
                       logger.warning(
                           "stuck-upload sweeper marked %d row(s) as failed", result.rowcount,
                       )
           except Exception:
               logger.exception("stuck-upload sweeper iteration failed")
           await asyncio.sleep(settings.stuck_sweeper_interval_s)
   ```
2. Update `apps/api/src/gw2analytics_api/main.py`:
   - In the FastAPI `lifespan` async context, after `scheduler_task = asyncio.create_task(...)`, add:
     ```python
     sweeper_task = asyncio.create_task(lifespan_stuck_upload_sweeper(_open_session))
     ```
   - In cleanup: `sweeper_task.cancel(); await asyncio.gather(sweeper_task, return_exceptions=True)`.
3. Update `apps/api/src/gw2analytics_api/config.py` (per plan 016's pattern):
   ```python
   stuck_sweeper_interval_s: int = Field(default=300, validation_alias="STUCK_SWEEPER_INTERVAL_S")
   stuck_sweeper_threshold_s: int = Field(default=300, validation_alias="STUCK_SWEEPER_THRESHOLD_S")
   ```
4. Update `apps/api/.env.example`:
   ```
   # Stuck-upload sweeper (worker crash recovery): marks uploads stale in
   # `pending` for > STUCK_SWEEPER_THRESHOLD_S as `failed` every
   # STUCK_SWEEPER_INTERVAL_S. Tune for large .zevtc files (5min default
   # is conservative; bump to 1800s if your largest parses take 10+ min).
   # STUCK_SWEEPER_INTERVAL_S=300
   # STUCK_SWEEPER_THRESHOLD_S=300
   ```
5. Add `apps/api/tests/test_stuck_upload_sweeper.py`:
   - Time-mock + real Postgres fixture.
   - Insert 1 upload pending for >threshold.
   - Run one iteration manually.
   - Assert it gets marked `failed` with the right error string.
   - Insert 1 upload pending for <threshold; assert it's NOT modified.

## Verification

- `find apps/api/src -name 'stuck_upload_sweeper.py'` → 1 file.
- `uv run pytest apps/api/tests/test_stuck_upload_sweeper.py -v` → all green.
- `uv run pytest` (full suite) → all green (no regression).
- Manual smoke (operator): start the API + arq worker; kill arq mid-parse; wait 6 min; `SELECT id, error FROM uploads WHERE status='failed' AND error LIKE 'stuck-pending-sweeper%'` → non-empty.

## Test plan

- 1 new pytest with time-mock + real Postgres fixture.
- Existing pytest suite should pass without regression.

## Done criteria

- `stuck_upload_sweeper.py` exists.
- `main.py` lifespan integrates + cleans up the task without leaking.
- `config.py` exposes both env vars with sensible defaults.
- New + existing tests pass.
- Lint + mypy + ruff all green.

## Maintenance note

- The default 5-minute threshold is conservative; tune via env for environments where parses legitimately run > 5 min (large .zevtc files have ranged up to 30 min in v0.10.x testing). Document the trade-off in `apps/api/.env.example`.
- The sweeper ITERATES only on `pending` — not on `processing` (those are actively in the worker). If a worker has been alive for > threshold on one job, ALSO mark those as `failed`? Consider in a future plan (operator decision needed on staleness semantics).
- Don't tie this task to the webhook scheduler's lifespan — independent concerns; either can fail without affecting the other.

## Escape hatch

- If the operator's monitoring already alerts on `pending > N min` (e.g. via Prometheus / Datadog / Uptime checks), the sweeper is redundant. Skip if monitoring exists.
- If a future arq version adds a built-in stuck-job hook (`on_stuck_job`), prefer that over the in-house sweeper.
- If a future Postgres version adds advisory locks + a per-row heartbeat column, switch to a heartbeat-based scheme (worker writes `last_heartbeat_at`; sweeper detects rows with `last_heartbeat_at < now() - threshold`).
