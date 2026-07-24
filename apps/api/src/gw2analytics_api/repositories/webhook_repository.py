"""Repository for webhook-related models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from gw2analytics_api.models import OrmWebhookDelivery, OrmWebhookDlq, OrmWebhookSubscription

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


__all__ = ["WebhookRepository"]


class WebhookRepository:
    """All DB access for webhook subscriptions, deliveries, and DLQ."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Subscriptions ────────────────────────────────────────

    def get_subscription_by_id(self, subscription_id: str) -> OrmWebhookSubscription | None:
        return self._session.get(OrmWebhookSubscription, subscription_id)

    def find_active_subscriptions(self) -> list[OrmWebhookSubscription]:
        return list(
            self._session.execute(
                select(OrmWebhookSubscription).where(
                    OrmWebhookSubscription.revoked_at.is_(None),
                ),
            )
            .scalars()
            .all()
        )

    def add_subscription(self, sub: OrmWebhookSubscription) -> None:
        self._session.add(sub)

    # ── Deliveries ───────────────────────────────────────────

    def get_delivery_by_id(self, delivery_id: str) -> OrmWebhookDelivery | None:
        return self._session.get(OrmWebhookDelivery, delivery_id)

    def find_deliveries_by_ids(self, delivery_ids: list[str]) -> dict[str, OrmWebhookDelivery]:
        deliveries = (
            self._session.execute(
                select(OrmWebhookDelivery).where(OrmWebhookDelivery.id.in_(delivery_ids)),
            )
            .scalars()
            .all()
        )
        return {d.id: d for d in deliveries}

    def find_deliveries_due(self, *, now: datetime) -> list[OrmWebhookDelivery]:
        return list(
            self._session.execute(
                select(OrmWebhookDelivery)
                .where(
                    OrmWebhookDelivery.next_attempt_at <= now,
                    OrmWebhookDelivery.delivered_at.is_(None),
                )
                .order_by(OrmWebhookDelivery.next_attempt_at.asc()),
            )
            .scalars()
            .all()
        )

    def add_delivery(self, delivery: OrmWebhookDelivery) -> None:
        self._session.add(delivery)

    # ── DLQ ──────────────────────────────────────────────────

    def get_dlq_by_id(self, delivery_id: str) -> OrmWebhookDlq | None:
        return self._session.get(OrmWebhookDlq, delivery_id)

    def get_dlq_by_id_for_update(self, delivery_id: str) -> OrmWebhookDlq | None:
        return self._session.execute(
            select(OrmWebhookDlq).where(OrmWebhookDlq.id == delivery_id).with_for_update(),
        ).scalar_one_or_none()

    def find_dlq_entries(
        self,
        *,
        subscription_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[OrmWebhookDlq]:
        stmt = select(OrmWebhookDlq).order_by(OrmWebhookDlq.moved_to_dlq_at.desc())
        if subscription_id is not None:
            stmt = stmt.where(OrmWebhookDlq.subscription_id == subscription_id)
        return list(self._session.execute(stmt.limit(limit).offset(offset)).scalars().all())

    def add_dlq(self, dlq: OrmWebhookDlq) -> None:
        self._session.add(dlq)

    def delete_dlq(self, dlq: OrmWebhookDlq) -> None:
        self._session.delete(dlq)

    # ── Transaction ──────────────────────────────────────────

    def commit(self) -> None:
        self._session.commit()

    def flush(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        self._session.rollback()
