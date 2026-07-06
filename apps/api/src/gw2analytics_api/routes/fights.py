"""/api/v1/fights`` endpoints.

GET list : paginated metadata list of all fights the API has parsed.
GET detail: a single fight with its embedded agents.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gw2analytics_api.database import get_session
from gw2analytics_api.models import OrmFight
from gw2analytics_api.schemas import AgentOut, FightOut

router = APIRouter(prefix="/api/v1/fights", tags=["fights"])


@router.get("", response_model=list[FightOut])
def list_fights(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),  # noqa: B008
) -> list[FightOut]:
    """Return up to ``limit`` fights (skipping the first ``offset``)."""
    rows = (
        db.execute(
            select(OrmFight).order_by(OrmFight.started_at.desc()).limit(limit).offset(offset),
        )
        .scalars()
        .all()
    )
    return [_to_fight_out(f) for f in rows]


@router.get("/{fight_id}", response_model=FightOut)
def get_fight(
    fight_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> FightOut:
    """Return a fight by id (the upload's sha256)."""
    fight = db.execute(
        select(OrmFight).where(OrmFight.id == fight_id).options(selectinload(OrmFight.agents)),
    ).scalar_one_or_none()
    if fight is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fight not found")
    return _to_fight_out(fight)


def _to_fight_out(fight: OrmFight) -> FightOut:
    return FightOut(
        id=fight.id,
        build_version=fight.build_version,
        encounter_id=fight.encounter_id,
        agent_count=fight.agent_count,
        started_at=fight.started_at,
        game_type=fight.game_type,
        agents=[
            AgentOut(
                agent_id=a.agent_id,
                name=a.name,
                profession=("UNKNOWN" if a.profession == 0 else f"PROF({a.profession})"),
                elite_spec=("BASE" if a.elite_spec == 0 else f"ELITE({a.elite_spec})"),
                is_player=a.is_player,
                account_name=a.account_name,
                subgroup=a.subgroup,
            )
            for a in fight.agents
        ],
    )
