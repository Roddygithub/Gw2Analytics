"""V1.3: add the ``fight_skills`` table for skill persistence.

Revision ID: 0003_fight_skills
Revises: 0002_agent_identity_columns
Create Date: 2026-07-06 00:00:00

V1.2 added ``account_name`` and ``subgroup`` columns to ``fight_agents``.
V1.3 follows the same additive pattern: a new ``fight_skills`` table
with a composite PK ``(fight_id, skill_id)`` and a CASCADE FK to
``fights``. The table is intentionally minimal — just ``fight_id``,
``skill_id`` and ``name`` — so future event-stream tables (V1.4+)
can FK into ``(fight_id, skill_id)`` for damage / healing / CC
analytics without a schema change.

Existing ``fights`` rows are unaffected: they have zero skills until
the next re-parse, which is the correct behaviour.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_fight_skills"
down_revision = "0002_agent_identity_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fight_skills",
        sa.Column("fight_id", sa.String(length=64), nullable=False),
        sa.Column("skill_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["fight_id"],
            ["fights.id"],
            name="fk_fight_skills_fight_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fight_id", "skill_id", name="pk_fight_skills"),
    )
    op.create_index("ix_fight_skills_fight_id", "fight_skills", ["fight_id"])


def downgrade() -> None:
    op.drop_index("ix_fight_skills_fight_id", table_name="fight_skills")
    op.drop_table("fight_skills")
