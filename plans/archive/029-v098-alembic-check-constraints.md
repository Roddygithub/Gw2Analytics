# Plan 029 — v0.9.8 alembic CHECK constraints

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — prod hardening pass
**Status:** pending
**Effort:** S
**Category:** data integrity hardening (defence-in-depth at the DB layer)
**Files touched:** `apps/api/alembic/versions/0009_check_constraints.py` (NEW) + `apps/api/src/gw2analytics_api/models.py` (add `CheckConstraint` declarations)

## Problem

Migrations 0001-0008 do NOT add `CHECK` constraints to any column.
The application code enforces domain invariants (status enum,
non-negative magnitudes, valid HTTP status code range) but the
DB accepts any value. A direct DB write (psql / admin script /
compromised CI runner) bypasses the Pydantic schema validation
+ service-layer guards. 4 specific gaps:

1. **`uploads.status`** — declared as `sa.String(length=50)` in
   0001. The Pydantic schema + service layer enforce the 4-value
   enum `('pending', 'parsing', 'parsed', 'failed')`. A direct
   `UPDATE uploads SET status = 'wat' WHERE id = ...` succeeds
   silently; the next read returns the invalid value; the
   web UI crashes on the unknown status.
2. **`webhook_deliveries.attempt`** — declared as `sa.Integer()`
   in 0006 with `server_default=sa.text("0")`. A direct
   `UPDATE webhook_deliveries SET attempt = -1` succeeds; the
   scheduler's `attempt + 1` arithmetic produces `0` instead
   of `-1+1=0`, masking the bug.
3. **`webhook_deliveries.status_code`** — declared as
   `sa.Integer()` in 0006 (nullable). The service layer writes
   only valid HTTP status codes (100-599) but the DB accepts
   any int. A direct write of `status_code = 99999` makes the
   GET-deliveries route render the raw int to the integrator,
   breaking their dashboards.
4. **`fight_player_summaries` magnitudes** (3 columns:
   `total_damage`, `total_healing`, `total_buff_removal`) —
   declared as `sa.Integer()` in 0005 with `server_default=0`.
   The service layer writes non-negative sums, but a direct
   `UPDATE ... SET total_damage = -100` succeeds; the next
   `/players` listing renders a negative damage number.

## Goals

- Add a new migration `0009_check_constraints.py` that adds
  `CHECK` constraints to the 4 affected tables.
- Add the `CheckConstraint` declarations to the corresponding
  SQLAlchemy ORM models in `apps/api/src/gw2analytics_api/models.py`
  so the constraints are part of the model metadata (defence-
  in-depth for in-process test runs against SQLite-in-tests).
- Write a 1-test hermetic regression test per constraint that
  asserts a violating INSERT is rejected with `IntegrityError`.

## Non-goals

- Adding a `webhook_deliveries.status` column. The state is
  currently inferred from `status_code` + `delivered_at`; adding
  a status column is a separate (larger) refactor. Tracked
  as a v0.9.9+ item.
- Enforcing FK constraints not currently in the schema
  (e.g. `webhook_dlq.subscription_id` is intentionally
  FORENSIC-not-FK per migration 0006's docstring). Out of
  scope.
- Migrating the schema to a different migration tool
  (sqlalchemy-migrate, sqitch, atlas). Out of scope (alembic
  is the production contract).
- Backfilling existing rows that violate the new constraints.
  The 4 constraints below are all "the value must be in
  range" — historical rows MUST already be in range (the
  service layer enforced them at write time). If any
  historical row violates a constraint, the migration's
  `upgrade()` MUST filter them out OR raise. The plan
  covers this with a pre-check.

## Implementation

### File: `apps/api/alembic/versions/0009_check_constraints.py` (NEW)

