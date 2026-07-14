"""v0.10.12 plan 017 close-out: tests for the new health + sweeper metrics.

Covers:
- ``HEALTH_DRIFT_COUNT`` is set by :func:`gw2analytics_api.routes.health.get_health_summary`
- ``HEALTH_DRIFT_COUNT`` gauges to 0 when ``drift_count`` is 0
- :func:`gw2analytics_api.workers.stuck_upload_sweeper._sweep_once`
  sets the ``UPLOADS_PENDING_COUNT`` gauge post-commit + increments
  ``STUCK_SWEEPER_MARKED_FAILED`` by rowcount
- :func:`gw2analytics_api.workers.stuck_upload_sweeper.lifespan_stuck_upload_sweeper`
  observes the iteration wallclock on the
  ``STUCK_SWEEPER_ITERATION_DURATION`` histogram

We intentionally do NOT unit-test the
``GET /api/v1/metrics`` endpoint here. That endpoint is a 4-line
mounting wrapper around :func:`prometheus_client.generate_latest`
and its production wiring is covered end-to-end by the manual
smoke CLI in :file:`apps/api/src/gw2analytics_api/scripts/metrics_smoke.py`.
A unit test that builds a standalone ``FastAPI()`` instance +
duplicates the route handler validates the library, not our code,
and would silently rot if the wired route diverges from the
standalone copy.

Tests that pass a mocked ``Session`` through the sweeper use the
``@contextmanager`` decorator as the session factory: this is the
canonical idiom because the production
:func:`_sweep_once` body opens the session via
``with session_factory() as session:``, and a ``MagicMock`` factory
loses its ``.execute.side_effect`` configuration to ``__enter__()``'s
default mock rebinding. ``@contextmanager fake_factory(): yield session``
keeps the configured reference intact across the context boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from itertools import cycle
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session

from gw2analytics_api.routes.health import get_health_summary
from gw2analytics_api.workers.stuck_upload_sweeper import (
    _sweep_once,
    lifespan_stuck_upload_sweeper,
)


def _sample_value(metric_name: str) -> float:
    """Return the current value of an UNLABELED metric from the global registry.

    The 4 new plan-017 metrics have no labels — they are gauges /
    counters keyed on a single dimension (drift_count, pending
    count, marked_failed total). ``prometheus_client`` exposes
    them as samples with an empty labels dict.
    """
    return REGISTRY.get_sample_value(metric_name, {}) or 0.0


def test_health_drift_count_set_after_route_call() -> None:
    """``HEALTH_DRIFT_COUNT`` reflects the latest drift_count after probe."""
    with patch("gw2analytics_api.routes.health.summary_drift") as fake_drift:
        fake_drift.return_value = {
            "total_fights": 100,
            "fights_with_summaries": 95,
            "drift_count": 5,
            "drift_pct": 5.0,
            "status": "drift",
        }

        get_health_summary(db=MagicMock())

    assert _sample_value("health_drift_count") == 5.0


def test_health_drift_count_set_to_zero_on_clean_database() -> None:
    """``HEALTH_DRIFT_COUNT`` gauges correctly to 0 when drift_count is 0.

    The empty-DB path is a known case (``SELECT COUNT(*) FROM fights``
    returns 0; ``drift_pct = 0.0``) and operators must NOT see the
    gauge stuck at a non-zero leftover from a prior probe.
    """
    with patch("gw2analytics_api.routes.health.summary_drift") as fake_drift:
        fake_drift.return_value = {
            "total_fights": 0,
            "fights_with_summaries": 0,
            "drift_count": 0,
            "drift_pct": 0.0,
            "status": "ok",
        }

        get_health_summary(db=MagicMock())

    assert _sample_value("health_drift_count") == 0.0


def test_sweep_once_updates_pending_gauge_and_failure_counter() -> None:
    """``_sweep_once`` queries COUNT(pending) post-commit + sets gauge + counter.

    Uses an ``@contextmanager`` factory so the configured ``session``
    reference (with ``.execute.side_effect`` set) is the SAME object
    yielded inside the ``with session_factory() as session:`` block
    of :func:`_sweep_once` — a ``MagicMock`` factory alone would lose
    the side-effect config to ``__enter__()``'s default mock rebind.
    """
    session = MagicMock()
    update_result = MagicMock(spec=Result, rowcount=2)
    count_result = MagicMock(spec=Result)
    count_result.scalar_one.return_value = 7
    # ``cycle`` avoids the ``StopIteration`` that a finite list would
    # trigger if a future code-path calls ``session.execute`` more
    # than twice per :func:`_sweep_once` invocation.
    session.execute.side_effect = cycle([update_result, count_result])

    @contextmanager
    def fake_session_factory() -> Generator[Session, None, None]:
        yield session

    marked_before = _sample_value("stuck_sweeper_marked_failed_total")

    _sweep_once(
        session_factory=fake_session_factory,  # type: ignore[arg-type]
        threshold_s=300,
    )

    marked_after = _sample_value("stuck_sweeper_marked_failed_total")
    pending_after = _sample_value("uploads_pending_count")

    # Counter increments by EXACTLY rowcount regardless of prior state.
    assert (marked_after - marked_before) == 2.0
    # Gauge is set to EXACTLY the post-sweep count (overwrites, not delta).
    assert pending_after == 7.0


@pytest.mark.asyncio
async def test_stuck_sweeper_iteration_duration_observed() -> None:
    """Each iteration observes a duration on the histogram (success path).

    Iterates the lifespan once via :func:`fake_sleep` raising
    :class:`asyncio.CancelledError` after the FIRST ``sleep`` call,
    so the test terminates deterministically. ``session.execute``
    uses :func:`itertools.cycle` so the 3rd+ ``session.execute`` calls
    (across multi-iteration lifespans) don't raise ``StopIteration``.
    The ``@contextmanager`` factory keeps the configured mock's
    ``.execute.side_effect`` intact across the lifespan's
    ``with session_factory() as session:`` block.
    """
    session = MagicMock()
    update_result = MagicMock(spec=Result, rowcount=0)
    count_result = MagicMock(spec=Result)
    count_result.scalar_one.return_value = 0
    session.execute.side_effect = cycle([update_result, count_result])

    @contextmanager
    def fake_session_factory() -> Generator[Session, None, None]:
        yield session

    before_count = _sample_value("stuck_sweeper_iteration_duration_seconds_count")
    before_sum = _sample_value("stuck_sweeper_iteration_duration_seconds_sum")

    sleep_call_count = 0

    async def fake_sleep(_s: float) -> None:
        nonlocal sleep_call_count
        sleep_call_count += 1
        if sleep_call_count >= 1:
            raise asyncio.CancelledError

    with (
        patch("gw2analytics_api.workers.stuck_upload_sweeper.asyncio.sleep", fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await lifespan_stuck_upload_sweeper(
            session_factory=fake_session_factory,  # type: ignore[arg-type]
        )

    after_count = _sample_value("stuck_sweeper_iteration_duration_seconds_count")
    after_sum = _sample_value("stuck_sweeper_iteration_duration_seconds_sum")

    # Histogram count incremented by AT LEAST 1 (the fake_sleep raised
    # after the first observe). The first iteration succeeded AND
    # observed before the cancelled sleep raised.
    assert after_count >= before_count + 1
    # Sum strictly increased (the observed value is real
    # ``time.monotonic()`` deltas — assert loose lower bound).
    assert after_sum >= before_sum
