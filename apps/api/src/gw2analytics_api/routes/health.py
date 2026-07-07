"""v0.8.6: operational health probe routes.

The :func:`summary_drift` probe surfaces the
``OrmFightPlayerSummary`` population drift so an operator
can detect when the fast-path is degraded to the
slow-path fallback (the best-effort ``except
SQLAlchemyError`` in :mod:`services` + the per-fight
catch in :mod:`backfill` silently swallow errors). The
probe is the integration point for the operational cron
that runs the backfill: a non-zero ``drift_count`` after
a backfill run signals a failure that needs
investigation.

The endpoint is intentionally unauthenticated (matches
the existing ``/healthz`` liveness check pattern) so
external monitoring systems can poll it without
credentials. The response is a small JSON object -- safe
to poll every minute from a monitoring system.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from gw2analytics_api.database import get_session
from gw2analytics_api.health import SummaryDrift, summary_drift

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/summary")
def get_health_summary(db: Session = Depends(get_session)) -> SummaryDrift:  # noqa: B008
    """Return the fight-summary drift for the operational health probe.

    Response shape::

        {
            "total_fights": 100,
            "fights_with_summaries": 95,
            "drift_count": 5,
            "drift_pct": 5.0,
            "status": "drift"
        }

    - ``total_fights``: the total number of ``OrmFight`` rows.
    - ``fights_with_summaries``: the number of distinct
      ``fight_id`` values that have at least one
      ``OrmFightPlayerSummary`` row.
    - ``drift_count``: ``total_fights - fights_with_summaries``,
      the number of fights whose summary rows are missing.
      Zero is the healthy state.
    - ``drift_pct``: ``drift_count / total_facts * 100`` as a
      float rounded to 2 decimal places, or ``0.0`` on an
      empty database.
    - ``status``: ``"ok"`` when ``drift_count == 0``,
      ``"drift"`` otherwise. The cron integration can
      branch on this field without computing its own
      threshold.

    The probe is a single SQL round-trip with 2 subqueries;
    it is safe to poll from a monitoring system at a high
    cadence (the query plan uses the ``fights`` PK index
    + the ``fight_player_summaries`` PK index).
    """
    return summary_drift(db)


__all__ = ["router"]
