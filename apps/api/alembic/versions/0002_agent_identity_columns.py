"""add account_name and subgroup to fight_agents

Revision ID: 0002_agent_identity_columns
Revises: 0001_v0_5_baseline
Create Date: 2026-01-15 12:00:00

Phase 2 -> V1 parser upgrade: the EVTC V1 layout surfaces an
arcdps combo string ``char_name\\0:account_name\\0subgroup\\0`` for
player agents. We persist both new fields as nullable columns on
``fight_agents`` so existing V0 rows remain valid (no backfill needed:
V0 had no notion of either field, so any historical row gets NULL
which the API exposes as ``null``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_agent_identity_columns"
down_revision: str | None = "0001_v0_5_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fight_agents",
        sa.Column("account_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "fight_agents",
        sa.Column("subgroup", sa.String(length=128), nullable=True),
    )
    # Widen the ``name`` column from 64 to 128 bytes to match the V1
    # parser's MAX_NAME_BYTES budget (covers full combo string with
    # UTF-8 slack; the parsed character name itself is still bounded
    # by arcdps' 19-char cap).
    op.alter_column("fight_agents", "name", existing_type=sa.String(length=64), type_=sa.String(length=128))


def downgrade() -> None:
    op.alter_column("fight_agents", "name", existing_type=sa.String(length=128), type_=sa.String(length=64))
    op.drop_column("fight_agents", "subgroup")
    op.drop_column("fight_agents", "account_name")
