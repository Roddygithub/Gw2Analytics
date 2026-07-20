"""Add fight context column (zerg / guild_raid / roam / unknown).

Nullable ``String(20)`` column on ``fights`` so pre-migration rows keep
NULL (frontend treats NULL as "unknown").  The context value is
computed from the ally count on fight persistence by the
``context_detector.classify_fight_context`` heuristic.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import ClassVar

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "fights",
        sa.Column("context", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fights", "context")
