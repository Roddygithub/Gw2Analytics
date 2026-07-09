# Plan 019 — v0.9.5: narrow `_persist_event_blob` `except Exception` to surface programming bugs

**Author:** senior-advisor audit (improve skill, standard effort) — v0.9.5 cleanup of the lowest-leverage deferred v0.9.3 findings.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`apps/api/src/gw2analytics_api/services.py::_persist_event_blob` wraps the `parser.parse_events(evtc_bytes)` + `gzip.compress(jsonl)` + `put_events(fight_id, gz_bytes)` chain in `except Exception`. The docstring at lines 195-230 documents the trade-off: a real programming bug (e.g. an `AttributeError` from a future refactor) would be silently swallowed + logged + the upload would still flip to `COMPLETED` with `events_blob_uri=NULL`. The operator has no way to detect the regression; the only signal is `logger.exception` which is monitored only by humans reading logs.

The fix: narrow the catch to a specific tuple of expected exceptions:
- `EvtcParseError` (malformed EVTC archive)
- `S3Error` (MinIO failure)
- `OSError` (filesystem / network)
- `gzip.BadGzipFile` (corrupt blob)
- `pydantic.ValidationError` (model mismatch)

A real `AttributeError` / `NameError` / `TypeError` (programming bug) propagates up to the surrounding `process_parse` try/except (which catches `(RuntimeError, ValueError)` and writes `error_message`). The upload flips to `FAILED` with the bug name in `error_message` — visible to the operator + alertable.

The 5-line narrowing closes the silent-bug surface while preserving the best-effort contract for genuine runtime failures.

---

## Files IN scope

- `apps/api/src/gw2analytics_api/services.py` (1 `except` clause change).
- `apps/api/tests/test_persist_event_blob_except.py` — **NEW** (2 tests).

## Files NOT in scope

