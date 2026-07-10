"""v0.10.0 plan 032: cross-account timeline ``GET`` route.

Mirrors the v0.8.0 per-account timeline route contract for N
accounts simultaneously. The Squad-comparison use case (e.g.
"how does my DPS compare to my healer's damage absorbed over the
same fight window?") is the maintainer's most-requested feature
in the incident log (per ``docs/ROADMAP.md`` §1).

Design rationale
================

Route shape is ``GET /api/v1/players/compare/timeline`` with a
**repeatable** ``accounts`` query param (``?accounts=A&accounts=B``
... up to 4 -- the chart's readability degrades past 4 lines on
a 1440-wide viewport). This shape was preferred over the spec's
literal "comma-joined path" because FastAPI's ``:path`` converter
does NOT split on commas -- a path of ``/players/A,B/timeline``
would hand the handler a single ``account_name="A,B"`` string,
requiring manual split + re-validation. Query params are the
canonical "list of N items" REST shape; the URL surface stays
clean (the spec is still readable as ``/compare/timeline?accounts=A,B``
URL-encoded).

Declaration order matters
-------------------------

This route MUST be declared BEFORE the catch-all
``get_player`` route's path ``{account_name:path}``. FastAPI
matches routes in declaration order; if the catch-all is
declared first, ``/api/v1/players/compare/timeline`` would
greedily match ``/{account_name:path}`` with
``account_name="compare/timeline"`` and return 404 from the
detail route before this route ever fires.

Per-account semantics preserved
-------------------------------

The route reuses ``apps.api.routes.players._compute_contributions``
(the same helper the list + detail + per-account timeline routes
use) so the compute path converges on the same output shape. The
``?bucket=`` and ``?tz=`` params match the per-account timeline
exactly (an analyst reading this route after the per-account
timeline sees the same wire surface -- only the response shape
changes).

404 vs empty
------------

The per-account timeline route returns ``404 Not Found`` when
the requested account has no contributions. The cross-account
route intentionally deviates: an analyst requesting an account
with no attended fights gets a per-account series with
``points: []`` (matches the ``OrmFightPlayerSummary`` empty-row
contract). A fully-unknown account is a 422 (the ``accounts=``
query param has a min-length-1 validator; an unknown account is
NOT treated as a 404 because the response shape "succeeds with
empty data" is more useful for the analyst UX than a 404).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.cross_account_timeline import (
    CrossAccountTimelineAggregator,
    CrossAccountTimelineSeries,
)
from gw2_analytics.player_profile import FightContribution
from gw2analytics_api.database import get_session
from gw2analytics_api.models import OrmFight
from gw2analytics_api.routes.players import _compute_contributions

router = APIRouter(prefix="/api/v1/players", tags=["players"])


def _group_contributions_by_account(
    contributions: Iterable[FightContribution],
    requested_accounts: Iterable[str],
) -> dict[str, list[FightContribution]]:
    """Group contributions by account, pre-seeded with the requested accounts.

    The dict is seeded with one empty list per requested account so
    :class:`CrossAccountTimelineAggregator` (which emits one series per
    dict KEY) yields exactly one series per requested account -- an
    account with no contributions still gets a series with empty
    ``points``. Contributions whose ``account_name`` was not requested
    are dropped. Pre-seeding also makes the append safe: a plain
    ``dict[...] = {}`` with an unconditional ``d[k].append`` raises
    ``KeyError`` on the first contribution (the v0.10.0 plan 032 defect
    this helper replaces).
    """
    grouped: dict[str, list[FightContribution]] = {account: [] for account in requested_accounts}
    for c in contributions:
        bucket = grouped.get(c.account_name)
        if bucket is not None:
            bucket.append(c)
    return grouped


# Maximum accounts per compare request. The chart's readability
# degrades past 4 lines on the visual-regression viewport
# (1440x900) so the route enforces ``[2, 4]`` as a hard limit.
# Enforced via ``Query(..., min_length=2, max_length=4)`` so
# FastAPI returns 422 automatically on out-of-range requests.
_MAX_ACCOUNTS_PER_COMPARE = 4


@router.get("/compare/timeline", response_model=list[CrossAccountTimelineSeries])
def get_compare_timeline(
    accounts: list[str] = Query(  # noqa: B008 - FastAPI dependency
        ...,
        min_length=2,
        max_length=_MAX_ACCOUNTS_PER_COMPARE,
        description=(
            "Repeatable query param: ``?accounts=A&accounts=B`` (up to 4). "
            "The route emits one per-account series in the response. "
            "An account with no attended fights is reported as a series "
            "with ``points: []`` (NOT a 404 -- the analyst UX benefits "
            "from a same-shape response for all requested accounts)."
        ),
    ),
    bucket: Literal["fight", "day"] = Query(
        "fight",
        description=(
            "Same semantics as the per-account timeline route: ``fight`` "
            "(default -- one point per attended fight) vs ``day`` (one "
            "point per UTC calendar day, totals summed across the day's "
            "fights; ``started_at`` is day-midnight in the requested TZ)."
        ),
    ),
    tz: str = Query(
        "UTC",
        description=(
            "Same semantics as the per-account timeline route: the "
            "day-bucketing TZ (IANA name). Invalid names return 422 "
            "(canonical FastAPI query-param validation contract). The "
            "``fight`` bucketing mode is unaffected by ``tz``."
        ),
    ),
    db: Session = Depends(get_session),  # noqa: B008
) -> list[CrossAccountTimelineSeries]:
    """Return one per-account series per requested account.

    Iterates :func:`apps.api.routes.players._compute_contributions`
    once per request (the helper does ONE cross-fight roll-up
    over ALL fights, then filters per-account in-memory). The
    cross-account response shape is a list of series; each
    series carries the same ``points`` shape as the per-account
    timeline (so a future v0.11.0 client could reuse the chart
    component without forking the per-account canvas).
    """
    # Deduplicate the input ``accounts`` list so a request with
    # ``?accounts=A&accounts=A&accounts=B`` emits ONE series for
    # ``A`` (not two). Preserves first-seen order so the analyst
    # sees their requested order on the chart, not the
    # de-dup-discovered order.
    seen: set[str] = set()
    deduped_accounts: list[str] = []
    for acct in accounts:
        if acct not in seen:
            seen.add(acct)
            deduped_accounts.append(acct)
    if len(deduped_accounts) < 2:
        # The ``Query(..., min_length=2)`` validator already returns
        # 422 on len < 2 raw; this guard handles the POST-de-dup
        # case where the request had duplicates that all reduce to
        # < 2 unique accounts.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"compare requires at least 2 unique accounts (got "
            f"{len(deduped_accounts)} after de-duplication)",
        )
    # Parse the ``?tz=`` string into a :class:`ZoneInfo` AFTER
    # the dedupe step so the 422 ordering matches the per-account
    # timeline's contract (resource first, query param second).
    # ``ZoneInfoNotFoundError`` is the canonical exception for an
    # unknown IANA name; we surface it as 422 to match FastAPI's
    # Query-validation convention.
    try:
        parsed_tz: ZoneInfo = ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown IANA timezone: {tz!r}",
        ) from exc
    fights = (
        db.execute(
            select(OrmFight)
            .order_by(OrmFight.started_at.desc())
            .options(selectinload(OrmFight.agents)),
        )
        .scalars()
        .all()
    )
    contributions = _compute_contributions(db, fights)
    # Bucket per-account contributions, pre-seeded with the requested
    # (deduped) accounts so every requested account gets a series and
    # an account with NO contributions still gets an empty-``points``
    # series (the "all requested accounts -> all series" contract).
    per_account_contributions = _group_contributions_by_account(contributions, deduped_accounts)
    # ``fight_id_to_started`` mirrors the per-account timeline
    # route's lookup table. The ``.get(fight_id, fight_id)``
    # fallback is the same defensive guard.
    fight_id_to_started = {f.id: f.started_at for f in fights}
    return CrossAccountTimelineAggregator().aggregate(
        per_account_contributions=per_account_contributions,
        fight_id_to_started=fight_id_to_started,
        bucket=bucket,
        tz=parsed_tz,
    )


__all__ = ["get_compare_timeline", "router"]
