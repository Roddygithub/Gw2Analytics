"""v0.9.0: add the webhook_subscriptions / webhook_deliveries / webhook_dlq tables.

The 3 webhook backend tables defined in ``docs/v0.8.0-backend-design.md`` §4:

- ``webhook_subscriptions``: the registered integrator profile
  (id, url, filter JSONB, description, secret, created_at,
  revoked_at). Soft-delete via revoked_at.

- ``webhook_deliveries``: per-(subscription, upload) delivery
  record (subscription_id FK, upload_id, attempt counter,
  status_code, error, delivered_at). The worker reads/writes
  this row through the 3-attempt retry schedule.

- ``webhook_dlq``: dead-letter queue for deliveries that have
  exhausted the retry budget. ``subscription_id`` is NOT FK-
  referenced here (the DLQ retains the original id for
  forensics even after the subscription is hard-deleted).

Schema choices follow the alembic precedent (v0.8.4's
migration 0005): id columns are TEXT + ``wh_`` / ``dly_`` /
``dlq_`` prefix + uuid hex; timestamps use
``DateTime(timezone=True)`` + Postgres ``now()`` default;
JSONB columns use ``sa.dialects.postgresql.JSONB(astext_type=
sa.Text())`` for the alembic-recognised Postgres type with
SQLite-test round-trip compat.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_webhooks"
down_revision: str | None = "0005_fight_player_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # webhook_subscriptions: the integrator profile.
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "filter",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_subscriptions"),
    )
    op.create_index(
        "ix_webhook_subscriptions_revoked_at",
        "webhook_subscriptions",
        ["revoked_at"],
    )

    # webhook_deliveries: per-(subscription, upload) retry record.
    # FK to webhook_subscriptions but NO ondelete CASCADE -- the
    # canonical state transition is soft-delete (``revoked_at``
    # on the parent subscription); a hard delete requires the
    # operator to clean up deliveries first (controlled FK
    # violation is intentional).
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("subscription_id", sa.String(length=64), nullable=False),
        sa.Column("upload_id", sa.String(length=64), nullable=False),
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["webhook_subscriptions.id"],
            name="fk_webhook_deliveries_subscription_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_deliveries"),
    )
    op.create_index(
        "ix_webhook_deliveries_subscription_id",
        "webhook_deliveries",
        ["subscription_id"],
    )
    op.create_index(
        "ix_webhook_deliveries_upload_id",
        "webhook_deliveries",
        ["upload_id"],
    )
    op.create_index(
        "ix_webhook_deliveries_delivered_at",
        "webhook_deliveries",
        ["delivered_at"],
    )

    # webhook_dlq: dead-letter queue. subscription_id is FORENSIC,
    # NOT FK-referenced -- a revoked subscription can still be
    # traced through its DLQ payload.
    op.create_table(
        "webhook_dlq",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("subscription_id", sa.String(length=64), nullable=False),
        sa.Column("upload_id", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "moved_to_dlq_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_dlq"),
    )
    op.create_index(
        "ix_webhook_dlq_subscription_id",
        "webhook_dlq",
        ["subscription_id"],
    )
    op.create_index(
        "ix_webhook_dlq_moved_to_dlq_at",
        "webhook_dlq",
        ["moved_to_dlq_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_dlq_moved_to_dlq_at", table_name="webhook_dlq")
    op.drop_index("ix_webhook_dlq_subscription_id", table_name="webhook_dlq")
    op.drop_table("webhook_dlq")

    op.drop_index(
        "ix_webhook_deliveries_delivered_at", table_name="webhook_deliveries"
    )
    op.drop_index(
        "ix_webhook_deliveries_upload_id", table_name="webhook_deliveries"
    )
    op.drop_index(
        "ix_webhook_deliveries_subscription_id",
        table_name="webhook_deliveries",
    )
    op.drop_table("webhook_deliveries")

    op.drop_index(
        "ix_webhook_subscriptions_revoked_at", table_name="webhook_subscriptions"
    )
    op.drop_table("webhook_subscriptions")
