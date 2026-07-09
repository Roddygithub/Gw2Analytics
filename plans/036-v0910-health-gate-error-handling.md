# Plan 036 — v0.9.10 health_gate.py: clearer error handling

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — backfill/scripts deep pass
**Status:** pending
**Effort:** S
**Category:** DX (CI error message clarity)
**Files touched:** `apps/api/src/gw2analytics_api/scripts/health_gate.py` (1 file, additive changes only) + `apps/api/tests/test_ci_health_gate.py` (4 NEW test cases)

## Problem

`apps/api/src/gw2analytics_api/scripts/health_gate.py` is
the CI gate that closes the loop on the v0.8.4 materialise
(the `OrmFightPlayerSummary` population drift probe). The
gate is invoked in `.github/workflows/ci.yml` via:

```yaml
- name: Health probe baseline (v0.8.7)
  run: uv run python -m gw2analytics_api.scripts.health_gate --save-baseline /tmp/health_baseline.json

- name: Health probe CI gate (v0.8.7 regression check)
  run: uv run python -m gw2analytics_api.scripts.health_gate --check-delta /tmp/health_baseline.json
```

The script has 4 error-handling gaps that surface during
CI runs:

### Gap 1: Missing baseline file → cryptic `FileNotFoundError`

```python
with Path(path).open() as f:
    baseline = json.load(f)
```

If the baseline file is missing (e.g. the `--save-baseline`
step failed silently, the file was deleted by a concurrent
job, the path is wrong), `Path(path).open()` raises
`FileNotFoundError: [Errno 2] No such file or directory: '/tmp/health_baseline.json'`.

The error is somewhat clear (the path is in the message)
but doesn't say "this is the CI gate, the baseline was
expected to exist, did you forget the --save-baseline
step?". The operator has to read the workflow YAML to
figure out what went wrong.

### Gap 2: Malformed JSON baseline → cryptic `JSONDecodeError`

```python
with Path(path).open() as f:
    baseline = json.load(f)
```

If the baseline file is malformed JSON (e.g. a partial
write from a crashed `--save-baseline` step, a manual
edit by the operator), `json.load(f)` raises
`json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

The error is cryptic — it doesn't say "the baseline file
is malformed; the canonical fix is to re-run the
--save-baseline step".

### Gap 3: Probe 5xx → cryptic `HTTPError`

```python
def _fetch_drift() -> SummaryDrift:
    client = TestClient(app)
    response = client.get("/api/v1/health/summary")
    response.raise_for_status()  # <-- raises HTTPError on 5xx
    return cast(SummaryDrift, response.json())
```

If the probe returns 5xx (e.g. the FastAPI app failed to
start, a startup event raised, a DB connection error in
the health route), `response.raise_for_status()` raises
`httpx.HTTPStatusError: Server error '500 Internal Server
Error' for url 'http://testserver/api/v1/health/summary'`.

The error doesn't say "the health probe endpoint failed;
the issue is NOT with the drift delta but with the
upstream health probe itself". The operator has to
manually hit the endpoint to figure out the real failure.

### Gap 4: Probe JSON missing `drift_count` → cryptic `KeyError`

```python
delta = data["drift_count"] - baseline["drift_count"]
```

If either response is missing the `drift_count` key
(e.g. a v0.8.7+ API change that renamed the field, a
malformed probe response), the script raises `KeyError:
'drift_count'`.

The error doesn't say "the probe response shape has
changed; check the SummaryDrift TypedDict in
gw2analytics_api.health".

## Goals

- Replace the 4 cryptic errors with clear, actionable
  error messages that identify (a) what went wrong, (b)
  where in the script it happened, (c) the canonical fix.
- Add 4 hermetic tests: (1) missing baseline file, (2)
  malformed JSON baseline, (3) probe 5xx, (4) missing
  `drift_count` key.

## Non-goals

- Switching from `TestClient` to a real HTTP client. The
  in-process `TestClient` is the canonical hermetic
  pattern (no uvicorn boot, no port binding, no race
  condition).
- Adding retry on probe 5xx. A probe 5xx is a real
  problem (the FastAPI app failed to start); retry would
  mask the symptom.
- Switching to a structured logging library (e.g.
  `structlog`). The current `print()`-based output is
  the canonical CI pattern (the operator reads the log
  in the GitHub Actions UI).

## Implementation

### File: `apps/api/src/gw2analytics_api/scripts/health_gate.py`

Replace the 4 error-handling sites with clear,
actionable error messages. The diff is a series of
`try/except` additions + a custom exception class.

