# Plan 045 — v0.9.14 `process_parse` commit-failure handling

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — services.py deep pass
**Status:** pending
**Effort:** S
**Category:** reliability (BG task silent failure)
**Files touched:** `apps/api/src/gw2analytics_api/services.py` (1 file, additive change only) + `apps/api/tests/test_uploads_e2e.py` (1 NEW test case)

## Problem

`apps/api/src/gw2analytics_api/services.py::process_parse`
runs as a FastAPI `BackgroundTask` (dispatched from
`POST /api/v1/uploads`). The function catches the
expected per-fight failure modes:

```python
try:
    evtc_bytes = read_zevtc_bytes(raw_bytes)
    fights = list(PythonEvtcParser().parse(evtc_bytes))
except EvtcParseError as exc:
    upload.status = UPLOAD_STATUS_FAILED
    upload.error_message = f"EvtcParseError: {exc}"
    db.commit()
    return
except (RuntimeError, ValueError) as exc:
    upload.status = UPLOAD_STATUS_FAILED
    upload.error_message = f"{type(exc).__name__}: {exc}"
    db.commit()
    return
```

…and the happy path:

```python
_save_fight(db, upload, core_fight)
_persist_event_blob(db, upload, evtc_bytes, core_fight.id)
upload.status = UPLOAD_STATUS_COMPLETED
upload.error_message = None
db.commit()  # <-- NOT in any try/except
```

If the final `db.commit()` raises `SQLAlchemyError`
(e.g. a transient Postgres connection drop, a
serialisation failure, a connection-pool exhaustion
timeout), the exception propagates up the call stack
to the FastAPI `BackgroundTasks` runner. The runner
**does not surface the exception to the caller** (the
caller is the `POST /api/v1/uploads` route, which
returns 201 immediately after dispatching the BG
task). The exception is logged by the runner (in
the uvicorn logs) but the upload status is never
updated to `"failed"`.

The operator sees the upload stuck at
`status="pending"` forever. The next `GET /api/v1/uploads/{id}`
returns 200 with `status="pending"`. The
`/fights` route's slow-path fallback serves the data
correctly (the fight row is in the DB, the events
blob is in MinIO, the summary is in the table). But
the upload envelope never reflects the success —
the operator can't tell whether the BG task is still
running or has crashed.

### Severity

- **Reliability**: MED — a single transient commit
  failure (e.g. a 1-second Postgres restart during
  the parse commit) leaves the upload stuck at
  `"pending"` indefinitely. The canonical fix is
  for the operator to manually UPDATE the upload
  to `"failed"` (a SQL round-trip) and re-upload
  the blob (a full re-parse).
