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
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
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
    # v0.10.2 hotfix: NUMERIC(20, 0) for arcdps uint64 (see migration 0010).
    agent_id: Mapped[int] = mapped_column(Numeric(20, 0), primary_key=True)
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
    # v0.10.3 plan 083: heuristic role detection (ported from
    # WvW_Analytics's ``apps/api/src/api/services/roles.py``).
    # ``detected_role`` is the primary role (DPS / HEAL / STRIP /
    # BOON / MIXED / UNKNOWN); ``String(30)`` covers every
    # current role name + a generous future-proofing margin.
    # ``detected_tags`` is an open-ended list of downstream-UX
    # signals (high_dps / off_meta / foreign_badges:<role> /
    # zero_output / ...). Stored as JSON (not ARRAY(String)) so
    # the list shape is flexible without an Alembic type change
    # on every future tag addition. Both columns are
    # ``nullable=True`` so the pre-v0.10.3 rows (which were
    # materialised without the heuristic) keep ``NULL`` -- the
    # frontend treats ``NULL`` as "unknown" (the pre-migration
    # semantic). The ``_persist_player_summaries`` helper
    # populates both columns for every new fight; see migration
    # 0011 + ``libs/gw2_analytics/role_detection.py`` for the
    # algorithm + the rationale.
    detected_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    detected_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class OrmWebhookSubscription(Base):
    """One registered webhook subscription (v0.9.0 backend).

    Created by ``POST /api/v1/webhooks`` and queried by the
    worker pool on every parse-completion notification.
    Soft-delete via ``revoked_at`` (NULL = active) so the
    ``GET /api/v1/webhooks`` endpoint can surface the analyst's
    audit panel without losing the historical record.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # SQL column is ``filter`` (matches the design doc §4 verbatim);
    # Python attr is ``filter_payload`` to shadow the Python builtin
    # ``filter()`` (which shadows nothing in practice but the
    # symbolic collision is a footgun in IDE auto-complete).
    filter_payload: Mapped[dict[str, object]] = mapped_column("filter", JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v0.10.0 plan 031: secret at rest is Fernet-envelope-encrypted
    # and stored as raw bytes (CWE-256 closure). The plaintext
    # ``whsec_<base64>`` secret crosses the wire ONLY at HMAC-sign
    # time inside ``workers/webhook_dispatch._dispatch_single``;
    # a stolen DB snapshot is NOT enough to forge signatures --
    # the attacker must ALSO have access to the ``SECRETS_KEK`` env
    # var. ``LargeBinary`` mirrors the same byte-preserving pattern
    # the ``webhook_deliveries.payload`` + ``webhook_dlq.payload``
    # columns use (v0.9.2 plan 009 Step 1) so HMAC byte-for-byte
    # integrity is preserved across the decrypt-then-sign flow.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Back-populates via FK from deliveries (the dlq side does
    # NOT have an FK -- deliberate forensics decision per
    # ``OrmWebhookDlq`` docstring). The route / service layer
    # queries the dlq via a manual filter on subscription_id;
    # no ``dlq_entries`` relationship here.
    deliveries: Mapped[list[OrmWebhookDelivery]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )


class OrmWebhookDelivery(Base):
    """One webhook delivery attempt chain (v0.9.0 backend).

    Created by the worker when a parse-completion matches a
    subscription's filter; updated through the 3-attempt retry
    schedule (1s / 10s / 100s exponential backoff) until
    success or DLQ-promotion.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # FK to webhook_subscriptions.id. NO ondelete cascade -- the
    # canonical state transition is soft-delete (revoked_at);
    # hard delete is a manual operator action that surfaces a
    # controlled FK violation.
    subscription_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("webhook_subscriptions.id"),
        nullable=False,
    )
    upload_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # v0.9.1: retry scheduler columns. ``next_attempt_at`` is the
    # wall-clock instant the polling worker
    # (webhook_scheduler.py) re-attempts a failed delivery; rows
    # with NULL ``next_attempt_at`` are picked up immediately. The
    # 1s/10s/100s exponential backoff (design doc §5) writes the
    # scheduled instant after each failed POST. ``payload`` stores
    # the canonical outbound body so retries + replays re-emit
    # byte-for-byte (HMAC-SHA256 integrity on the integrator side).
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    subscription: Mapped[OrmWebhookSubscription] = relationship(back_populates="deliveries")


class OrmWebhookDlq(Base):
    """One dead-letter entry (v0.9.0 backend).

    Populated by the worker when a delivery has exhausted the
    3-attempt retry schedule. Retained indefinitely (no
    automatic cleanup); the v0.9.x followup will surface a
    ``POST /webhooks/dlq/{id}/replay`` endpoint for manual
    replay.

    Schema note: ``subscription_id`` is NOT FK-referenced. The
    DLQ keeps the original id for forensics even after the
    subscription is hard-deleted; the route / service layer
    queries the subscription row directly by id when needed
    (no SQLAlchemy relationship here).
    """

    __tablename__ = "webhook_dlq"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(64), nullable=False)
    upload_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    moved_to_dlq_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
