"""``/api/v1/guilds`` endpoints.

GET list    : list guilds for an account.
GET detail  : guild info + members.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from gw2analytics_api.database import get_session
from gw2analytics_api.models import Guild, GuildMember
from gw2analytics_api.services.guild_service import list_guilds_for_account

router = APIRouter(prefix="/api/v1/guilds", tags=["guilds"])


class GuildInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    tag: str


class GuildMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_name: str
    rank: str


class GuildDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    tag: str
    members: list[GuildMemberOut] = []


@router.get("", response_model=list[GuildInfoOut])
def list_guilds(
    account_name: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> list[GuildInfoOut]:
    """List all guilds that the given account is a member of."""
    guilds = list_guilds_for_account(db, account_name)
    return [GuildInfoOut(id=g.id, name=g.name, tag=g.tag) for g in guilds]


@router.get("/{guild_id}", response_model=GuildDetailOut)
def get_guild(
    guild_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> GuildDetailOut:
    """Return guild info + members for a specific guild."""
    guild = db.execute(select(Guild).where(Guild.id == guild_id)).scalar_one_or_none()
    if guild is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "guild not found")
    members = (
        db.execute(select(GuildMember).where(GuildMember.guild_id == guild_id))
        .scalars()
        .all()
    )
    return GuildDetailOut(
        id=guild.id,
        name=guild.name,
        tag=guild.tag,
        members=[GuildMemberOut(account_name=m.account_name, rank=m.rank) for m in members],
    )
