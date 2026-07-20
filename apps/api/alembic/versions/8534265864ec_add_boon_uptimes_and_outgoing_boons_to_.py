"""Add boon uptimes and outgoing boons to fight_player_summaries

Revision ID: 8534265864ec
Revises: 0021
Create Date: 2026-07-21 00:39:52.271019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8534265864ec'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Ordered list of the 14 tracked boons, matching TRACKED_BUFFS keys.
_BOONS = [
    "might",
    "fury",
    "quickness",
    "alacrity",
    "protection",
    "regeneration",
    "vigor",
    "aegis",
    "stability",
    "swiftness",
    "resistance",
    "resolution",
    "superspeed",
    "stealth",
]


def upgrade() -> None:
    """Add boon uptime (percentage) and outgoing (stack-ms) columns.

    Idempotent: if a previous migration or manual schema change already
    created ``boon_<boon>_uptime`` columns, rename them to the canonical
    ``<boon>_uptime`` names used by the ORM. ``ADD COLUMN IF NOT EXISTS``
    guards the outgoing columns and any missing uptime columns.
    """
    boon_list = ", ".join(f"'{boon}'" for boon in _BOONS)
    op.execute(
        f"""
        DO $$
        DECLARE
            boon text;
            old_name text;
            new_name text;
        BEGIN
            FOREACH boon IN ARRAY ARRAY[{boon_list}]
            LOOP
                old_name := 'boon_' || boon || '_uptime';
                new_name := boon || '_uptime';
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'fight_player_summaries'
                      AND column_name = old_name
                ) THEN
                    EXECUTE format(
                        'ALTER TABLE fight_player_summaries RENAME COLUMN %I TO %I',
                        old_name, new_name
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )

    for boon in _BOONS:
        op.execute(
            f"ALTER TABLE fight_player_summaries "
            f"ADD COLUMN IF NOT EXISTS {boon}_uptime FLOAT"
        )
        op.execute(
            f"ALTER TABLE fight_player_summaries "
            f"ADD COLUMN IF NOT EXISTS outgoing_{boon} BIGINT"
        )


def downgrade() -> None:
    """Remove boon uptime and outgoing columns."""
    for boon in _BOONS:
        op.execute(f"ALTER TABLE fight_player_summaries DROP COLUMN IF EXISTS {boon}_uptime")
        op.execute(f"ALTER TABLE fight_player_summaries DROP COLUMN IF EXISTS outgoing_{boon}")
