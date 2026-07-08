"""v0.9.1: extend webhook_deliveries with retry-scheduling columns.

Adds:
  * ``next_attempt_at`` (TIMESTAMPTZ, nullable, indexed) -- the
    scheduler poll reads ``WHERE next_attempt_at <= now() OR IS NULL``
    so retries are batched per the 1s/10s/100s exponential backoff
    schedule (design doc §5).
  * ``payload`` (JSONB, nullable for back-compat with pre-v0.9.1 rows)
    -- the canonical outbound body bytes originally POSTed. Stored
    on the delivery row so the retry + replay paths can re-emit
    byte-for-byte (HMAC-SHA256 integrity on the integrator side).

Per design doc §5 + the v0.9.0 [Unreleased] “### Known followup (api -
v0.9.1 webhook retry + DLQ)” block.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_webhook_retry"
down_revision = "0006_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_webhook_deliveries_next_attempt_at",
        "webhook_deliveries",
        ["next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_deliveries_next_attempt_at",
        table_name="webhook_deliveries",
    )
    op.drop_column("webhook_deliveries", "payload")
    op.drop_column("webhook_deliveries", "next_attempt_at")
