from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gw2analytics_api.models.upload import Upload

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gw2analytics_api.database import Base


class OrmFight(Base):
    __tablename__ = "fights"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    upload_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("uploads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    build_version: Mapped[str] = mapped_column(String(16), nullable=False)
    encounter_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    agent_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    game_type: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    events_blob_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)

    upload: Mapped[Upload] = relationship(back_populates="fight")
    agents: Mapped[list[OrmFightAgent]] = relationship(
        back_populates="fight",
        cascade="all, delete-orphan",
        order_by="OrmFightAgent.agent_id",
    )
    skills: Mapped[list[OrmFightSkill]] = relationship(
        back_populates="fight",
        cascade="all, delete-orphan",
        order_by="OrmFightSkill.skill_id",
    )


class OrmFightAgent(Base):
    __tablename__ = "fight_agents"

    fight_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fights.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[int] = mapped_column(Numeric(20, 0), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    profession: Mapped[int] = mapped_column(Integer, nullable=False)
    elite_spec: Mapped[int] = mapped_column(Integer, nullable=False)
    is_player: Mapped[bool] = mapped_column(Boolean, nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subgroup: Mapped[str | None] = mapped_column(String(128), nullable=True)

    fight: Mapped[OrmFight] = relationship(back_populates="agents")


class OrmFightSkill(Base):
    __tablename__ = "fight_skills"

    fight_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fights.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    fight: Mapped[OrmFight] = relationship(back_populates="skills")


class OrmFightPlayerSummary(Base):
    __tablename__ = "fight_player_summaries"

    __table_args__ = (
        CheckConstraint(
            "total_damage >= 0",
            name="ck_fight_player_summaries_damage_nonneg",
        ),
        CheckConstraint(
            "total_healing >= 0",
            name="ck_fight_player_summaries_healing_nonneg",
        ),
        CheckConstraint(
            "total_buff_removal >= 0",
            name="ck_fight_player_summaries_buff_removal_nonneg",
        ),
    )

    fight_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fights.id", ondelete="CASCADE"),
        primary_key=True,
    )
    account_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    profession: Mapped[int] = mapped_column(Integer, nullable=False)
    elite_spec: Mapped[int] = mapped_column(Integer, nullable=False)
    total_damage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_healing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_buff_removal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detected_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    detected_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    power_damage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condi_damage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    might_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    fury_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    quickness_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    alacrity_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    protection_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    regeneration_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    vigor_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    aegis_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    stability_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    swiftness_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    resistance_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    superspeed_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    stealth_uptime: Mapped[float | None] = mapped_column(Float, nullable=True)
    outgoing_might: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_fury: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_quickness: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_alacrity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_protection: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_regeneration: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_vigor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_aegis: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_stability: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_swiftness: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_resistance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_resolution: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_superspeed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outgoing_stealth: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    boon_strips: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_cleanses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roles: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
