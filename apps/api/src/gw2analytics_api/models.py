"""ORM models for the V0.5 schema.

Three tables:
* ``uploads``     — every .zevtc file received (idempotent on sha256).
* ``fights``      — one row per parsed encounter (PK equals the sha256).
* ``fight_agents``— denormalised per-agent rows.

This file is the **only** place the wire-format for persistence lives.
Pydantic schemas (for the API) and Pydantic domain models (from
``gw2_core``) are kept strictly separate.
"""

# ``from __future__ import annotations`` is REQUIRED here: SQLAlchemy 2.0
# resolves ``Mapped[OrmFight | None]`` and ``list[OrmFightAgent]`` at class
# body execution time. Without this, removing the forward-reference quotes
# would cause NameError on import.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gw2analytics_api.database import Base

# Status values stored on ``uploads.status``. Keep in sync with Postgres CHECK if you add one.
UPLOAD_STATUS_PENDING = "pending"
UPLOAD_STATUS_COMPLETED = "completed"
UPLOAD_STATUS_FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Upload(Base):
    """A user-submitted combat log (.zevtc) along with parse status."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), default=UPLOAD_STATUS_PENDING, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_version: Mapped[str] = mapped_column(String(64), default="0", nullable=False)

    fight: Mapped[OrmFight | None] = relationship(
        back_populates="upload",
        uselist=False,
        cascade="all, delete-orphan",
    )


class OrmFight(Base):
    """One parsed combat encounter."""

    __tablename__ = "fights"

    # NB: ``OrmFight.id`` is the **inner EVTC** content hash (SHA-256 of the
    # extracted EVTC bytes, computed in ``parser.py:_iter_fights``). This
    # differs from ``Upload.sha256`` which hashes the OUTER zip blob. The two
    # are distinct identifiers — do not JOIN them as if they were equal.
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
    """One agent record denormalised into the fight for V0 metrics queries."""

    __tablename__ = "fight_agents"

    fight_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fights.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    profession: Mapped[int] = mapped_column(Integer, nullable=False)
    elite_spec: Mapped[int] = mapped_column(Integer, nullable=False)
    is_player: Mapped[bool] = mapped_column(Boolean, nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subgroup: Mapped[str | None] = mapped_column(String(128), nullable=True)

    fight: Mapped[OrmFight] = relationship(back_populates="agents")


class OrmFightSkill(Base):
    """One skill record (V1.3).

    Normalised into its own table so future event-stream tables (V1.4+)
    can FK into ``(fight_id, skill_id)`` for damage/healing/CC analytics.
    """

    __tablename__ = "fight_skills"

    fight_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fights.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    fight: Mapped[OrmFight] = relationship(back_populates="skills")