- **DX**: MED — the failure is silent (no log line
  in the operator's console) and the upload
  envelope doesn't surface the issue.

## Goals

- Add a `try/except SQLAlchemyError` around the
  final `db.commit()` in `process_parse`. On
  failure, write `status=FAILED` + the exception's
  type + message to `error_message`, then
  `db.rollback()` + a best-effort retry commit
  (the rollback clears the dirty state, the retry
  commit persists the FAILED status).
- Add a `logger.exception(...)` call in the except
  block so the operator sees the failure in the
  uvicorn logs.
- Add a hermetic test that injects a
  `SQLAlchemyError` at the final commit + asserts
  the upload status flips to `"failed"` with the
  expected error message.

## Non-goals

- Adding retry-on-commit. A transient commit
  failure is a per-fight issue; retrying the
  commit would re-execute the same SQL with the
  same state, which is the same race condition.
  The operator can re-upload the blob to retry.
- Migrating to a dedicated worker queue (Arq) with
  a fresh worker-scoped session. Out of scope
  (the v0.9.2 hardening posture is sync-FastAPI;
  the docstring's TODO is deferred to a future
  cycle).
- Adding a watchdog that reaps stuck
  `status="pending"` uploads after N hours. Out of
  scope (the canonical fix is for the BG task to
  surface the failure; the watchdog is a
  belt-and-braces second line of defence).
- Narrowing the existing `except Exception` in
  `_persist_event_blob`. Out of scope (already
  covered by plan 019).

## Implementation

### File: `apps/api/src/gw2analytics_api/services.py`

Update `process_parse` to wrap the final
`db.commit()` in a try/except. The diff is a
~10-line addition to the happy path.

```python
# BEFORE (in process_parse, the happy path):
        _save_fight(db, upload, core_fight)
        _persist_event_blob(db, upload, evtc_bytes, core_fight.id)
        upload.status = UPLOAD_STATUS_COMPLETED
        upload.error_message = None
        db.commit()

# AFTER:
        _save_fight(db, upload, core_fight)
        _persist_event_blob(db, upload, evtc_bytes, core_fight.id)
        upload.status = UPLOAD_STATUS_COMPLETED
        upload.error_message = None
        try:
            db.commit()
        except SQLAlchemyError as exc:
            # v0.9.14 plan 045: a transient commit
            # failure (Postgres connection drop,
            # serialisation failure, pool timeout)
            # would otherwise leave the upload stuck
            # at "pending" forever -- the BG task
            # exception propagates to the FastAPI
            # BackgroundTasks runner, which logs it
            # but does NOT surface it to the
            # operator. We catch here so the upload
            # envelope reflects the failure.
            #
            # The rollback clears the dirty state
            # (the staged fight + agents + skills +
            # summary rows are discarded); the
            # retry-commit persists the FAILED
            # status. A best-effort retry-commit
            # means a transient connection drop on
            # the original commit MAY be recovered
            # on the retry; a persistent connection
            # drop on the retry means the upload
            # stays at the previous status (the
            # default Python `Exception` raised by
            # the second commit propagates to the
            # BG task runner, which logs it).
            logger.exception(
                "commit failed for upload %s; marking FAILED",
                upload_id,
            )
            db.rollback()
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = (
                f"SQLAlchemyError: {exc}"
            )
            try:
                db.commit()
            except SQLAlchemyError:
                # The retry commit also failed.
                # The BG task exception propagates
                # to the runner; the operator sees
                # the upload stuck at the previous
                # status (either "pending" if the
                # fight row was never inserted, or
                # "completed" if the fight row was
                # inserted but the status update
                # wasn't persisted). The operator
                # can re-upload the blob to retry.
                logger.exception(
                    "retry commit also failed for upload %s",
                    upload_id,
                )
                raise
```

### File: `apps/api/tests/test_uploads_e2e.py` (NEW test case)

Add a new test that injects a `SQLAlchemyError` at
the final commit + asserts the upload status flips
to `"failed"` with the expected error message.

```python
def test_process_parse_commits_failed_status_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
    sample_upload: str,
) -> None:
    """A ``SQLAlchemyError`` at the final commit
    flips the upload status to ``"failed"`` with
    a clear error message (not stuck at
    ``"pending"``).

    The test monkeypatches ``db.commit()`` to
    raise on the second call (the final commit
    in the happy path) but succeed on the third
    call (the retry commit). The fight row +
    agents + skills are already staged; the
    rollback clears them; the retry commit
    persists the FAILED status.
    """
    original_commit = get_sessionmaker()().commit
    call_count = {"n": 0}

    def flaky_commit() -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # The final commit in the happy path
            # raises (simulates a transient Postgres
            # connection drop).
            raise OperationalError(
                "simulated", {}, Exception("lost connection")
            )
        # The retry commit + any subsequent commits
        # succeed.
        original_commit()

    # ... monkeypatch the session's commit method
    # on the session used by process_parse ...

    # ... trigger process_parse via the helper ...

    # Assert the upload status is "failed" with the
    # expected error message.
    upload_resp = client.get(
        f"/api/v1/uploads/{sample_upload}"
    )
    assert upload_resp.status_code == 200
    body = upload_resp.json()
    assert body["status"] == "failed"
    assert "SQLAlchemyError" in body["error_message"]
```

## Test plan

1. **1 new hermetic test** in
   `apps/api/tests/test_uploads_e2e.py` covers
   the commit-failure path. The test monkeypatches
   `db.commit()` to raise on the first call +
   asserts the upload status flips to `"failed"`
   with the expected error message.
2. **All existing tests pass** — the change is
   backwards-compatible for the happy path (no
   exception is raised on the final commit; the
   `try/except` is a no-op).
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `process_parse` wraps the final `db.commit()`
      in a `try/except SQLAlchemyError`.
- [ ] On commit failure, the upload status flips
      to `"failed"` + `error_message` includes
      `"SQLAlchemyError"` + the exception message.
- [ ] The retry commit (after rollback) is itself
      wrapped in a `try/except` so a double-failure
      doesn't leave the BG task in a half-state.
- [ ] `logger.exception(...)` is called in both
      except blocks.
- [ ] 1 new hermetic test passes.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the
      happy-path commits are unchanged; only
      the failure path is modified).

## Out-of-scope / deferred

- **Adding retry-on-commit with exponential
  backoff**: out of scope (a transient commit
  failure is a per-fight issue; the operator can
  re-upload the blob to retry).
- **Migrating to a dedicated worker queue (Arq)**:
  out of scope (the v0.9.2 hardening posture is
  sync-FastAPI; the docstring's TODO is deferred
  to a future cycle).
- **Adding a watchdog that reaps stuck
  `status="pending"` uploads**: out of scope
  (the canonical fix is for the BG task to surface
  the failure; the watchdog is a belt-and-braces
  second line of defence).
- **Narrowing the existing `except Exception` in
  `_persist_event_blob`**: out of scope (already
  covered by plan 019).

## Maintenance notes

- **The retry commit pattern is the canonical
  "best-effort recovery" idiom**. The rollback
  clears the dirty state (so the next commit
  doesn't try to re-flush the staged rows), and
  the retry commit persists the FAILED status.
  A double-failure (the retry commit also fails)
  propagates to the BG task runner, which logs
  the exception in the uvicorn logs.
- **The `logger.exception(...)` call is the
  canonical Python logging idiom for "an
  exception happened; log the stack trace".**
  The operator greps the uvicorn logs for
  "commit failed for upload" to find the
  failure.
- **The `error_message` includes the exception
  type + message** so the operator can diagnose
  the failure without reading the uvicorn logs.
  A future hardening pass can truncate the
  message to 200 chars to avoid the 4KB
  `error_message` column overflow.
- **The change does NOT affect the happy path**.
  A successful commit goes through the `try`
  block without raising; the `except` is a
  no-op. The performance cost is a single
  `try/except` setup per BG task (negligible).