- `apps/api/src/gw2analytics_api/main.py` (no FastAPI wiring change).
- `apps/api/src/gw2analytics_api/storage.py` (no storage change).
- `apps/api/src/gw2analytics_api/workers/*` (the dispatcher reads `events_blob_uri`; the catch doesn't affect dispatch).

---

## Current code (read from `44ea862`)

### `services.py::_persist_event_blob` (around line 195-230)

```python
def _persist_event_blob(db, upload, evtc_bytes, fight_id):
    """Drain the cbtevent block into a MinIO blob and write the key back.

    - Empty streams leave events_blob_uri as NULL.
    - ANY exception raised by ``parse_events`` or ``put_events`` is
      logged and swallowed so the upload still flips to
      ``COMPLETED`` with the fight-row + agents + skills
      persisted. The catch is intentionally broad because
      this call sits OUTSIDE the ``process_parse``
      try/except ...
    """
    parser = PythonEvtcParser()
    try:
        events = list(parser.parse_events(evtc_bytes))
        if not events:
            logger.debug(...)
            return
        jsonl = "\n".join(event.model_dump_json() for event in events).encode("utf-8")
        gz_bytes = gzip.compress(jsonl)
        blob_uri = put_events(fight_id, gz_bytes)
    except Exception:
        # parse_events raises EvtcParseError; put_events raises
        # S3Error (and OSError variants); anything truly
        # unexpected lands here too. All three are treated
        # identically: degrade to events_blob_uri = NULL.
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return
    ...
```

The `except Exception` catches everything — including programming bugs that should fail loud.

---

## Step-by-step

### Step 1 — Narrow the catch

In `services.py::_persist_event_blob`, REPLACE:

```python
    parser = PythonEvtcParser()
    try:
        events = list(parser.parse_events(evtc_bytes))
        if not events:
            logger.debug(...)
            return
        jsonl = "\n".join(event.model_dump_json() for event in events).encode("utf-8")
        gz_bytes = gzip.compress(jsonl)
        blob_uri = put_events(fight_id, gz_bytes)
    except Exception:
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return
```

WITH:

```python
    parser = PythonEvtcParser()
    try:
        events = list(parser.parse_events(evtc_bytes))
        if not events:
            logger.debug(...)
            return
        jsonl = "\n".join(event.model_dump_json() for event in events).encode("utf-8")
        gz_bytes = gzip.compress(jsonl)
        blob_uri = put_events(fight_id, gz_bytes)
    except (EvtcParseError, S3Error, OSError, gzip.BadGzipFile, ValidationError) as exc:
        # v0.9.5 plan 019: narrowed from ``except Exception`` to
        # the specific exception types this call site can
        # legitimately raise. A real programming bug
        # (AttributeError, NameError, TypeError, KeyError) is
        # now propagated UP to the surrounding ``process_parse``
        # try/except (which writes the exception name to
        # ``uploads.error_message`` and flips the upload to
        # FAILED) instead of being silently swallowed.
        # ``gzip.BadGzipFile`` is a subclass of ``OSError`` since
        # Python 3.8 but listed explicitly for readability.
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", exc)
        return
```

(Add the `gzip` + `ValidationError` imports to the top of `services.py` if not already there; `gzip` is already imported. Add `from pydantic import ValidationError` if not already imported.)

### Step 2 — Add 2 regression tests

`apps/api/tests/test_persist_event_blob_except.py` (NEW):

```python
"""v0.9.5 plan 019: _persist_event_blob except-narrowing regression tests."""
from __future__ import annotations

from unittest.mock import patch
import gzip

import pytest
from minio.error import S3Error

from gw2analytics_api.services import _persist_event_blob


def test_s3_error_is_swallowed_with_warning_log(monkeypatch):
    """Genuine S3Error: blob stays NULL + log is WARNING-level."""
    def fake_put_events(fight_id, gz_bytes):
        raise S3Error("minio down", "test", "test")
    monkeypatch.setattr(
        "gw2analytics_api.services.put_events", fake_put_events,
    )
    with patch("gw2analytics_api.services.logger") as mock_log:
        _persist_event_blob(db=None, upload=None, evtc_bytes=b"...", fight_id="FIGHT")
    # No exception escapes; logger.exception called.
    mock_log.exception.assert_called_once()


def test_attribute_error_propagates_to_caller():
    """Programming bug (AttributeError) is NOT swallowed; propagates UP."""
    def fake_parse_events(evtc_bytes):
        # Simulate a programming bug: a typo in a future refactor
        # that references a non-existent attribute.
        raise AttributeError("'NoneType' object has no attribute 'foo'")
    with patch("gw2analytics_api.services.PythonEvtcParser.parse_events", fake_parse_events):
        with pytest.raises(AttributeError):
            _persist_event_blob(
                db=None, upload=None, evtc_bytes=b"...", fight_id="FIGHT",
            )
```

---

## Verification commands

```bash
uv run ruff check apps/api
uv run mypy --no-incremental libs apps
uv run pytest apps/api/tests/test_persist_event_blob_except.py -v
uv run pytest apps/api/tests/test_uploads_e2e.py -v
# Expected: existing 92+ pass + 0 fail + 3 skip.
```

A worktree `git diff` against `44ea862` must show ONLY:
- `apps/api/src/gw2analytics_api/services.py` (1 line in the except clause + 1-2 import additions).
- `apps/api/tests/test_persist_event_blob_except.py` (NEW, 2 tests).
- `CONTRIBUTING.md` (1 short subsection on the narrowed catch).

## Maintenance note

- The narrowed catch surfaces `AttributeError`, `NameError`, `TypeError`, `KeyError` as `uploads.error_message` entries. Operators monitoring `uploads.status='failed'` + `error_message` will see these immediately.
- A regression test (plan 019 step 2) explicitly asserts that an `AttributeError` propagates. If a future refactor broadens the catch back to `except Exception`, this test fails.
- The trade-off: a bug that previously stayed silent (logged) now flips the upload to `FAILED` with the bug name visible. This is the correct production posture — a silent bug is worse than a visible FAILED upload (which can be retried via re-upload).

## Escape hatches

- If a future plan needs to add an exception type (e.g. a new `CompressionError`), add it to the tuple. The test fixture is updated in lockstep.
- If a future plan migrates to async storage (e.g. `aiobotocore`), the catch may need a different shape. The 5-tuple contract is for sync code; async code raises a different exception surface. Out of scope here.
- If a future plan adds retry-with-backoff inside `_persist_event_blob` (e.g. retry the MinIO PUT 3 times before degrading), the catch stays narrow — the retry loop wraps the existing try/except. Out of scope here.
