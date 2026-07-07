"""v0.8.4: add the fight_player_summaries table to materialise the per-fight per-account roll-up.

Revision ID: 0004_fight_player_summaries
Revises: 0003_fight_skills
Create Date: 2026-07-07 12:00:00

The 3 player-centric routes (/api/v1/players, /api/v1/players/{name},
/api/v1/players/{name}/timeline) currently walk every fight's gzipped
events blob on every request (the O(fights x events) cost documented
in the v0.7.0 CHANGELOG: "5-30s latency for users with 100+ fights").
This migration adds the fight_player_summaries table that the
background parser populates after each successful fight parse -- the
3 player routes then serve the per-account view with a pure SQL
aggregation (O(rows) instead of O(fights x events)).

Schema design (mirrors the models.py::OrmFightPlayerSummary docstring):
- Composite PK on (fight_id, account_name) -- the row is identified
  by its (fight, player) pair. CASCADE FK on fight_id keeps the table
  in sync with the fights table.
- Denormalised identity (name, profession, elite_spec) so the player
  routes don't JOIN OrmFightAgent on every request. Last-seen name,
  first-seen profession/elite (the PlayerProfileAggregator's contract).
- 3 magnitudes: total_damage, total_healing, total_buff_removal.
- Composite index on (account_name, fight_id) covers the 3 routes'
  access pattern (filter on account_name, sort by fight_id for the
  recency-first tiebreaker).

Existing fights are unaffected: they have zero summary rows until the
next re-parse, which is the correct behaviour (the routes fall back
to the on-demand blob-walk for pre-migration fights; see
_compute_contributions in routes/players.py).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_fight_player_summaries"
down_revision: str | None = "0004_fight_events_blob_uri"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fight_player_summaries",
        sa.Column("fight_id", sa.String(length=64), nullable=False),
        sa.Column("account_name", sa.String(length=128), nullable=False),
        # Denormalised identity (last-seen name, first-seen profession /
        # elite_spec) so the player routes don't JOIN ``OrmFightAgent``
        # on every request.
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("profession", sa.Integer(), nullable=False),
        sa.Column("elite_spec", sa.Integer(), nullable=False),
        # The 3 magnitudes. ``default=0`` so a partial INSERT (a row
        # with only identity columns) is valid -- the parser writes
        # all 3 magnitudes atomically, but the default is defensive
        # against a future refactor that splits the write.
        sa.Column(
            "total_damage",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_healing",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_buff_removal",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.ForeignKeyConstraint(
            ["fight_id"],
            ["fights.id"],
            name="fk_fight_player_summaries_fight_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "fight_id",
            "account_name",
            name="pk_fight_player_summaries",
        ),
    )
    # Composite index on (account_name, fight_id) -- the 3 player
    # routes filter on account_name and sort by fight_id, so a
    # single index covers both access patterns. The PK index on
    # (fight_id, account_name) covers the re-parse DELETE
    # (WHERE fight_id = ?).
    op.create_index(
        "ix_fight_player_summaries_account_fight",
        "fight_player_summaries",
        ["account_name", "fight_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fight_player_summaries_account_fight",
        table_name="fight_player_summaries",
    )
    op.drop_table("fight_player_summaries")
