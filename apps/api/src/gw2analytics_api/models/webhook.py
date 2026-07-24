from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gw2analytics_api.database import Base, utcnow


class OrmWebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    filter_payload: Mapped[dict[str, object]] = mapped_column(
        "filter", JSONB(astext_type=Text()), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deliveries: Mapped[list[OrmWebhookDelivery]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )


class OrmWebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    __table_args__ = (
        CheckConstraint(
            "attempt >= 0",
            name="ck_webhook_deliveries_attempt_nonneg",
        ),
        CheckConstraint(
            "status_code IS NULL OR (status_code >= 100 AND status_code <= 599)",
            name="ck_webhook_deliveries_status_code_range",
        ),
        Index("ix_webhook_deliveries_sub_next", "subscription_id", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
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
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    subscription: Mapped[OrmWebhookSubscription] = relationship(back_populates="deliveries")


class OrmWebhookDlq(Base):
    __tablename__ = "webhook_dlq"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Phase 1.3: FK to webhook_subscriptions.id (both String(64), compatible).
    # Note: upload_id FK is intentionally omitted because uploads.id is Uuid
    # and webhook_dlq.upload_id is String(64) — PostgreSQL rejects cross-type
    # FKs. A type-consistent migration would require changing the column type
    # which is deferred to Phase 3 schema normalization.
    subscription_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("webhook_subscriptions.id"),
        nullable=False,
    )
    upload_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    moved_to_dlq_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
