"""add events_blob_uri to fights

Revision ID: 0004_fight_events_blob_uri
Revises: 0003_fight_skills
Create Date: 2026-07-07 00:00:00

Phase 7 v1 wire-up: the parser now consumes the V1.3 cbtevent block and
emits a stream of :class:`DamageEvent` records. We persist that stream
as a gzipped JSONL blob in MinIO at ``events/{fight_id}.jsonl.gz`` and
add a nullable ``events_blob_uri`` column on ``fights`` so the GET
``/api/v1/fights/{id}/events`` route can locate the blob.

Historical fights (uploaded before this migration) keep
``events_blob_uri = NULL``. The route surfaces a ``404 Not Found`` for
those instead of a misleading empty aggregation, signalling to API
consumers that a re-upload is required to view deep metrics.
``GET /fights/{id}`` continues to return the agents + skills row
unchanged -- ``events_blob_uri`` is purely additive.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_fight_events_blob_uri"
down_revision: str | None = "0003_fight_skills"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fights",
        sa.Column("events_blob_uri", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fights", "events_blob_uri")
