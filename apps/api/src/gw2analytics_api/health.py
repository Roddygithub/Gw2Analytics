"""v0.8.6: operational health probes for the GW2Analytics API.

The :mod:`services` module wraps the per-(fight, account)
summary materialisation in a narrow ``except SQLAlchemyError``
(best-effort: a failure degrades to the slow-path fallback).
The :mod:`backfill` module catches ``(S3Error, OSError,
SQLAlchemyError, ValidationError)`` per fight (so a single
bad fight does not abort the whole backfill). Both patterns
silently swallow errors -- the production behavior is
correct (the slow-path fallback serves the data; the
backfill is re-runnable), but an operator has no easy way
to detect when the fast-path is degraded for production
users.

This module closes the observability gap with a single
SQL query that returns the drift between the total fight
count and the fights-with-summary count. The probe is
exposed at ``GET /api/v1/health/summary`` (see
:mod:`gw2analytics_api.routes.health`) and is the
integration point for the operational cron that runs
the backfill (a non-zero ``drift_count`` after a backfill
run signals a failure that needs investigation).

The probe is intentionally cheap: a single round-trip
with 2 subqueries, each scanning a small index
(``fights`` PK + ``fight_player_summaries`` PK). The
response is a small JSON object -- safe to poll every
minute from a monitoring system.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session


class SummaryDrift(TypedDict):
    """The shape of the ``GET /api/v1/health/summary`` response.

    Attributes
    ----------
    total_fights:
        The total number of ``OrmFight`` rows in the database.
    fights_with_summaries:
        The number of distinct ``fight_id`` values that have
        at least one ``OrmFightPlayerSummary`` row. The
        ``DISTINCT`` is necessary because a single fight can
        have multiple summary rows (one per
        ``(fight_id, account_name)`` pair).
    drift_count:
        ``total_fights - fights_with_summaries`` -- the number
        of fights whose summary rows are missing.
    drift_pct:
        ``drift_count / total_fights * 100`` as a float, or
        ``0.0`` if ``total_fights == 0`` (avoids a
        ``ZeroDivisionError`` on an empty database). The
        ``round(..., 2)`` keeps the response small + stable
        for monitoring diffs.
    status:
        The qualitative health state. ``"ok"`` when
        ``drift_count == 0`` (no missing summary rows) and
        ``"drift"`` otherwise. The cron integration can
        branch on this field instead of computing its own
        threshold from the raw numbers.
    """

    total_fights: int
    fights_with_summaries: int
    drift_count: int
    drift_pct: float
    status: Literal["ok", "drift"]


def summary_drift(db: Session) -> SummaryDrift:
    """Return the fight-summary drift for the operational health probe.

    Single round-trip: 2 subqueries in one ``SELECT``. The
    query planner can satisfy each subquery independently
    (the ``fights`` PK index + the
    ``fight_player_summaries`` PK index), so the cost is
    O(1) page fetches per subquery, regardless of the
    dataset size.

    Returns
    -------
    A :class:`SummaryDrift` dict with the 4 fields described
    on the class. The ``drift_pct`` is rounded to 2 decimal
    places for stable monitoring diffs.
    """
    # The 2 subqueries are aliased columns of a single-row,
    # single-SELECT -- the query planner can run them in
    # parallel and the network cost is 1 round-trip. Using
    # ``text()`` is intentional: the query is a single
    # hand-written scalar SELECT (no parameters, no
    # SQLAlchemy ORM overhead) and the wire format is the
    # same whether it's a Python ``int`` or a Python
    # ``Decimal`` (psycopg returns ``int`` for ``COUNT(*)``).
    row = db.execute(
        text(
            "SELECT "
            "(SELECT COUNT(*) FROM fights) AS total_fights, "
            "(SELECT COUNT(DISTINCT fight_id) FROM fight_player_summaries) "
            "AS fights_with_summaries"
        )
    ).one()
    total_fights = int(row.total_fights)
    fights_with_summaries = int(row.fights_with_summaries)
    drift_count = total_fights - fights_with_summaries
    drift_pct = round(drift_count / total_fights * 100, 2) if total_fights > 0 else 0.0
    # The ``status`` field is a qualitative summary that
    # operators can branch on without computing their own
    # threshold from the raw numbers. Binary ``ok`` vs
    # ``drift`` is the cleanest contract: any non-zero
    # ``drift_count`` after a backfill run is a signal
    # that a per-fight failure needs investigation. A more
    # granular status (``ok`` / ``degraded`` / ``critical``
    # based on ``drift_pct`` thresholds) could be added
    # later if operators ask for it.
    status: Literal["ok", "drift"] = "ok" if drift_count == 0 else "drift"
    return SummaryDrift(
        total_fights=total_fights,
        fights_with_summaries=fights_with_summaries,
        drift_count=drift_count,
        drift_pct=drift_pct,
        status=status,
    )


__all__ = ["SummaryDrift", "summary_drift"]