```python
"""v0.8.7: CI gate for the operational health probe.

.. (existing docstring) ..

Error handling
--------------

The gate has 4 distinct error paths, each with a clear,
actionable error message that identifies (a) what went
wrong, (b) where in the script it happened, (c) the
canonical fix:

1. **Missing baseline file** (``--check-delta PATH`` is
   called with a path that doesn't exist): the script
   prints a clear error + exits 1. The error message
   identifies the path + reminds the operator that the
   baseline must be created via the ``--save-baseline``
   step BEFORE the e2e suite.

2. **Malformed JSON baseline** (the baseline file exists
   but contains invalid JSON): the script prints a clear
   error + exits 1. The error message identifies the path
   + reminds the operator that the canonical fix is to
   re-run the ``--save-baseline`` step.

3. **Probe 5xx** (the in-process ``TestClient`` returns
   5xx from ``/api/v1/health/summary``): the script
   prints a clear error + exits 1. The error message
   identifies the status code + the URL + reminds the
   operator that the issue is with the upstream health
   probe (NOT the drift delta).

4. **Probe response missing ``drift_count``** (the
   probe returns 200 but the JSON is missing the
   expected field): the script prints a clear error +
   exits 1. The error message identifies the missing
   field + the canonical shape (``SummaryDrift``
   TypedDict) + reminds the operator that the probe
   response shape has likely changed (a v0.8.7+
   breaking change).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final, cast

from fastapi.testclient import TestClient

from gw2analytics_api.health import SummaryDrift
from gw2analytics_api.main import app

MAX_DRIFT_DELTA: Final[int] = 2


def _error_and_exit(msg: str) -> int:
    """Print a clear error message to stderr + exit 1.

    The canonical error message format for the gate. The
    error is printed to stderr (not stdout) so the
    GitHub Actions UI shows it as a failure (the
    `print` is on stderr; the summary line is on
    stdout).
    """
    print(f"CI gate ERROR: {msg}", file=sys.stderr)
    return 1


def _fetch_drift() -> SummaryDrift:
    """Hit /api/v1/health/summary via in-process TestClient.

    Raises a clear error if the probe returns 5xx or the
    response is missing the ``drift_count`` field. The
    errors are caught by the caller and converted to a
    clear ``_error_and_exit`` message.
    """
    client = TestClient(app)
    try:
        response = client.get("/api/v1/health/summary")
    except Exception as exc:
        raise RuntimeError(
            f"failed to hit /api/v1/health/summary via "
            f"TestClient: {exc!r}. This is a CI-script "
            f"failure (the FastAPI app failed to "
            f"initialise); check the test setup."
        ) from exc
    if not response.is_success:
        raise RuntimeError(
            f"/api/v1/health/summary returned HTTP "
            f"{response.status_code}: {response.text!r}. "
            f"The issue is with the upstream health probe "
            f"itself (NOT the drift delta). The canonical "
            f"fix is to debug the health route -- the "
            f"drift delta is meaningless if the probe "
            f"can't return a valid response."
        )
    data = response.json()
    if "drift_count" not in data:
        raise RuntimeError(
            f"/api/v1/health/summary response is missing "
            f"the 'drift_count' field. The canonical "
            f"shape is ``SummaryDrift`` (see "
            f"gw2analytics_api.health). The probe "
            f"response shape has likely changed; check "
            f"the v0.8.7+ CHANGELOG."
        )
    return cast(SummaryDrift, data)


def _save_baseline(path: str) -> int:
    """.. (existing docstring) .."""
    try:
        data = _fetch_drift()
    except RuntimeError as exc:
        return _error_and_exit(str(exc))
    print(f"Health probe baseline: {data}")
    with Path(path).open("w") as f:
        json.dump(data, f)
    return 0


def _check_delta(path: str) -> int:
    """.. (existing docstring) .."""
    try:
        data = _fetch_drift()
    except RuntimeError as exc:
        return _error_and_exit(str(exc))
    print(f"Health probe post-e2e: {data}")

    baseline_path = Path(path)
    if not baseline_path.exists():
        return _error_and_exit(
            f"baseline file does not exist: {path!r}. "
            f"The canonical workflow is to run "
            f"``--save-baseline {path}`` BEFORE the e2e "
            f"suite (in the .github/workflows/ci.yml "
            f"Health probe baseline step) and "
            f"``--check-delta {path}`` AFTER the e2e "
            f"suite. If the baseline was deleted, "
            f"re-run the --save-baseline step."
        )
    try:
        with baseline_path.open() as f:
            baseline = json.load(f)
    except json.JSONDecodeError as exc:
        return _error_and_exit(
            f"baseline file {path!r} is malformed JSON: "
            f"{exc.msg} at line {exc.lineno} column "
            f"{exc.colno}. The canonical fix is to "
            f"re-run the ``--save-baseline {path}`` "
            f"step (a partial write from a crashed "
            f"--save-baseline run is the most common "
            f"cause)."
        )

    if "drift_count" not in baseline:
        return _error_and_exit(
            f"baseline file {path!r} is missing the "
            f"'drift_count' field. The canonical shape "
            f"is ``SummaryDrift`` (see "
            f"gw2analytics_api.health). The baseline "
            f"was likely created against an older API "
            f"version; re-run ``--save-baseline {path}`` "
            f"against the current API."
        )

    delta = data["drift_count"] - baseline["drift_count"]
    if delta >= MAX_DRIFT_DELTA:
        print(
            f"CI gate FAILED: drift_count delta={delta} "
            f">= max={MAX_DRIFT_DELTA} "
            f"(baseline_drift_count={baseline['drift_count']}, "
            f"post_drift_count={data['drift_count']})",
        )
        return 1

    print(
        f"CI gate OK: drift_count delta={delta} < max={MAX_DRIFT_DELTA}",
    )
    return 0
```

