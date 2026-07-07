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
    # Phase 7 v1: location of the per-fight gzipped-JSONL event blob in
    # MinIO (``events/{fight_id}.jsonl.gz``). ``NULL`` for fights that
    # pre-date the parser-side event consumer OR for fights whose parser
    # pass yielded zero events (the parser degrades to ``NULL`` rather
    # than persist an empty blob). The ``/fights/{id}/events`` route
    # surfaces 404 in either case so consumers don't mistake
    # unavailability for zero damage.
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


class OrmFightPlayerSummary(Base):
    """One row per ``(fight_id, account_name)`` pair: the per-fight
    per-account damage / healing / buff-removal totals (v0.8.4).

    Materialises the cross-fight roll-up so the ``/api/v1/players``,
    ``/api/v1/players/{name}`` and ``/api/v1/players/{name}/timeline``
    routes can serve the per-account view with a pure SQL aggregation
    instead of walking every fight's gzipped events blob on every
    request. The previous O(fights x events) per-request cost was
    acceptable for v0.7.0 (handful of fights in the local-dev
    dataset) but the 5-30s latency for users with 100+ fights was
    the documented v0.7.0 perf debt.

    Schema design
    -------------
    - **Composite PK on ``(fight_id, account_name)``**: the row is
      identified by its (fight, player) pair; the CASCADE FK on
      ``fight_id`` keeps the table in sync with ``fights`` (a
      re-parsed fight replaces its rows atomically; a deleted
      fight removes its rows automatically).
    - **Denormalised identity** (``name`` / ``profession`` /
      ``elite_spec``): the source-side ``OrmFightAgent`` row carries
      the canonical identity, but denormalising on the summary
      eliminates the JOIN on every player-route request. The
      trade-off is a small write-time cost: a single
      ``OrmFightAgent.account_name -> (name, profession, elite_spec)``
      lookup per source-side event during the write. ``name`` is the
      last-seen char-name (the aggregator's contract);
      ``profession`` / ``elite_spec`` are first-seen anchors (also
      the aggregator's contract).
    - **Composite index on ``(account_name, fight_id)``**: the 3
      player routes filter on ``account_name`` (the per-player view)
      and sort by ``fight_id`` (the recency-first tiebreaker) so
      this single index covers both access patterns. ``fight_id``
      alone is also covered by the PK index (for the re-parse
      DELETE).
    """

    __tablename__ = "fight_player_summaries"

    fight_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("fights.id", ondelete="CASCADE"),
        primary_key=True,
    )
    account_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    # Denormalised identity (last-seen name, first-seen profession /
    # elite_spec) so the player routes don't JOIN ``OrmFightAgent``
    # on every request. See the class docstring for the rationale.
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    profession: Mapped[int] = mapped_column(Integer, nullable=False)
    elite_spec: Mapped[int] = mapped_column(Integer, nullable=False)
    # The 3 magnitudes. ``>= 0`` (the events blob is filtered to
    # positive values at parse time; the migration is additive so
    # existing rows keep their values without a backfill check).
    total_damage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_healing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_buff_removal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
