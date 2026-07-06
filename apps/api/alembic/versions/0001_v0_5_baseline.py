"""baseline schema

Revision ID: 0001_v0_5_baseline
Revises:
Create Date: 2024-01-15 12:00:00

Initial V0.5 schema: uploads, fights, fight_agents.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_v0_5_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index("ix_uploads_sha256", "uploads", ["sha256"])

    op.create_table(
        "fights",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("build_version", sa.String(length=16), nullable=False),
        sa.Column("encounter_id", sa.Integer(), nullable=False),
        sa.Column("agent_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("game_type", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["upload_id"], ["uploads.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fights_upload_id", "fights", ["upload_id"])

    op.create_table(
        "fight_agents",
        sa.Column("fight_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("profession", sa.Integer(), nullable=False),
        sa.Column("elite_spec", sa.Integer(), nullable=False),
        sa.Column("is_player", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fight_id"], ["fights.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fight_id", "agent_id"),
    )


def downgrade() -> None:
    op.drop_table("fight_agents")
    op.drop_table("fights")
    op.drop_index("ix_fights_upload_id", table_name="fights")
    op.drop_index("ix_uploads_sha256", table_name="uploads")
    op.drop_table("uploads")
