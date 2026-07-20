"""v0.10.29: widen fight_player_summaries magnitude columns to BigInteger.

Real WvW fights produce per-player damage totals that exceed the
int32 range (e.g. > 200 billion). This migration widens the five
magnitude columns to BIGINT so the summary rows can persist without
NumericValueOutOfRange errors.

Revision ID: 0014_fps_bigint
Revises: 0013_drift_cleanup
Create Date: 2026-07-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0014_fps_bigint"
down_revision: str | None = "0013_drift_cleanup"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "fight_player_summaries",
        "total_damage",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "fight_player_summaries",
        "total_healing",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "fight_player_summaries",
        "total_buff_removal",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "fight_player_summaries",
        "power_damage",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "fight_player_summaries",
        "condi_damage",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "fight_player_summaries",
        "condi_damage",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "fight_player_summaries",
        "power_damage",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.alter_column(
        "fight_player_summaries",
        "total_buff_removal",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "fight_player_summaries",
        "total_healing",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "fight_player_summaries",
        "total_damage",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
