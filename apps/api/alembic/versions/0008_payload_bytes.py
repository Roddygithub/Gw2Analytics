"""migrate webhook payload columns to LargeBinary (canonical-bytes)

Revision ID: 0008_payload_bytes
Revises: 0007_webhook_retry
Create Date: 2026-07-08

Why
---
Pre-v0.9.2: ``OrmWebhookDelivery.payload`` + ``OrmWebhookDlq.payload`` are
mapped as ``JSON`` (Postgres JSONB). JSONB intrinsically re-orders keys
on round-trip. ``json.dumps(canonical_dict, separators=(",", ":"))``
produces bytes X; ORM round-trip via JSONB yields bytes Y != X because
JSONB normalised the keys during storage. The HMAC-SHA256 signature
differs across retries + replays, breaking the integrator's
byte-for-byte HMAC verification contract documented in design doc
§3.4.

Post-v0.9.2: payload is ``LargeBinary`` (raw bytes). The dispatch
worker writes the canonical bytes (json.dumps(body, separators=(",",
":")).encode("utf-8")); HMAC computes on bytes verbatim; replay
copies bytes verbatim; the integrator's verification is
byte-identical across retries + initial POST + replay.

Data migration safety
---------------------
``USING convert_to(payload::text, 'UTF8')`` converts existing JSONB
rows to bytea WITHOUT an explicit drain. This is LOSSY: JSONB-stored
dicts do not have canonical key ordering, so the converted bytes are
NOT byte-equivalent to what the original dispatch worker emitted.

For PRODUCTION deployments with active DLQ rows pre-migration
v0.9.2:

1. BEFORE running this migration, drain the DLQ via
   ``POST /api/v1/webhooks/dlq/{id}/replay`` so the scheduler
   flushes pending intents to byte-canonical format.

2. Operators preferring a 100 % lossless upgrade may
   ``DELETE FROM webhook_dlq WHERE moved_to_dlq_at < (now() -
   interval '1 day')`` after a successful drain; this is
   intentionally NOT part of the migration (manual operator
   action documented in ``docs/v0.8.0-backend-design.md``).

Downgrade path
--------------
``op.alter_column(..., type_=JSONB, existing_type=LargeBinary,
postgresql_using="convert_from(payload, 'UTF8')::jsonb")``
reconstructs the dict. The resulting key ordering is JSONB-default
(alphabetical), so the reconstructed dict differs from the
canonical dispatch bytes; HMAC verification on downgraded rows
FAILS until the next replay attempt, which writes the canonical
bytes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_payload_bytes"
down_revision: str | None = "0007_webhook_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "webhook_deliveries",
        "payload",
        existing_type=sa.dialects.postgresql.JSONB(),
        type_=sa.LargeBinary(),
        existing_nullable=True,
        postgresql_using="convert_to(payload::text, 'UTF8')",
    )
    op.alter_column(
        "webhook_dlq",
        "payload",
        existing_type=sa.dialects.postgresql.JSONB(),
        type_=sa.LargeBinary(),
        existing_nullable=False,
        postgresql_using="convert_to(payload::text, 'UTF8')",
    )


def downgrade() -> None:
    op.alter_column(
        "webhook_deliveries",
        "payload",
        existing_type=sa.LargeBinary(),
        type_=sa.dialects.postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="convert_from(payload, 'UTF8')::jsonb",
    )
    op.alter_column(
        "webhook_dlq",
        "payload",
        existing_type=sa.LargeBinary(),
        type_=sa.dialects.postgresql.JSONB(),
        existing_nullable=False,
        postgresql_using="convert_from(payload, 'UTF8')::jsonb",
    )
