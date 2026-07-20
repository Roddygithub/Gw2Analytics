"""Add blocked, dodges, interrupts to fight_player_summaries.

``blocked`` / ``dodges`` / ``interrupts`` are defense event counters
populated from the arcdps cbtevent ``result`` byte (Phase B of plan
172). All three are nullable ``Integer`` columns so pre-migration rows
keep ``NULL`` (the frontend treats NULL as "unavailable").

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import ClassVar

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: str | None = "0016_player_stats_enrich"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "fight_player_summaries",
        sa.Column("blocked", sa.Integer(), nullable=True),
    )
    op.add_column(
        "fight_player_summaries",
        sa.Column("dodges", sa.Integer(), nullable=True),
    )
    op.add_column(
        "fight_player_summaries",
        sa.Column("interrupts", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fight_player_summaries", "interrupts")
    op.drop_column("fight_player_summaries", "dodges")
    op.drop_column("fight_player_summaries", "blocked")