### File: `apps/api/tests/test_ci_health_gate.py` (4 NEW tests)

```python
def test_check_delta_missing_baseline_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing baseline file produces a clear error
    message + exits 1."""
    missing = tmp_path / "nonexistent.json"
    rc = _check_delta(str(missing))
    assert rc == 1
    captured = capsys.readouterr()
    assert "baseline file does not exist" in captured.err
    assert str(missing) in captured.err

def test_check_delta_malformed_json_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed JSON baseline file produces a clear
    error message + exits 1."""
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json")
    rc = _check_delta(str(bad))
    assert rc == 1
    captured = capsys.readouterr()
    assert "malformed JSON" in captured.err

def test_check_delta_probe_5xx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A probe 5xx produces a clear error message +
    exits 1 (not the cryptic HTTPError)."""
    # Save a valid baseline first.
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"drift_count": 0}))
    # Patch the probe to return 5xx.
    from starlette.responses import Response
    def fake_get(self, url: str) -> Response:
        return Response("probe broken", status_code=500)
    monkeypatch.setattr(
        "fastapi.testclient.TestClient.get", fake_get,
    )
    rc = _check_delta(str(baseline))
    assert rc == 1
    captured = capsys.readouterr()
    assert "HTTP 500" in captured.err

def test_check_delta_missing_drift_count_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A baseline file missing the 'drift_count' key
    produces a clear error message + exits 1."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"other_field": 0}))
    rc = _check_delta(str(bad))
    assert rc == 1
    captured = capsys.readouterr()
    assert "missing the 'drift_count' field" in captured.err
```

## Test plan

1. **4 new hermetic tests** (above) cover the 4 error
   paths.
2. **All existing tests pass** — the change is
   backwards-compatible for the happy path
   (save-baseline + check-delta with a valid baseline).
3. **`uv run pytest apps/api/tests/`** exits 0.
4. **`uv run mypy --no-incremental libs apps`** is
   clean.

## Acceptance criteria

- [ ] `apps/api/src/gw2analytics_api/scripts/health_gate.py`
      has the 4 new clear error paths.
- [ ] 4 new hermetic tests pass.
- [ ] All existing tests pass.
- [ ] `mypy --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] Manual smoke: a CI run with a missing baseline
      file shows the clear error message in the
      GitHub Actions UI.

## Out-of-scope / deferred

- **Adding retry on probe 5xx**: out of scope (a
  probe 5xx is a real problem; retry would mask
  the symptom).
- **Switching to a structured logging library**:
  out of scope (the `print()` pattern is the
  canonical CI pattern).
- **Adding a `--strict` flag that fails the gate
  on negative deltas (summary rows were added
  post-baseline)**: out of scope (the current
  behaviour is intentional; a v0.9.11+ plan
  can add the flag).

## Maintenance notes

- **The 4 error paths are the 4 distinct failure
  modes a CI run can hit**. A future hardening
  pass can add more (e.g. "baseline drift_count is
  negative" for a corrupt baseline, "probe
  response has a wrong type" for a v0.8.7+ API
  change).
- **The `_error_and_exit` helper is a private
  function**. A future shared CLI utility module
  (e.g. `apps/api/src/gw2analytics_api/scripts/_cli.py`)
  can promote it. Out of scope for v0.9.10.
- **The error messages reference the canonical
  remediation**. Future CI improvements (e.g. a
  pre-flight check that verifies the baseline file
  exists before running the gate) can reduce the
  noise further. Out of scope for v0.9.10.
