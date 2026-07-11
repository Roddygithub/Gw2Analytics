# Plan 044 — v0.9.13 `post_minimal_fight` error message

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — test suite patterns deep pass
**Status:** pending
**Effort:** S
**Category:** DX (test failure clarity)
**Files touched:** `apps/api/tests/_fixtures.py` (1 file, additive change only) + 1 new test case in any consumer of `post_minimal_fight` (e.g. `apps/api/tests/test_backfill.py`)

## Problem

`apps/api/tests/_fixtures.py::wait_for_upload_completion`
polls the upload status until the background parser
flips `status` to `"completed"`. If the parser fails
(e.g. a corrupt EVTC blob, a missing field, a parser
bug), the status flips to `"failed"` and the loop
exits after 5 seconds with a cryptic error:

```python
msg = f"upload {upload_id} did not reach 'completed' within 5s"
raise AssertionError(msg)
```

The error message identifies the upload_id but does
NOT include:
- The upload's `status` (was it `"failed"`? still
  `"pending"`?).
- The upload's `error_message` field (the parser's
  structured error: e.g. "EVTC header missing magic
  bytes", "agent_count=0", "blob is gzip-corrupt").

The operator has to:
1. Re-poll the upload manually (`curl /api/v1/uploads/{id}`)
2. Read the `error_message` field
3. Correlate with the test's input

This is wasteful for a test that fails intermittently
on a real parser bug. The canonical fix is to include
the status + error_message in the AssertionError.

### Severity

- **DX**: LOW — the test failure is catchable, the
  operator just has to do extra work to diagnose.
- **Reliability**: LOW — no false negatives; the
  test correctly fails when the parser fails.

## Goals

- Update `wait_for_upload_completion` to include the
  upload's `status` + `error_message` in the
  AssertionError when the upload does not reach
  `"completed"` within the 5s ceiling.
- Add a hermetic test that injects a parser failure
  (e.g. a blob with an invalid header) and asserts
  the AssertionError includes the error_message.

## Non-goals

- Reducing the 5s ceiling. The 5s wait is generous
  (the parser completes in milliseconds for a
  fixture-sized blob); a real parser failure flips
  to `"failed"` within 100ms. The 5s ceiling
  catches a real hang (e.g. a deadlock in the BG
  task) without false-positiving on slow CI.
- Adding structured logging to the BG parser task
  to surface the failure earlier. Out of scope
  (the parser's `error_message` field is the
  canonical failure surface).
- Catching the parser failure at the test-fixture
  level (e.g. asserting `status == "failed"` and
  re-raising with a structured exception). Out of
  scope (the canonical "test fails when the
  parser fails" behaviour is the AssertionError;
  adding a custom exception would force every
  test to handle it).

## Implementation

### File: `apps/api/tests/_fixtures.py`

Update `wait_for_upload_completion` to include the
status + error_message in the AssertionError.

```python
def wait_for_upload_completion(upload_id: str) -> str:
    """Poll the upload status until the background
    parser flips ``status`` to ``"completed"``, then
    return the persisted ``fight_id``.

    The POST handler spawns :func:`process_parse` via
    FastAPI's ``BackgroundTasks``, so the upload is
    still ``"pending"`` immediately after the POST.
    Downstream tests depend on the events blob being
    written (the ``/players`` + ``/squads`` +
    ``/skills`` routes read it), so the wait is
    mandatory. A 5s ceiling is generous: the parser
    completes in milliseconds for a fixture-sized
    blob.

    A small post-completion ``time.sleep(0.1)`` gives
    the parser a chance to write the events blob
    before the downstream tests query it; the
    BackgroundTasks runner fires after the POST
    response is sent, so the first poll iteration
    may race the task startup.

    On timeout (5s ceiling reached without the upload
    reaching ``"completed"``), the AssertionError
    includes the upload's current ``status`` and
    ``error_message`` so the operator can diagnose
    the failure without re-polling the upload
    manually. The ``status="failed"`` case is the
    canonical "parser bug" path; the
    ``status="pending"`` case is the canonical "BG
    task hung" path.
    """
    last_status: str | None = None
    last_error: str | None = None
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        body = upload_resp.json()
        last_status = body.get("status")
        last_error = body.get("error_message")
        if last_status == "completed":
            time.sleep(0.1)
            return str(body["fight_id"])
        time.sleep(0.1)
    msg = (
        f"upload {upload_id} did not reach 'completed' "
        f"within 5s (last_status={last_status!r}, "
        f"last_error={last_error!r}). "
        f"If last_status == 'failed', the parser "
        f"rejected the blob; the error_message is the "
        f"parser's structured error. "
        f"If last_status == 'pending', the BG task "
        f"hung; check the uvicorn logs for the "
        f"process_parse stack trace."
    )
    raise AssertionError(msg)
```

