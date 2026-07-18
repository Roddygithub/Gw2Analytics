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

v0.10.26-pre plan 170 extension: adds the failed-upload TTL cleanup
sweep that hard-deletes ``status = 'failed'`` rows older than
``STUCK_SWEEPER_FAILED_RETENTION_DAYS`` (default 90) with the
plan 160 ``Duplicate fight:`` error signature AND zero dependent
:class:`OrmFight` rows. Composes with the existing pending sweep
on the same iteration cadence.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gw2analytics_api.config import get_settings
from gw2analytics_api.metrics import (
    STUCK_SWEEPER_FAILED_SWEPT,
    STUCK_SWEEPER_ITERATION_DURATION,
    STUCK_SWEEPER_MARKED_FAILED,
    UPLOADS_PENDING_COUNT,
)
from gw2analytics_api.models import UPLOAD_STATUS_FAILED, OrmFight, Upload

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
            # v0.10.26-pre plan 170: failed-upload cleanup sweep.
            # Composes with the existing pending->failed promotion
            # in the SAME tick; the two sweeps are independent and
            # one slipping does not block the other (the iteration
            # duration is observed AFTER BOTH sweeps complete so
            # the operator sees the real wallclock cost).
            try:
                await asyncio.to_thread(
                    _sweep_failed_once,
                    session_factory,
                    settings.stuck_sweeper_failed_retention_days,
                )
            except SQLAlchemyError:
                logger.exception(
                    "failed-upload cleanup sweep tick failed; continuing to next interval"
                )
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


# v0.10.26-pre plan 170: failed-row TTL cleanup helper.
#
# Composes with :func:`_sweep_once` -- both run on the same iteration
# cadence (``STUCK_SWEEPER_INTERVAL_S``). The promotion sweep above
# flips stale ``pending`` -> ``failed``; this sweep hard-deletes
# ``failed`` rows that have aged past the retention window AND have
# zero dependent :class:`OrmFight` rows. Hard DELETE is safe because
# the :class:`OrmFight` FK ``ondelete="CASCADE"`` would otherwise
# orphan fight data: the cascade chain is 4 levels deep
# (Upload -> OrmFight -> OrmFightAgent / OrmFightSkill /
# OrmFightPlayerSummary), so a naive sweep would silently destroy
# analytical summary data for a failure I do not know is real vs
# transient. The ``NOT EXISTS`` subquery pre-excludes rows with
# dependent fights BEFORE the DELETE, so the FK CASCADE is never
# exercised by this sweep.
#
# Why scope to ``error_message LIKE 'Duplicate fight:%'``
# =======================================================
# plan 160 IDs the upload-fight_id collision path as the dominant
# source of redundant rows: a re-submitted .zevtc with a sha256
# different from the canonical fight (the original parse failed or
# was rolled back) creates a new upload row. The idempotency layer
# on the upload route marks the new upload ``failed`` with
# ``Duplicate fight: <canonical_fight_id>``. These rows are create
# only dross -- there is no fight data to retain -- and accumulate
# forever because the existing sweep only handles ``pending``
# (parking-lot rows). Sweeping ONLY the ``Duplicate`` signature
# avoids accidentally deleting rows the operator might want to
# inspect (network errors, parser crashes, parse-then-resubmit
# flows that DID land a fight row).
#
# TOCTOU-safe single statement
# ===========================
# The SELECT-with-NOT-EXISTS is folded into the DELETE's WHERE
# clause so Postgres re-evaluates the correlated NOT EXISTS at
# DELETE-plan time. The 2-statement SELECT-then-DELETE pattern has
# a TOCTOU window: a client inserting an OrmFight referencing one
# of the candidate uploads between T1 (SELECT) and T2 (DELETE)
# would hit the FK CASCADE unintentionally and orphan that new
# fight row. The fold closes the window because Postgres plans the
# DELETE-with-IN-subquery as a single anti-join over the FK index
# -- the dependent check is re-applied per outer row at plan time.
_BATCH_DELETE_SIZE = 1000


def _sweep_failed_once(
    session_factory: Callable[[], Session],
    retention_days: int,
) -> int:
    """One failed-upload cleanup iteration. DB-blocking; called via
    ``asyncio.to_thread`` from :func:`lifespan_stuck_upload_sweeper`.

    Hard-deletes :class:`Upload` rows that satisfy:

    - ``status == 'failed'`` (already promoted by :func:`_sweep_once`
      or set by the upload route on a parse failure)
    - ``uploaded_at < NOW() - retention_days`` (default 90 days)
    - ``error_message LIKE 'Duplicate fight:%'`` (strictly scoped
      per plan 170 to the plan 160 idempotency collision path;
      avoids squashing actionable failure modes like parse errors
      or network blips that the operator might want to inspect)
    - ``NOT EXISTS (SELECT 1 FROM fights WHERE fights.upload_id =
      uploads.id)`` -- the safety guard on the FK CASCADE; pre
      queries the dependent-fight existence so the DELETE bypasses
      any row whose cascade would orphan analytical summary data

    Returns the number of rows deleted. Idempotent on re-run.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)

    with session_factory() as session:
        delete_result = session.execute(
            delete(Upload).where(
                Upload.id.in_(
                    select(Upload.id)
                    .where(
                        Upload.status == UPLOAD_STATUS_FAILED,
                        Upload.uploaded_at < cutoff,
                        Upload.error_message.like("Duplicate fight:%"),
                        ~select(OrmFight.id)
                        .where(OrmFight.upload_id == Upload.id)
                        .exists(),
                    )
                    .limit(_BATCH_DELETE_SIZE)
                )
            )
        )
        deleted_count: int = delete_result.rowcount  # type: ignore[attr-defined]
        session.commit()

        if deleted_count:
            STUCK_SWEEPER_FAILED_SWEPT.inc(deleted_count)
            logger.info(
                "failed-upload cleanup sweep hard-deleted %d row(s)",
                deleted_count,
            )

        return deleted_count
