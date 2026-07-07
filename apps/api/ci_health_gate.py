"""v0.8.7: CI gate for the operational health probe.

The :func:`summary_drift` library in
:mod:`gw2analytics_api.health` surfaces the
``OrmFightPlayerSummary`` population drift. This script
is the **CI gate** that closes the loop: it runs in
``.github/workflows/ci.yml::lint-and-test`` to detect
regressions in the v0.8.4 materialise.

Design notes
------------

- **Delta check, not absolute threshold**: the script
  compares the probe response at the END of the e2e
  suite to a baseline captured at the START. The
  ``drift_count`` delta must be <= ``MAX_DRIFT_DELTA``.
  An absolute ``drift_pct`` threshold would be too
  fragile -- a 1% budget fails when the test DB has
  ~10 fights, a 10% budget misses regressions when the
  test DB has ~100 fights (the e2e suite's
  ``test_health_summary_surfaces_drift_after_summary_deletion``
  test deliberately deletes summary rows, producing a
  baseline-dependent ``drift_pct``). The delta
  approach is baseline-agnostic.

- **In-process TestClient**: the script imports the
  FastAPI ``app`` from :mod:`gw2analytics_api.main`
  and uses :class:`fastapi.testclient.TestClient` to
  hit ``/api/v1/health/summary`` directly. No uvicorn
  boot, no port binding, no race condition -- the
  script is a hermetic ``python -m`` invocation that
  completes in < 1 s on a typical CI runner.

- **MAX_DRIFT_DELTA = 2**: the e2e suite legitimately
  adds up to 2 fights of drift (the
  :func:`test_health_summary_surfaces_drift_after_summary_deletion`
  test deliberately deletes summary rows; a v0.8.4
  materialise regression would add ~1 more fight of
  drift per e2e test that creates a new fight, so the
  delta would be ~3-4). The budget of 2 is tight
  enough to catch a real regression without
  false-positiving the legitimate e2e drift.

Modes
-----

- ``--save-baseline PATH``: capture the current probe
  response to ``PATH`` as JSON. The CI workflow runs
  this BEFORE the e2e suite.
- ``--check-delta PATH``: compare the current probe
  response to the baseline at ``PATH``. The CI
  workflow runs this AFTER the e2e suite. Returns
  non-zero if the delta exceeds the budget.
- No flags: print the probe response and return 0
  (debug mode).

Exit codes
----------

- ``0``: gate passed (or saved baseline, or debug).
- ``1``: gate failed (delta exceeds budget).
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

# Maximum tolerated ``drift_count`` delta between the
# baseline and the post-e2e probe response. The e2e
# suite adds up to 2 fights of drift (the
# ``test_health_summary_surfaces_drift_after_summary_deletion``
# test deletes summary rows). A v0.8.4 materialise
# regression would add ~1 more fight of drift per e2e
# test that creates a new fight, so the delta would
# be ~3-4. The budget of 2 catches a real regression
# without false-positiving the legitimate e2e drift.
MAX_DRIFT_DELTA: Final[int] = 2


def _fetch_drift() -> SummaryDrift:
    """Hit /api/v1/health/summary via in-process TestClient.

    The :class:`SummaryDrift` TypedDict is the canonical
    response shape; this function returns the raw JSON
    so the caller can compare to the baseline without
    re-parsing the TypedDict. The
    :func:`test_health_summary_shape_contract` test in
    ``apps/api/tests/test_health_summary.py`` pins the
    shape contract.
    """
    client = TestClient(app)
    response = client.get("/api/v1/health/summary")
    response.raise_for_status()
    # ``response.json()`` is typed as ``Any`` by FastAPI;
    # we trust the :class:`SummaryDrift` annotation
    # because the
    # :func:`test_health_summary_shape_contract` test
    # pins the shape contract. ``cast`` is explicit (no
    # ``type: ignore`` comment to maintain).
    return cast(SummaryDrift, response.json())


def _save_baseline(path: str) -> int:
    """Capture the current probe response to ``path`` as JSON.

    The CI workflow runs this BEFORE the e2e suite so
    the baseline reflects the test DB state at the
    start of the suite (which is the legitimate
    "ground truth" against which the post-e2e drift is
    measured).
    """
    data = _fetch_drift()
    print(f"Health probe baseline: {data}")
    with Path(path).open("w") as f:
        json.dump(data, f)
    return 0


def _check_delta(path: str) -> int:
    """Compare the current probe response to the baseline at ``path``.

    The CI workflow runs this AFTER the e2e suite. The
    ``drift_count`` delta must be <= ``MAX_DRIFT_DELTA``;
    any larger delta is a signal that the v0.8.4
    materialise silently broke (the e2e suite
    legitimately adds up to 2 fights of drift).
    """
    data = _fetch_drift()
    print(f"Health probe post-e2e: {data}")

    with Path(path).open() as f:
        baseline = json.load(f)
    print(f"Health probe baseline: {baseline}")

    # JSON integers deserialize to Python ``int``, so the
    # ``int()`` casts are not strictly needed. They are
    # omitted because the
    # :class:`SummaryDrift` TypedDict pins the field
    # types at the boundary.
    delta = data["drift_count"] - baseline["drift_count"]
    # The ``>=`` is the off-by-one fix: the e2e suite
    # legitimately adds ``+1`` to ``drift_count`` (the
    # :func:`test_health_summary_surfaces_drift_after_summary_deletion`
    # test deletes summary rows). A v0.8.4 materialise
    # regression would add ``+1`` more (a second e2e
    # test that creates a fight without summaries), so
    # the regression delta is ``+2``. With ``> 2``, the
    # regression would pass (false negative); with
    # ``>= 2``, the regression correctly fails.
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


def main() -> int:
    """Run the CI gate; return 0 on pass, 1 on fail.

    The function is intentionally simple: dispatch on
    the optional CLI args, run the corresponding mode,
    return the exit code. The ``argparse`` plumbing is
    minimal -- the two modes are mutually exclusive
    (saving a baseline and checking a delta are
    separate CI steps).
    """
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
    )
    parser.add_argument(
        "--save-baseline",
        type=str,
        metavar="PATH",
        help=("Capture the current probe response to PATH as JSON (CI: run BEFORE the e2e suite)."),
    )
    parser.add_argument(
        "--check-delta",
        type=str,
        metavar="PATH",
        help=(
            "Compare the current probe response to the "
            "baseline at PATH (CI: run AFTER the e2e "
            "suite). Non-zero exit if the drift_count "
            "delta exceeds the budget."
        ),
    )
    args = parser.parse_args()

    if args.save_baseline:
        return _save_baseline(args.save_baseline)
    if args.check_delta:
        return _check_delta(args.check_delta)

    # No flags: debug mode.
    data = _fetch_drift()
    print(f"Health probe response: {data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
