"""Add boon uptime and outgoing generation columns to fight_player_summaries.

14 ``Float`` columns for per-buff uptime percentages (0.0-100.0) and
14 ``BigInteger`` columns for outgoing boon generation (cumulative
stack-time in ms).  All nullable so pre-migration rows keep NULL.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import ClassVar

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None

_BOON_UPTIME_COLUMNS: list[tuple[str, type]] = [
    ("boon_might_uptime", sa.Float()),
    ("boon_fury_uptime", sa.Float()),
    ("boon_quickness_uptime", sa.Float()),
    ("boon_alacrity_uptime", sa.Float()),
    ("boon_protection_uptime", sa.Float()),
    ("boon_regeneration_uptime", sa.Float()),
    ("boon_vigor_uptime", sa.Float()),
    ("boon_aegis_uptime", sa.Float()),
    ("boon_stability_uptime", sa.Float()),
    ("boon_swiftness_uptime", sa.Float()),
    ("boon_resistance_uptime", sa.Float()),
    ("boon_resolution_uptime", sa.Float()),
    ("boon_superspeed_uptime", sa.Float()),
    ("boon_stealth_uptime", sa.Float()),
]

_OUTGOING_COLUMNS: list[tuple[str, type]] = [
    ("outgoing_might", sa.BigInteger()),
    ("outgoing_fury", sa.BigInteger()),
    ("outgoing_quickness", sa.BigInteger()),
    ("outgoing_alacrity", sa.BigInteger()),
    ("outgoing_protection", sa.BigInteger()),
    ("outgoing_regeneration", sa.BigInteger()),
    ("outgoing_vigor", sa.BigInteger()),
    ("outgoing_aegis", sa.BigInteger()),
    ("outgoing_stability", sa.BigInteger()),
    ("outgoing_swiftness", sa.BigInteger()),
    ("outgoing_resistance", sa.BigInteger()),
    ("outgoing_resolution", sa.BigInteger()),
    ("outgoing_superspeed", sa.BigInteger()),
    ("outgoing_stealth", sa.BigInteger()),
]


def upgrade() -> None:
    for col_name, col_type in _BOON_UPTIME_COLUMNS:
        op.add_column(
            "fight_player_summaries",
            sa.Column(col_name, col_type, nullable=True),
        )
    for col_name, col_type in _OUTGOING_COLUMNS:
        op.add_column(
            "fight_player_summaries",
            sa.Column(col_name, col_type, nullable=True),
        )


def downgrade() -> None:
    # v0.16.0 fix: ``if_exists=True`` makes this downgrade idempotent
    # across the chain. The later migration ``8534265864ec`` renames
    # the ``boon_<X>_uptime`` columns emitted here to ``<X>_uptime`` and
    # owns the outgoing_<X> columns too, with its own
    # ``DROP COLUMN IF EXISTS`` on downgrade. Hitting this migration's
    # downgrade after ``8534265864ec``'s has already removed the columns
    # raises ``UndefinedColumn: outgoing_stealth`` (and the same for
    # every other boon) without ``if_exists=True``. With it, the
    # second pass is a no-op and ``alembic downgrade base`` succeeds.
    for col_name, _ in reversed(_OUTGOING_COLUMNS):
        op.drop_column("fight_player_summaries", col_name, if_exists=True)
    for col_name, _ in reversed(_BOON_UPTIME_COLUMNS):
        op.drop_column("fight_player_summaries", col_name, if_exists=True)