### File: `apps/api/tests/test_backfill.py` (additions)

Add a new test that injects a parser failure (a blob
with an invalid header) and asserts the AssertionError
includes the error_message.

```python
def test_post_minimal_fight_error_message_includes_parser_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A parser failure surfaces in
    ``wait_for_upload_completion``'s AssertionError.

    The test POSTs a blob with an invalid EVTC header
    (``b"NOT_EVTC"`` instead of ``b"EVTC"``); the
    parser rejects the blob and the upload status
    flips to ``"failed"`` with an error_message. The
    helper raises an AssertionError that includes
    the error_message.
    """
    blob = make_minimal_zevtc(
        agents=[(1, 2, 18, "Test", True)],
        build="20250101",
    )
    # Overwrite the EVTC header to invalidate it.
    # The zip file is intact (the parser's
    # _first_entry succeeds); the EVTC header
    # inside the zip is wrong.
    import zipfile
    from io import BytesIO
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("fight.evtc", b"NOT_EVTC" + b"\x00" * 21)
    bad_blob = buf.getvalue()

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("bad.zevtc", bad_blob, "application/octet-stream")},
    )
    assert resp.status_code == 201
    upload_id = resp.json()["id"]

    with pytest.raises(AssertionError) as exc_info:
        wait_for_upload_completion(upload_id)

    err = str(exc_info.value)
    assert "last_status='failed'" in err
    assert "EVTC" in err  # the parser's error_message mentions EVTC
```

## Test plan

1. **1 new hermetic test** in
   `apps/api/tests/test_backfill.py` (or any
   consumer of `post_minimal_fight`) covers the
   parser-failure path. The test POSTs a blob
   with an invalid header + asserts the
   AssertionError includes the status +
   error_message.
2. **All existing tests pass** — the change is
   backwards-compatible for any test where the
   parser succeeds (the AssertionError path is
   unchanged).
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `wait_for_upload_completion` includes the
      upload's `status` + `error_message` in the
      AssertionError.
- [ ] 1 new hermetic test in
      `apps/api/tests/test_backfill.py` passes.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the test
      helper is test-only).

## Out-of-scope / deferred

- **Reducing the 5s ceiling**: out of scope (the
  5s wait is generous; a real parser failure
  flips to `"failed"` within 100ms; the 5s
  ceiling catches a real hang without
  false-positiving on slow CI).
- **Adding structured logging to the BG parser
  task**: out of scope (the parser's
  `error_message` field is the canonical failure
  surface).
- **Catching the parser failure at the test-fixture
  level with a custom exception**: out of scope
  (the canonical AssertionError is sufficient).

## Maintenance notes

- **The `last_status` + `last_error` local
  variables** are tracked in the for loop so the
  AssertionError can include them after the loop
  exits. The variables are unused inside the loop
  body; they are only used in the error path.
  Mypy + ruff both accept the assignment as
  "used" (the error path uses them).
- **The 5s ceiling is intentionally generous**:
  a real parser failure flips to `"failed"`
  within 100ms. The 5s ceiling catches a real
  hang (e.g. a deadlock in the BG task) without
  false-positiving on slow CI runners. A future
  hardening pass can lower the ceiling to 2s.
- **The test injects a parser failure by
  overwriting the EVTC header** to `b"NOT_EVTC"`.
  The parser's `_first_entry` checks the magic
  bytes and raises `EvtcParseError`; the
  `process_parse` BG task catches the error +
  writes `status="failed"` + `error_message` to
  the uploads table. The test asserts the
  AssertionError includes both the status +
  the parser's error message.
- **The test uses `pytest.raises(AssertionError)`
  + `exc_info.value` to capture the message**;
  the assertions on `err` (the AssertionError's
  `str()`) verify the message includes the
  expected substrings (`"last_status='failed'"`,
  `"EVTC"`).
