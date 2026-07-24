"""Repository for guild-related models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from gw2analytics_api.models import Guild, GuildMember

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


__all__ = ["GuildRepository"]


class GuildRepository:
    """All DB access for guilds and guild members."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── getters ──────────────────────────────────────────────

    def get_by_id(self, guild_id: str) -> Guild | None:
        return self._session.execute(
            select(Guild).where(Guild.id == guild_id),
        ).scalar_one_or_none()

    # ── finders ──────────────────────────────────────────────

    def find_guilds_for_account(self, account_name: str) -> list[Guild]:
        stmt = (
            select(Guild)
            .join(GuildMember)
            .where(GuildMember.account_name == account_name)
            .distinct()
        )
        return list(self._session.execute(stmt).scalars().all())

    def find_members_for_guild(self, guild_id: str) -> list[GuildMember]:
        return list(
            self._session.execute(
                select(GuildMember).where(GuildMember.guild_id == guild_id),
            )
            .scalars()
            .all()
        )

    # ── save ─────────────────────────────────────────────────

    def add_guild(self, guild: Guild) -> None:
        self._session.add(guild)

    def add_member(self, member: GuildMember) -> None:
        self._session.add(member)

    def flush(self) -> None:
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()
