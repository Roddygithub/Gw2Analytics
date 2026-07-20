"""Add boon strips and condition cleanses to fight_player_summaries

Revision ID: 88a9e507121b
Revises: 8534265864ec
Create Date: 2026-07-21 01:16:52.396614

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88a9e507121b'
down_revision: Union[str, Sequence[str], None] = '8534265864ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add boon_strips and condition_cleanses columns idempotently."""
    op.execute(
        "ALTER TABLE fight_player_summaries "
        "ADD COLUMN IF NOT EXISTS boon_strips INTEGER"
    )
    op.execute(
        "ALTER TABLE fight_player_summaries "
        "ADD COLUMN IF NOT EXISTS condition_cleanses INTEGER"
    )


def downgrade() -> None:
    """Remove boon_strips and condition_cleanses columns."""
    op.execute("ALTER TABLE fight_player_summaries DROP COLUMN IF EXISTS condition_cleanses")
    op.execute("ALTER TABLE fight_player_summaries DROP COLUMN IF EXISTS boon_strips")
