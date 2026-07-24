from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from gw2analytics_api.database import Base


class Guild(Base):
    __tablename__ = "guilds"

    id: Mapped[str] = mapped_column(String(72), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tag: Mapped[str] = mapped_column(String(128), nullable=False)


class GuildMember(Base):
    __tablename__ = "guild_members"

    __table_args__ = (Index("ix_guild_members_account", "account_name"),)

    guild_id: Mapped[str] = mapped_column(
        String(72),
        ForeignKey("guilds.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    account_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    rank: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
