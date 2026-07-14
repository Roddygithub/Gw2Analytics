"""Stuck-upload sweeper: marks stale pending uploads as failed (plan 014).

If the arq worker process dies mid-parse, the corresponding
``uploads.status = 'pending'`` row can stay pending indefinitely.
This lifespan task polls for stale pending rows and marks them
as ``failed`` so the operator is not silently surprised by
dangling DB rows.

Lifecycle
---------

Runs as a background asyncio task started by
:mod:`gw2analytics_api.main`'s ``lifespan`` handler. Configurable
via ``STUCK_SWEEPER_INTERVAL_S`` (poll interval, default 300s) and
``STUCK_SWEEPER_THRESHOLD_S`` (staleness threshold, default 300s).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gw2analytics_api.config import get_settings
from gw2analytics_api.metrics import (
    STUCK_SWEEPER_ITERATION_DURATION,
    STUCK_SWEEPER_MARKED_FAILED,
    UPLOADS_PENDING_COUNT,
)
from gw2analytics_api.models import UPLOAD_STATUS_FAILED, Upload

logger = logging.getLogger(__name__)


async def lifespan_stuck_upload_sweeper(
    session_factory: Callable[[], Session],
) -> None:
    """Background task: sweep stale pending uploads.

    Every ``stuck_sweeper_interval_s`` seconds, query uploads where
    ``status='pending'`` and ``created_at`` is older than
    ``stuck_sweeper_threshold_s`` seconds. Mark them as ``failed``
    with an explanatory error message.

    Crash-loop resilience: the per-iteration ``try/except`` catches
    transient DB errors and continues to the next interval.
    """
    settings = get_settings()
    interval_s = settings.stuck_sweeper_interval_s
    threshold_s = settings.stuck_sweeper_threshold_s

    logger.info(
        "stuck-upload sweeper starting (interval: %ds, threshold: %ds)",
        interval_s,
        threshold_s,
    )

    try:
        while True:
            # Plan 017 close-out: instrument the iteration
            # wallclock. Measure BEFORE the work so a stuck SQL
            # query is captured (failures are still observed,
            # the per-row counter attribution is skipped when
            # the sweep raises).
            iteration_start = time.monotonic()
            try:
                await asyncio.to_thread(
                    _sweep_once,
                    session_factory,
                    threshold_s,
                )
            except SQLAlchemyError:
                logger.exception("stuck-upload sweeper tick failed; continuing to next interval")
            STUCK_SWEEPER_ITERATION_DURATION.observe(time.monotonic() - iteration_start)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        logger.info("stuck-upload sweeper cancelled; shutting down cleanly")
        raise


def _sweep_once(
    session_factory: Callable[[], Session],
    threshold_s: int,
) -> int:
    """One sweep iteration. DB-blocking; called via ``asyncio.to_thread``.

    Returns the number of rows marked as failed.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=threshold_s)
    error_msg = (
        f"stuck-pending-sweeper: no completion signal within "
        f"{threshold_s}s (worker died or Redis lost the job)"
    )

    with session_factory() as session:
        stmt = (
            update(Upload)
            .where(
                Upload.status == "pending",
                Upload.uploaded_at < cutoff,
            )
            .values(
                status=UPLOAD_STATUS_FAILED,
                error_message=error_msg,
            )
        )
        result = session.execute(stmt)
        rowcount: int = result.rowcount  # type: ignore[attr-defined]
        session.commit()

        if rowcount:
            # Plan 017 close-out: increment the marked-failed
            # counter by the rowcount (per-row attribution is
            # summed by the Counter contract; the operator can
            # diff before/after a sweep to confirm pick-up).
            STUCK_SWEEPER_MARKED_FAILED.inc(rowcount)
            logger.warning(
                "stuck-upload sweeper marked %d row(s) as failed",
                rowcount,
            )

        # Plan 017 close-out: refresh the pending-upload gauge
        # AFTER the sweep UPDATE has committed (the .commit()
        # above releases the transaction lock so the SELECT
        # COUNT(*) sees a consistent snapshot). One cheap
        # index-only COUNT per sweep iteration (interval_s
        # cadence, default 300s). Lets operators alert on
        # `uploads_pending_count > 0` to detect a sweeper
        # that's silently broken.
        pending_after = session.execute(
            select(func.count()).select_from(Upload).where(Upload.status == "pending")
        ).scalar_one()
        UPLOADS_PENDING_COUNT.set(int(pending_after))

        return rowcount
