"""``/api/v1/players`` endpoints (thin route layer).

Phase 2.3: all business logic is extracted into
:mod:`gw2analytics_api.services.player_service` and
:mod:`gw2analytics_api.route_helpers`. This file only
declares the FastAPI routes and formats the responses.

Endpoints
---------
- GET  ``/api/v1/players`` — cross-fight player roll-up
- GET  ``/api/v1/players/{account_name}/timeline`` — per-account timeline
- GET  ``/api/v1/players/{account_name}`` — full profile + fight breakdown
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from gw2_analytics.player_profile import PlayerProfile
from gw2_analytics.role_detection import detect_role_lite
from gw2analytics_api.database import get_session
from gw2analytics_api.limiter import limiter
from gw2analytics_api.route_helpers import (
    format_elite_label,
    format_profession_label,
    parse_profession_filter,
    profile_to_list_row,
)
from gw2analytics_api.schemas import (
    PerFightBreakdownRowOut,
    PlayerListRowOut,
    PlayerProfileOut,
    PlayerTimelineOut,
    PlayerTimelinePointOut,
)
from gw2analytics_api.services.player_profiles import (
    aggregate_player_profiles_cursor,
    aggregate_player_profiles_from_sql,
)
from gw2analytics_api.services.player_service import (
    DayTotals,
    combine_day_midnight,
    load_merged_contributions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/players", tags=["players"])


@router.get("", response_model=list[PlayerListRowOut])
@limiter.limit("30/minute")
def list_players(
    request: Request,  # noqa: ARG001
    response: Response,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(
        None,
        description=(
            "Cursor for keyset pagination (base64-encoded JSON with "
            "``last_damage`` and ``last_account``). When provided, "
            "``offset`` is ignored and cursor-based navigation is used. "
            "The next cursor is returned as the ``X-Next-Cursor`` response header."
        ),
    ),
    profession: str = Query(
        "",
        description=(
            "Filter to players whose modal profession matches the enum name "
            "(e.g. ?profession=MESMER) or integer value (e.g. ?profession=7). "
            "Default (empty) returns all players."
        ),
    ),
    db: Session = Depends(get_session),  # noqa: B008
) -> list[PlayerListRowOut]:
    """Return up to ``limit`` players.

    Phase 4.4: supports cursor-based keyset pagination via the
    ``cursor`` query parameter (base64-encoded JSON). When a cursor
    is provided the legacy ``offset`` is ignored. The next-page cursor
    is returned as the ``X-Next-Cursor`` response header.
    """
    parsed_profession = parse_profession_filter(profession)

    if cursor:
        profiles, next_cursor = aggregate_player_profiles_cursor(
            db,
            limit=limit,
            cursor=cursor,
            profession_filter=parsed_profession,
        )
        if next_cursor:
            response.headers["X-Next-Cursor"] = next_cursor
        return [profile_to_list_row(p) for p in profiles]

    profiles = aggregate_player_profiles_from_sql(
        db,
        limit=limit,
        offset=offset,
        profession_filter=parsed_profession,
    )
    return [profile_to_list_row(p) for p in profiles]


@router.get("/{account_name:path}/timeline", response_model=PlayerTimelineOut)
def get_player_timeline(
    account_name: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    bucket: Literal["fight", "day"] = Query("fight"),
    tz: str = Query("UTC"),
    db: Session = Depends(get_session),  # noqa: B008
) -> PlayerTimelineOut:
    """Return the per-fight historical timeline for one account.

    Sort order is recency-first (``started_at DESC``). The
    ``?bucket=day`` mode collapses all fights sharing a calendar
    day into one summed point. The ``?tz=`` query param selects
    the TZ for day-bucketing (default UTC).
    """
    bare_account_name = account_name.lstrip(":")
    own_contributions, fight_id_to_started = load_merged_contributions(
        db,
        account_name=bare_account_name,
    )

    if not own_contributions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    account_name = bare_account_name

    try:
        parsed_tz: ZoneInfo = ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown IANA timezone: {tz!r}",
        ) from exc

    sorted_contributions = own_contributions

    if bucket == "day":
        day_totals: dict[str, DayTotals] = defaultdict(DayTotals)
        day_first_fight: dict[str, str] = {}
        day_first_started: dict[str, Any] = {}
        for c in sorted_contributions:
            started_at = fight_id_to_started[c.fight_id]
            aware_utc = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
            day_key = aware_utc.astimezone(parsed_tz).date().isoformat()
            day_first_fight.setdefault(day_key, c.fight_id)
            day_first_started.setdefault(day_key, started_at)
            totals = day_totals[day_key]
            totals.damage += c.total_damage
            totals.healing += c.total_healing
            totals.strip += c.total_buff_removal
        all_points = [
            PlayerTimelinePointOut(
                fight_id=day_first_fight[day_key],
                started_at=combine_day_midnight(day_first_started[day_key], parsed_tz),
                total_damage=day_totals[day_key].damage,
                total_healing=day_totals[day_key].healing,
                total_buff_removal=day_totals[day_key].strip,
            )
            for day_key in day_totals
        ]
    else:
        all_points = [
            PlayerTimelinePointOut(
                fight_id=c.fight_id,
                started_at=fight_id_to_started[c.fight_id],
                total_damage=c.total_damage,
                total_healing=c.total_healing,
                total_buff_removal=c.total_buff_removal,
            )
            for c in sorted_contributions
        ]

    page = all_points[offset : offset + limit]
    return PlayerTimelineOut(
        account_name=account_name,
        total=len(all_points),
        limit=limit,
        offset=offset,
        bucket=bucket,
        tz=tz,
        points=page,
    )


@router.get("/{account_name:path}", response_model=PlayerProfileOut)
def get_player(
    account_name: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> PlayerProfileOut:
    """Return the full profile + per-fight breakdown for one account.

    Raises 404 when no agent carries the requested ``account_name``.
    """
    bare_account_name = account_name.lstrip(":")
    own_contributions, fight_id_to_started = load_merged_contributions(
        db,
        account_name=bare_account_name,
    )

    if not own_contributions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")

    account_name = bare_account_name
    first = own_contributions[0]

    profile = PlayerProfile(
        account_name=account_name,
        name=first.name,
        profession=first.profession,
        elite=first.elite,
        fights_attended=len(own_contributions),
        total_damage=sum(c.total_damage for c in own_contributions),
        total_healing=sum(c.total_healing for c in own_contributions),
        total_buff_removal=sum(c.total_buff_removal for c in own_contributions),
        attended_fight_ids=sorted(c.fight_id for c in own_contributions),
    )

    detected_role, detected_tags = detect_role_lite(
        total_damage=profile.total_damage,
        total_healing=profile.total_healing,
        total_buff_removal=profile.total_buff_removal,
        profession_int=int(profile.profession),
        elite_spec_int=int(profile.elite),
    )

    return PlayerProfileOut(
        account_name=profile.account_name,
        name=profile.name,
        profession=format_profession_label(profile.profession),
        elite_spec=format_elite_label(profile.elite),
        fights_attended=profile.fights_attended,
        total_damage=profile.total_damage,
        total_healing=profile.total_healing,
        total_buff_removal=profile.total_buff_removal,
        detected_role=detected_role,
        detected_tags=detected_tags,
        attended_fight_ids=profile.attended_fight_ids,
        per_fight_breakdown=[
            PerFightBreakdownRowOut(
                fight_id=c.fight_id,
                started_at=fight_id_to_started[c.fight_id],
                total_damage=c.total_damage,
                total_healing=c.total_healing,
                total_buff_removal=c.total_buff_removal,
                detected_role=c.detected_role,
                detected_tags=c.detected_tags,
            )
            for c in own_contributions
        ],
    )