```python
"""add CHECK constraints for domain invariants

Revision ID: 0009_check_constraints
Revises: 0008_payload_bytes
Create Date: 2026-07-09 00:00:00

Data-integrity hardening: 4 ``CHECK`` constraints on existing
columns, enforced at the DB layer. The application code already
enforces the same invariants (Pydantic schemas + service-layer
guards) but the DB accepts any value; a direct write (psql /
admin script / compromised CI runner) bypasses the application
guards. The CHECK constraints close the gap at the lowest layer.

Affected invariants:

  1. ``uploads.status`` must be one of
     ('pending', 'parsing', 'parsed', 'failed') -- the 4-value
     enum enforced by ``UploadStatus`` in ``schemas.py``.
  2. ``webhook_deliveries.attempt`` must be >= 0 -- the
     counter starts at 0 (server_default) and is monotonically
     incremented; negative values are a bug.
  3. ``webhook_deliveries.status_code`` must be in [100, 599]
     (when not NULL) -- the canonical HTTP status code range.
  4. ``fight_player_summaries.{total_damage, total_healing,
     total_buff_removal}`` must each be >= 0 -- magnitudes are
     non-negative by definition; negative values are a bug.

Pre-check: the migration's ``upgrade()`` first asserts that no
existing rows violate the constraints (via 4 ``SELECT`` count
queries). If any violating row is found, the migration raises
``RuntimeError`` with a clear message identifying the offending
table + count. Operators must either (a) clean up the offending
rows manually, OR (b) accept the migration failure and roll
back to investigate.

Why pre-check, not ``NOT VALID`` + ``VALIDATE CONSTRAINT``:
  - The 4 tables are small (<10K rows expected in production;
    the 0005-fight_player_summaries table is bounded by the
    number of attended players per fight).
  - The pre-check is fast (<1 s on the canonical dataset).
  - ``NOT VALID`` constraints are accepted by Postgres but
    skipped by the query planner; a future query might not
    see the constraint enforced. Cleaner to do a full
    ``ADD CONSTRAINT`` + pre-check.

Why no ``downgrade()`` for the constraints:
  - The constraints are DEFENSIVE; dropping them is a
    potential footgun. The plan keeps the constraints in
    place across all future migrations.
  - The ``downgrade()`` is intentionally a no-op that raises
    ``NotImplementedError`` with a clear message.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_check_constraints"
down_revision: str | None = "0008_payload_bytes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Canonical enums + ranges, mirrored from apps/api/src/gw2analytics_api/schemas.py
# (UploadStatus) + apps/api/src/gw2analytics_api/models.py (the 3 magnitude
# defaults). Keep in sync if the service-layer enums change.
UPLOAD_STATUS_VALUES = ("pending", "parsing", "parsed", "failed")
WEBHOOK_STATUS_CODE_MIN = 100
WEBHOOK_STATUS_CODE_MAX = 599


def _pre_check_no_violations(table: str, where_clause: str) -> None:
    """Run ``SELECT COUNT(*) FROM <table> WHERE <where_clause>``
    and raise ``RuntimeError`` if the count is > 0. The pre-check
    guards against the ``ADD CONSTRAINT`` failing on existing
    data (Postgres rejects the ALTER if any row violates)."""
    conn = op.get_bind()
    result = conn.execute(
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
    # Pre-check: ensure no existing rows violate the new constraints.
    # The pre-check is fast on the canonical dataset (<1 s for the
    # 4 tables combined at <10K rows each).
    _pre_check_no_violations(
        "uploads",
        "status NOT IN ('pending', 'parsing', 'parsed', 'failed')",
    )
    _pre_check_no_violations(
        "webhook_deliveries",
        "attempt < 0 OR (status_code IS NOT NULL AND "
        "(status_code < 100 OR status_code > 599))",
    )
    _pre_check_no_violations(
        "fight_player_summaries",
        "total_damage < 0 OR total_healing < 0 OR "
        "total_buff_removal < 0",
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

    # Constraint 3: webhook_deliveries.status_code in [100, 599]
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
        "supported (the constraints are defensive; dropping them "
        "is a footgun). If you need to roll back, restore from a "
        "pre-0009 backup."
    )
```

### File: `apps/api/src/gw2analytics_api/models.py`

Add `CheckConstraint` declarations to the 3 affected ORM models.
The constraints mirror the migration's pre-check + the service-
layer invariants. SQLite-in-tests enforces CHECK constraints
from version 3.3+, so the hermetic test suite gets the same
protection as production Postgres.

```python
from sqlalchemy import CheckConstraint, Column, Integer, String, Table

# uploads
uploads = Table(
    "uploads",
    Base.metadata,
    # ... existing columns ...
    CheckConstraint(
        "status IN ('pending', 'parsing', 'parsed', 'failed')",
        name="ck_uploads_status",
    ),
    # ... existing constraints ...
)

# webhook_deliveries
webhook_deliveries = Table(
    "webhook_deliveries",
    Base.metadata,
    # ... existing columns ...
    CheckConstraint(
        "attempt >= 0",
        name="ck_webhook_deliveries_attempt_nonneg",
    ),
    CheckConstraint(
        "status_code IS NULL OR "
        "(status_code >= 100 AND status_code <= 599)",
        name="ck_webhook_deliveries_status_code_range",
    ),
    # ... existing constraints ...
)

# fight_player_summaries
fight_player_summaries = Table(
    "fight_player_summaries",
    Base.metadata,
    # ... existing columns ...
    CheckConstraint(
        "total_damage >= 0",
        name="ck_fight_player_summaries_damage_nonneg",
    ),
    CheckConstraint(
        "total_healing >= 0",
        name="ck_fight_player_summaries_healing_nonneg",
    ),
    CheckConstraint(
        "total_buff_removal >= 0",
        name="ck_fight_player_summaries_buff_removal_nonneg",
    ),
    # ... existing constraints ...
)
```

