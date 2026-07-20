"""Add guilds and guild_members tables.

Two new tables for guild tracking:
- ``guilds``: stores guild id, name, tag from the GW2 API.
- ``guild_members``: stores guild membership (account_name, rank).

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import ClassVar

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.String(72), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("tag", sa.String(128), nullable=False),
    )
    op.create_table(
        "guild_members",
        sa.Column(
            "guild_id",
            sa.String(72),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("account_name", sa.String(128), nullable=False),
        sa.Column("rank", sa.String(128), nullable=False, server_default=""),
    )
    op.create_unique_constraint(
        "uq_guild_member",
        "guild_members",
        ["guild_id", "account_name"],
    )


def downgrade() -> None:
    op.drop_table("guild_members")
    op.drop_table("guilds")
