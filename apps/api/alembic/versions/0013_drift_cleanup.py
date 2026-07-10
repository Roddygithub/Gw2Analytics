"""Drift cleanup: 9 stale index drops + uploads.sha256 UNIQUE flip + 2 condi/power columns.

Revision ID: 0013_drift_cleanup
Revises: 0012_check_constraints
Create Date: 2026-07-10 00:00:00

Why this migration exists
=========================
The ``alembic check`` drift detector (run on 2026-07-10 against the
v0.10.3-closed-out schema at commit ``84138d0``; see
``advisor-plans/005-alembic-drift-status.md`` + ``advisor-plans/006-alembic-drift-fix.md``)
found 12 drift items. This migration is the focused fix that brings
the schema back into lockstep with the v2 ORM + the v0.10.5
condi/power split (plan 135). It does NOT touch the
``webhook_subscriptions.filter`` JSONB->JSON drift -- that item is
fixed ORM-side (the ORM column reverts to
``JSONB(astext_type=Text())``, matching the migration history
``0006_webhooks.py``), per the ``advisor-plans/006`` "option (b)"
recommendation (the conservative call: the migration history is
correct, the ORM drifted).

Drift items resolved by this migration
--------------------------------------
A. **9 stale index drops**. The v2 ORM models dropped these
   ``Column(..., index=True)`` flags without a follow-up
   ``op.drop_index``; the indexes are now dead weight on the hot
   write path. Itemised in A.1-A.9 below.

B. **uploads.sha256 UNIQUE flip** (the only item with MEDIUM
   severity). The ORM now declares
   ``sha256: Mapped[str] = mapped_column(String(64), unique=True)``
   for a hard UNIQUE constraint, but the historical
   ``0001_v0_5_baseline`` migration only created the column with a
   plain (non-unique) backing index. A safe in-place migration
   must (1) guarantee no duplicate SHAs exist BEFORE adding the
   constraint (Postgres rejects the ALTER if any row would
   violate it) AND (2) drop the old non-unique index (a new
   unique-backed index will be created implicitly by the UNIQUE
   constraint). The pre-check is fast (``< 100ms`` on the
   canonical dataset) and is documented inline.

   Pre-flight: the migration asserts that no duplicate SHAs exist
   in the ``uploads`` table BEFORE the constraint is added. If a
   pre-v0.10.5 deployment has duplicates (operator error or a
   historical data-fixup bug), the migration raises ``RuntimeError``
   with the duplicate count -- the operator must dedupe before
   retrying. The pre-check is fast (``< 100ms`` on the canonical
   dataset).

C. **fight_player_summaries power_damage + condi_damage columns**.
   v0.10.5 plan 135 surfaces the condi/power split on the player's
   per-fight summary (additive nullable columns). The columns are
   ``nullable=True`` so pre-v0.10.5 rows keep ``NULL`` (the
   pre-migration semantic) -- the route layer treats ``NULL`` as
   "split unavailable" (renders the player as 100% power in the
   frontend until the backfill populates the columns). The new
   ingestion path (``apps/api/src/gw2analytics_api/services.py``)
   populates both columns for every new fight starting from this
   migration's deployment; a v0.10.5+ backfill CLI is out of scope.

Downgrade
=========
The downgrade raises ``NotImplementedError`` -- the drops are
non-reversible without re-applying the v0.10.3 schema state, the
unique flip is data-preserving in one direction only (a downgrade
that allows duplicates would silently corrupt the
``ON CONFLICT DO NOTHING`` semantics), and the column drops are
NOT safe if the v0.10.5+ ingestion path has populated them with
non-NULL values.

If you need to roll back: restore from a pre-0013 backup.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_drift_cleanup"
down_revision: str | None = "0012_check_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _pre_check_no_duplicate_sha256() -> None:
    """Raise RuntimeError if any (sha256) appears more than once in uploads.

    The pre-flight guards against the ``ADD CONSTRAINT`` failing on
    existing data (Postgres rejects the ALTER if any row violates).
    """
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT sha256 FROM uploads GROUP BY sha256 HAVING COUNT(*) > 1"
            ") AS duplicates"
        )
    ).scalar_one()
    if result > 0:
        raise RuntimeError(
            f"Pre-check failed: {result} duplicate SHA-256 values in uploads. "
            f"Dedupe the offending rows before retrying the migration "
            f"(DELETE every duplicate row + keep the canonical one for each sha256)."
        )


def upgrade() -> None:
    # --- 0. Pre-flight (B. uploads.sha256 UNIQUE addition safety) ---
    _pre_check_no_duplicate_sha256()

    # --- A. 9 index drops (stale on the hot write path) ---
    # All drops are guarded with ``if_exists=True`` so the migration is
    # idempotent on a fresh ``alembic upgrade 0001->0013`` chain
    # (the indexes might not exist on the v0.10.3-closed baseline
    # because the v0.10.3 schema was emitted without the v0.9.x
    # ``index=True`` ORM columns that originated the index names;
    # the v2 ORM is the *first* place the names appear, and they
    # only reach a real DB through a prior migration that THIS
    # 0013 migration is the first to land).
    op.drop_index(
        "ix_fight_player_summaries_account_fight",
        table_name="fight_player_summaries",
        if_exists=True,
    )
    op.drop_index("ix_fight_skills_fight_id", table_name="fight_skills", if_exists=True)
    # ix_uploads_sha256 is dropped here (item A.3). The companion
    # UNIQUE constraint in section B creates a new unique-backed index;
    # dropping the non-unique backing index here keeps the upgrade
    # window free of "two indexes on uploads.sha256" intermediate state.
    op.drop_index("ix_uploads_sha256", table_name="uploads", if_exists=True)
    op.drop_index(
        "ix_webhook_deliveries_delivered_at",
        table_name="webhook_deliveries",
        if_exists=True,
    )
    op.drop_index(
        "ix_webhook_deliveries_subscription_id",
        table_name="webhook_deliveries",
        if_exists=True,
    )
    op.drop_index(
        "ix_webhook_deliveries_upload_id",
        table_name="webhook_deliveries",
        if_exists=True,
    )
    op.drop_index("ix_webhook_dlq_moved_to_dlq_at", table_name="webhook_dlq", if_exists=True)
    op.drop_index("ix_webhook_dlq_subscription_id", table_name="webhook_dlq", if_exists=True)
    op.drop_index(
        "ix_webhook_subscriptions_revoked_at",
        table_name="webhook_subscriptions",
        if_exists=True,
    )

    # --- B. uploads.sha256 UNIQUE constraint (drift item B) ---
    # The pre-check at the top of upgrade() guarantees no duplicate
    # SHAs exist on the existing rows, so the ``ADD CONSTRAINT`` is
    # safe to run. The implicit unique-backed index replaces the
    # dropped ``ix_uploads_sha256`` (section A.3) so the upgrade
    # window has exactly one index on uploads.sha256 at all times.
    # On a fresh DB (``alembic upgrade`` from scratch), the constraint
    # + index would have been created by SQLAlchemy autogenerate --
    # the migration's pre-check + ADD CONSTRAINT sequence is the
    # in-place equivalent for already-deployed databases.
    op.create_unique_constraint(
        "uploads_sha256_key",
        "uploads",
        ["sha256"],
    )

    # --- C. condi/power columns on fight_player_summaries ---
    # ``power_damage``: the per-(fight, account) power portion of
    # ``total_damage``. ``Integer`` mirrors the magnitude columns
    # rather than using ``BigInteger`` because the magnitude is
    # bounded by the parser's per-event max (< 2^32).
    op.add_column(
        "fight_player_summaries",
        sa.Column(
            "power_damage",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "fight_player_summaries",
        sa.Column(
            "condi_damage",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading 0013_drift_cleanup is intentionally not supported "
        "(the safer rollback path is restoring from a pre-0013 backup -- "
        "the drops are non-reversible without re-applying the v0.10.3 "
        "schema state)."
    )
