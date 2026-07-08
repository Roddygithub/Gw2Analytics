# 006-v091-upload-bg-task-closed-session

**Status**: DONE (shipped in v0.9.1 hardening slice)
**Date**: 2026-07-08 (executed as part of H1 + H2 followups)
**Drift-detection base**: `ef5e4f3`
**Addresses finding**: #3 — `BackgroundTasks(process_parse)` receives the request-scoped `db` after FastAPI dependency teardown; raises `DetachedInstanceError`; upload never reaches `COMPLETED`.

## Context

`apps/api/src/gw2analytics_api/routes/uploads.py` schedules `process_parse` as a FastAPI
`BackgroundTasks` task that takes the request-scoped `db: Session = Depends(get_session)`.
FastAPI executes BG tasks AFTER the response has been sent and the dependency
generator\'s `finally` block has fired, which closes the session. `process_parse` then
raises `DetachedInstanceError` on its first query. The upload silently never reaches
`UPLOAD_STATUS_COMPLETED`; `dispatch_for_upload` is never triggered; the webhook
integration is dormant. This works in the e2e test suite only because the existing
`_wait_for_upload_completion` helper uses `time.sleep(0.1)` polling — the race is
often won in tests, often lost in production.

The v0.9.0 webhook slice already established the correct pattern:
`dispatch_for_upload(session_factory, upload_id)` opens its own worker-scoped session.
This plan applies the same pattern to `process_parse`.

## Files in scope

- `apps/api/src/gw2analytics_api/services.py` (`process_parse` and its session dependency)
- `apps/api/src/gw2analytics_api/routes/uploads.py` (the BG-task registration line)
- `apps/api/main.py` (read-only — confirm `get_sessionmaker` import is in scope for re-use)
- `apps/api/tests/test_uploads_e2e.py` (add a focused regression test)

## Files explicitly out of scope

- `apps/api/src/gw2analytics_api/workers/webhook_dispatch.py` (already correct pattern; do not touch)
- `apps/api/src/gw2analytics_api/workers/webhook_scheduler.py` (already correct pattern)
- `apps/api/src/gw2analytics_api/database.py` (read-only — the factory is the source)

## Steps

1. **Inspect `process_parse` signature and the current BG-task caller**.
   - Verify command: `grep -n 'def process_parse\\|process_parse(' apps/api/src/gw2analytics_api/services.py apps/api/src/gw2analytics_api/routes/uploads.py`
   - Expected: `process_parse` takes `db: Session` directly. The caller uses `background_tasks.add_task(process_parse, db=db)`.

2. **Refactor `process_parse` to take `session_factory: Callable[[], Session]`**.
   - Import `get_sessionmaker` from `gw2analytics_api.database`.
   - Body wraps the existing logic in `with session_factory() as db:` (mirroring `dispatch_for_upload`).
   - The function must commit at the end (existing semantics).
   - Update the docstring to record the new contract.
   - Verify command: `grep -n 'def process_parse\\|session_factory' apps/api/src/gw2analytics_api/services.py`
   - Expected: signature now `process_parse(session_factory: Callable[[], Session], upload_id: uuid.UUID)`.

3. **Update the BG-task registration in `routes/uploads.py`**.
   - Replace `background_tasks.add_task(process_parse, db=db)` with `background_tasks.add_task(process_parse, session_factory=get_sessionmaker)`.
   - Verify command: `grep -n 'background_tasks.add_task' apps/api/src/gw2analytics_api/routes/uploads.py`
   - Expected: only the new call.

4. **Run ruff + mypy on the touched files**.
   - Verify command: `cd apps/api && uv run ruff check src/gw2analytics_api/services.py src/gw2analytics_api/routes/uploads.py src/gw2analytics_api/main.py && uv run mypy src/gw2analytics_api/services.py src/gw2analytics_api/routes/uploads.py`
   - Expected: both clean. The `Callable[...]` import is already in scope from the v0.9.1 webhook scheduler work — verify and reuse.

5. **App still boots**.
   - Verify command: `cd apps/api && uv run python -c 'from gw2analytics_api.main import app; print(\"OK routes=\", len(app.routes))'`
   - Expected: `OK routes=13`.

## Test plan

- Add a focused regression test `apps/api/tests/test_uploads_e2e.py::test_background_task_session_alive_at_invocation` that:
  - Builds a minimal `.zevtc` blob (existing `_make_minimal_zevtc` helper).
  - POSTs it to `/api/v1/uploads`.
  - **Without** the existing `time.sleep(0.1)` poll, asserts on the next request that `upload.status == UPLOAD_STATUS_COMPLETED`.
  - This test catches the regression where `process_parse` would `DetachedInstanceError`.
- Verify command: `cd apps/api && uv run pytest tests/test_uploads_e2e.py::test_background_task_session_alive_at_invocation -v`
- Expected: PASS.

## Maintenance note

All BG-task entrypoints in `apps/api/src/gw2analytics_api/` MUST take a `session_factory` rather than a request-scoped `db` from here forward. Add a docstring note at the top of `services.py` pinning this rule. The webhook slice already enforces the same convention by code review — document it once, then enforce via peer review (or a future ruff `RUF0XX` custom rule).

## Escape hatches

- **STOP** if the e2e test suite reports wobble in `test_uploads_e2e.py` post-refactor. Investigate whether `session_factory` resolves to the cached `sessionmaker` (which holds a connection pool) or a fresh one; under heavy BG-task load, connection-pool exhaustion could leak through.
- **STOP** if `process_parse` is later migrated to Celery or Arq. The refactor remains compatible (any "in-process worker" passes `session_factory` cleanly), but if anyone proposes a fork-style executor that does NOT share the FastAPI process, this rule invalidates.
