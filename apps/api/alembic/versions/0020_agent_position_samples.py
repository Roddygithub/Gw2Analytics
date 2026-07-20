"""Add position_samples JSONB column to fight_agents.

Nullable JSONB column storing downsampled position heatmap samples
as an array of ``[time_ms, x, y]`` triples.  Downsampled to 1
sample per 500ms with a max of 2000 samples per player.  ``NULL``
when no position data is available.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import ClassVar

from alembic import op
import sqlalchemy as sa


revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "fight_agents",
        sa.Column("position_samples", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fight_agents", "position_samples")