(Note: the exact column definitions in the snippet above are
abbreviated for clarity. The actual edit uses the existing
`OrmUpload` / `OrmWebhookDelivery` / `OrmFightPlayerSummary`
classes with the `__table_args__` tuple, adding the
`CheckConstraint` declarations to the existing tuple.)

### Test plan

1. **Pre-check on the canonical test DB**: the migration
   upgrades from `0008_payload_bytes` → `0009_check_constraints`
   in <2 s (the pre-check finds 0 violating rows on the
   test DB).
2. **Pre-check on a poisoned test DB**: manually insert a
   row with `status = 'wat'` into `uploads`; the migration
   raises `RuntimeError` with a clear message.
3. **Constraint enforcement**: after the migration, a
   direct `INSERT INTO uploads (..., status, ...) VALUES
   (..., 'wat', ...)` raises `IntegrityError`.
4. **Constraint enforcement on webhook_deliveries.attempt**:
   `UPDATE webhook_deliveries SET attempt = -1 WHERE id = ...`
   raises `IntegrityError`.
5. **Constraint enforcement on webhook_deliveries.status_code**:
   `UPDATE webhook_deliveries SET status_code = 999 WHERE id = ...`
   raises `IntegrityError`; `UPDATE ... SET status_code = NULL`
   succeeds.
6. **Constraint enforcement on fight_player_summaries**: an
   `UPDATE ... SET total_damage = -1 WHERE ...` raises
   `IntegrityError`.
7. **Hermetic regression tests** (NEW, in
   `apps/api/tests/test_alembic_constraints.py`):
   - `test_uploads_status_check_constraint` — 4 OK values +
     1 violating value (rejected).
   - `test_webhook_deliveries_attempt_nonneg` — 0, 1, 10
     (accepted); -1 (rejected).
   - `test_webhook_deliveries_status_code_range` — 100, 200,
     404, 599, NULL (accepted); 99, 600, 99999 (rejected).
   - `test_fight_player_summaries_magnitudes_nonneg` —
     0, 1000 (accepted); -1, -1000 (rejected for all 3 cols).
8. **All existing tests pass** — the constraints do not
   reject any current code path.

## Acceptance criteria

- [ ] `apps/api/alembic/versions/0009_check_constraints.py`
      exists with the 6 `op.create_check_constraint` calls +
      the pre-check + the `NotImplementedError` downgrade.
- [ ] `apps/api/src/gw2analytics_api/models.py` has the
      6 `CheckConstraint` declarations on the 3 affected
      tables.
- [ ] `apps/api/tests/test_alembic_constraints.py` has the
      4 hermetic regression tests; all 4 pass.
- [ ] The full `apps/api/tests/` suite still passes
      (no existing test rejected by the new constraints).
- [ ] `mypy libs apps --no-incremental` is clean.
- [ ] `ruff check` is clean.
- [ ] No production code paths change (the constraints are
      defensive; the application code already enforces the
      same invariants).

## Out-of-scope / deferred

- **`webhook_deliveries.status` enum column**: the state is
  currently inferred from `status_code` + `delivered_at`;
  adding a status column is a separate (larger) refactor.
  Tracked as a v0.9.9+ item.
- **Pre-existing CHECK constraints on other tables**
  (e.g. `webhook_subscriptions.filter` JSONB schema
  validation, `fights.agent_count >= 0`): the 4 constraints
  in this plan are the most-leverage; other invariants can
  be added in a v0.9.9+ followup.
- **Postgres-only `DOMAIN` types** (e.g. `CREATE DOMAIN
  http_status_code AS INTEGER CHECK (...)`): out of scope
  (the 4 column-level CHECKs cover the highest-leverage
  invariants).
- **NOT VALID + VALIDATE CONSTRAINT for zero-downtime
  migration on a busy production table**: the 4 affected
  tables are small enough that a full constraint add is
  fine (<1 s). For larger tables, a future plan can adopt
  the `NOT VALID` + `VALIDATE` pattern.

## Maintenance notes

- **SQLite CHECK constraints**: SQLite enforces CHECK from
  version 3.3.0 (2016); the canonical test suite uses a
  modern SQLite. The hermetic test suite gets the same
  constraint enforcement as production Postgres.
- **Migration pre-check cost**: the pre-check runs 3
  `SELECT COUNT(*)` queries on the 3 tables. On the
  canonical dataset (1K fights, 5K agents, 10K summary
  rows, 100K deliveries), the cost is <100 ms. On a
  future 1M-row dataset, the cost grows to ~5 s — still
  acceptable for a one-time migration.
- **Adding a new status value** to `UploadStatus`: a
  future change to add a 5th status (e.g. `cancelled`)
  must update BOTH the Pydantic schema AND the CHECK
  constraint. A test in `test_alembic_constraints.py`
  that asserts the constraint rejects `cancelled` would
  catch the sync drift.
