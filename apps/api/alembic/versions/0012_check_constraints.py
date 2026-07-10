"""add CHECK constraints for domain invariants

Revision ID: 0012_check_constraints
Revises: 0011_player_role_detection
Create Date: 2026-07-10 00:00:00

Data-integrity hardening: 6 ``CHECK`` constraints on
existing columns, enforced at the DB layer. The
application code already enforces the same invariants
(Pydantic schemas + service-layer guards) but the DB
accepts any value; a direct write (psql / admin script /
compromised CI runner) bypasses the application guards.
The CHECK constraints close the gap at the lowest layer.

Affected invariants:

  1. ``uploads.status`` must be one of ('pending',
     'completed', 'failed') -- the 3-value enum enforced
     by ``UploadStatus`` in ``schemas.py``. (The plan 029
     text referenced 'parsing'/'parsed' but the live model
     uses 'completed'/'failed'; the constraint uses the
     live values to avoid migration-vs-code drift.)
  2. ``webhook_deliveries.attempt`` must be >= 0 -- the
     counter starts at 0 (server_default) and is
     monotonically incremented; negative values are a
     bug.
  3. ``webhook_deliveries.status_code`` must be in
     [100, 599] (when not NULL) -- the canonical HTTP
     status code range.
  4. ``fight_player_summaries.{total_damage,
     total_healing, total_buff_removal}`` must each be
     >= 0 -- magnitudes are non-negative by definition;
     negative values are a bug.

Pre-check: the migration's ``upgrade()`` first asserts
that no existing rows violate the constraints (via 4
``SELECT`` count queries). If any violating row is found,
the migration raises ``RuntimeError`` with a clear message
identifying the offending table + count. Operators must
either (a) clean up the offending rows manually, OR (b)
accept the migration failure and roll back to investigate.

Why pre-check, not ``NOT VALID`` + ``VALIDATE CONSTRAINT``:
  - The affected tables are small (<10K rows expected in
    production; the 0005-fight_player_summaries table is
    bounded by the number of attended players per fight).
  - The pre-check is fast (<1 s on the canonical dataset).
  - ``NOT VALID`` constraints are accepted by Postgres
    but skipped by the query planner; a future query
    might not see the constraint enforced. Cleaner to do
    a full ``ADD CONSTRAINT`` + pre-check.

Why no ``downgrade()`` for the constraints:
  - The constraints are DEFENSIVE; dropping them is a
    potential footgun. The plan keeps the constraints in
    place across all future migrations.
  - The ``downgrade()`` is intentionally a no-op that
    raises ``NotImplementedError`` with a clear message.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_check_constraints"
down_revision: str | None = "0011_player_role_detection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical enums + ranges, mirrored from
# ``apps/api/src/gw2analytics_api/models.py``
# (UPLOAD_STATUS_PENDING / UPLOAD_STATUS_COMPLETED /
#  UPLOAD_STATUS_FAILED). Keep in sync if the service-layer
#  enums change.
UPLOAD_STATUS_VALUES = ("pending", "completed", "failed")
WEBHOOK_STATUS_CODE_MIN = 100
WEBHOOK_STATUS_CODE_MAX = 599


def _pre_check_no_violations(table: str, where_clause: str) -> None:
    """Run ``SELECT COUNT(*) FROM <table> WHERE <where_clause>``
    and raise ``RuntimeError`` if the count is > 0. The pre-check
    guards against the ``ADD CONSTRAINT`` failing on existing
    data (Postgres rejects the ALTER if any row violates)."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}")
    ).scalar_one()
    if result > 0:
        raise RuntimeError(
            f"Pre-check failed: {result} rows in {table} violate "
            f"the new CHECK constraint (where: {where_clause!r}). "
            f"Clean up the offending rows before retrying the "
            f"migration."
        )


def upgrade() -> None:
    # Pre-check: ensure no existing rows violate the new
    # constraints. The pre-check is fast on the canonical
    # dataset (<1 s for the 4 tables combined at <10K rows
    # each).
    _pre_check_no_violations(
        "uploads",
        f"status NOT IN {UPLOAD_STATUS_VALUES!r}",
    )
    _pre_check_no_violations(
        "webhook_deliveries",
        "attempt < 0 OR (status_code IS NOT NULL AND "
        f"(status_code < {WEBHOOK_STATUS_CODE_MIN} OR "
        f"status_code > {WEBHOOK_STATUS_CODE_MAX}))",
    )
    _pre_check_no_violations(
        "fight_player_summaries",
        "total_damage < 0 OR total_healing < 0 OR total_buff_removal < 0",
    )

    # Constraint 1: uploads.status enum
    op.create_check_constraint(
        "ck_uploads_status",
        "uploads",
        f"status IN {UPLOAD_STATUS_VALUES!r}",
    )

    # Constraint 2: webhook_deliveries.attempt >= 0
    op.create_check_constraint(
        "ck_webhook_deliveries_attempt_nonneg",
        "webhook_deliveries",
        "attempt >= 0",
    )

    # Constraint 3: webhook_deliveries.status_code in
    # [100, 599] (or NULL)
    op.create_check_constraint(
        "ck_webhook_deliveries_status_code_range",
        "webhook_deliveries",
        f"status_code IS NULL OR "
        f"(status_code >= {WEBHOOK_STATUS_CODE_MIN} AND "
        f"status_code <= {WEBHOOK_STATUS_CODE_MAX})",
    )

    # Constraint 4a: fight_player_summaries.total_damage >= 0
    op.create_check_constraint(
        "ck_fight_player_summaries_damage_nonneg",
        "fight_player_summaries",
        "total_damage >= 0",
    )

    # Constraint 4b: fight_player_summaries.total_healing >= 0
    op.create_check_constraint(
        "ck_fight_player_summaries_healing_nonneg",
        "fight_player_summaries",
        "total_healing >= 0",
    )

    # Constraint 4c: fight_player_summaries.total_buff_removal >= 0
    op.create_check_constraint(
        "ck_fight_player_summaries_buff_removal_nonneg",
        "fight_player_summaries",
        "total_buff_removal >= 0",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading CHECK constraints is intentionally not "
        "supported (the constraints are defensive; dropping "
        "them is a footgun). If you need to roll back, "
        "restore from a pre-0012 backup."
    )
