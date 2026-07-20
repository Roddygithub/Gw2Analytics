"""v0.11.0 plan 172 Phase A: add enriched player stat columns to fight_player_summaries.

Real WvW fights produce per-player damage-taken, deaths, downs, and
stun-break counts that the existing OrmFightPlayerSummary does not
track. This migration adds 4 nullable columns -- NULL preserves the
pre-v0.11.0 contract (the frontend treats NULL as "unavailable").

Revision ID: 0016_player_stats_enrich
Revises: 0015_merge
Create Date: 2026-07-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016_player_stats_enrich"
down_revision: str | None = "0015_merge"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "fight_player_summaries",
        sa.Column("damage_taken", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "fight_player_summaries",
        sa.Column("downs", sa.Integer(), nullable=True),
    )
    op.add_column(
        "fight_player_summaries",
        sa.Column("deaths", sa.Integer(), nullable=True),
    )
    op.add_column(
        "fight_player_summaries",
        sa.Column("stun_breaks", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fight_player_summaries", "stun_breaks")
    op.drop_column("fight_player_summaries", "deaths")
    op.drop_column("fight_player_summaries", "downs")
    op.drop_column("fight_player_summaries", "damage_taken")
