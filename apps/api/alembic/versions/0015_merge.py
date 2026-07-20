"""Merge bigint and strip-account-colon migration heads.

Revision ID: 0015_merge
Revises: 0014_fps_bigint, 0014_strip_account_colon
Create Date: 2026-07-19 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_merge"
down_revision: str | Sequence[str] | None = (
    "0014_fps_bigint",
    "0014_strip_account_colon",
)
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
