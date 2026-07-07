"""v0.8.7: unit tests for the CI gate script.

The :mod:`ci_health_gate` script is hermetic in
production (in-process TestClient, < 1 s on a CI
runner). The unit tests are hermetic too: they
monkeypatch ``_fetch_drift`` to return a fixed
:class:`SummaryDrift` so the test doesn't depend on
the test database state.

The 5 test cases cover the 3 entry points of the
script's public API:

- :func:`_save_baseline` -- writes the probe response
  to a JSON file.
- :func:`_check_delta` -- compares the current probe
  response to the baseline, fails on delta >=
  ``MAX_DRIFT_DELTA``. The boundary cases (delta ==
  MAX, delta == MAX - 1) pin the ``>=`` comparison
  (the off-by-one fix from the v0.8.7 round 142
  code-review).
- :func:`main` -- the argparse dispatch (the
  ``--save-baseline`` / ``--check-delta`` / no-args
  modes). The no-args debug mode is a thin pass-through
  that prints the response.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from gw2analytics_api.health import SummaryDrift
from gw2analytics_api.scripts.health_gate import (
    MAX_DRIFT_DELTA,
    _check_delta,
    _save_baseline,
    main,
)


def _make_drift(*, drift_count: int) -> SummaryDrift:
    """Build a :class:`SummaryDrift` with a given ``drift_count``.

    A small helper that pins the
    ``drift_count / total_fights * 100`` formula
    (rounded to 2 decimals) so the test doesn't
    duplicate the formula. The other fields are
    derived: ``fights_with_summaries = total -
    drift_count`` and ``status = "ok" if drift_count
    == 0 else "drift"`` (matches the
    :func:`summary_drift` library's contract).
    """
    total = 10
    with_summary = total - drift_count
    drift_pct = round(drift_count / total * 100, 2) if total > 0 else 0.0
    return SummaryDrift(
        total_fights=total,
        fights_with_summaries=with_summary,
        drift_count=drift_count,
        drift_pct=drift_pct,
        status="ok" if drift_count == 0 else "drift",
    )


def test_save_baseline_creates_json_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--save-baseline`` writes the probe response to a JSON file.

    Asserts the file is created at the requested path,
    the JSON content matches the (monkeypatched) probe
    response exactly, and the exit code is 0. The
    :func:`_fetch_drift` monkeypatch isolates the test
    from the test database state -- the test exercises
    the file-write + JSON-serialisation path, not the
    in-process TestClient path.
    """
    fake_drift = _make_drift(drift_count=0)
    monkeypatch.setattr(
        "gw2analytics_api.scripts.health_gate._fetch_drift",
        lambda: fake_drift,
    )
    baseline_path = tmp_path / "baseline.json"
    exit_code = _save_baseline(str(baseline_path))
    assert exit_code == 0
    assert baseline_path.exists()
    data = json.loads(baseline_path.read_text())
    assert data == fake_drift


def test_check_delta_passes_on_zero_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--check-delta`` with delta = 0 returns 0.

    The baseline and the post-state are identical
    (no drift introduced), so the gate should pass
    (exit 0). The :func:`_fetch_drift` monkeypatch
    pins the post-state to the same value as the
    baseline.
    """
    fake_drift = _make_drift(drift_count=0)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(fake_drift))
    monkeypatch.setattr(
        "gw2analytics_api.scripts.health_gate._fetch_drift",
        lambda: fake_drift,
    )
    exit_code = _check_delta(str(baseline_path))
    assert exit_code == 0


def test_check_delta_fails_when_delta_equals_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--check-delta`` with delta = ``MAX_DRIFT_DELTA`` returns 1.

    The ``>=`` comparison (the off-by-one fix from
    the v0.8.7 round 142 code-review) means a delta
    exactly equal to the budget fails the gate. The
    test pins this boundary: with ``> MAX`` and
    ``MAX = 2``, a delta of 2 would pass (false
    negative); with ``>= MAX``, the regression
    correctly fails.
    """
    fake_drift_baseline = _make_drift(drift_count=0)
    fake_drift_regression = _make_drift(
        drift_count=MAX_DRIFT_DELTA,
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(fake_drift_baseline))
    monkeypatch.setattr(
        "gw2analytics_api.scripts.health_gate._fetch_drift",
        lambda: fake_drift_regression,
    )
    exit_code = _check_delta(str(baseline_path))
    assert exit_code == 1


def test_check_delta_passes_at_budget_minus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--check-delta`` with delta = ``MAX_DRIFT_DELTA`` - 1 returns 0.

    The complement of the boundary test: a delta one
    below the budget must pass (exit 0). The e2e
    suite's legitimate +1 drift (the
    :func:`test_health_summary_surfaces_drift_after_summary_deletion`
    test deletes summary rows) lives in this band;
    the test pins that the legitimate drift is
    within the budget.
    """
    fake_drift_baseline = _make_drift(drift_count=0)
    fake_drift_drift = _make_drift(
        drift_count=MAX_DRIFT_DELTA - 1,
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(fake_drift_baseline))
    monkeypatch.setattr(
        "gw2analytics_api.scripts.health_gate._fetch_drift",
        lambda: fake_drift_drift,
    )
    exit_code = _check_delta(str(baseline_path))
    assert exit_code == 0


def test_no_args_debug_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main()`` with no args prints the response and returns 0.

    The no-args mode is a debug-mode pass-through that
    prints the probe response and returns 0 (the gate
    is not enforced -- the user is just inspecting the
    probe). The :func:`sys.argv` monkeypatch is needed
    because :func:`argparse.ArgumentParser.parse_args`
    reads from :data:`sys.argv` by default; without the
    monkeypatch, pytest's own argv would be parsed and
    the test would fail with an "unrecognized arguments"
    error.
    """
    fake_drift = _make_drift(drift_count=0)
    monkeypatch.setattr(sys, "argv", ["ci_health_gate.py"])
    monkeypatch.setattr(
        "gw2analytics_api.scripts.health_gate._fetch_drift",
        lambda: fake_drift,
    )
    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Health probe response:" in captured.out
