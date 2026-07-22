"""Add roles (JSON) column to fight_player_summaries.

Stores the per-player multi-role classification computed by the
v0.14.x readout aggregator (DPS/Heal/Support/Strip/Cleanser/CC).
The column is a JSON array of strings, nullable so pre-migration
rows keep NULL. The compute is additive via _persist_player_summaries.

Revision ID: 57a3c9ee1b2f
Revises: 88a9e507121b
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "57a3c9ee1b2f"
down_revision: Union[str, None] = "88a9e507121b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fight_player_summaries",
        sa.Column(
            "roles",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Multi-role classification: list of strings (DPS/Heal/Support/Strip/Cleanser/CC)",
        ),
    )


def downgrade() -> None:
    op.drop_column("fight_player_summaries", "roles")
