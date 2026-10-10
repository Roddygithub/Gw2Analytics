"""Persist player dodge, block and interrupt counters in summaries.

Reconciles the defense-counter columns on ``fight_player_summaries``:
migration ``0017_player_defense_events`` already added ``blocked``,
``dodges`` and ``interrupts``. The product code (ORM, API schema and
frontend) names the block counter ``blocks``. This migration therefore adds
(or renames the legacy ``blocked`` column to) ``blocks`` and leaves the
already-present ``dodges``/``interrupts`` untouched, so it applies cleanly
on top of ``0017`` instead of re-adding columns that already exist.

Revision ID: 0022
Revises: ea3023c87c0f
Create Date: 2026-10-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0022"
down_revision: str | None = "ea3023c87c0f"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "fight_player_summaries"


def _columns() -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    columns = _columns()
    if "blocks" not in columns:
        if "blocked" in columns:
            # 0017 shipped the block counter as ``blocked``; the product
            # reads ``blocks``. Rename in place so existing rows are kept.
            op.alter_column(_TABLE, "blocked", new_column_name="blocks")
        else:
            op.add_column(_TABLE, sa.Column("blocks", sa.Integer(), nullable=True))
    for name in ("dodges", "interrupts"):
        if name not in columns:
            op.add_column(_TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    columns = _columns()
    if "blocks" in columns:
        # ``blocked`` is the 0017 name; ``dodges``/``interrupts`` belong to 0017.
        op.alter_column(_TABLE, "blocks", new_column_name="blocked")
