"""Tests for ``backfill_role_detection`` (P6 from COVERAGE-90-PLAN).

Targets the uncovered ``backfill_role_detection`` function in backfill.py
(67% → ~85%). The function discovers OrmFightPlayerSummary rows where
``detected_role IS NULL`` and populates them via ``detect_role_lite``.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import select as sa_select

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import OrmFight, OrmFightPlayerSummary, Upload
from gw2analytics_api.scripts.backfill_player_summaries import backfill_role_detection


def _seed_summary_row(
    *,
    detected_role: str | None = None,
    detected_tags: list[str] | None = None,
) -> tuple[str, str]:
    """Create upload + fight + player_summary row.

    Returns ``(fight_id, account_name)``.
    """
    fight_id = f"bf-{_uuid.uuid4().hex[:12]}"
    account_name = f"test.{_uuid.uuid4().hex[:8]}"

    with get_sessionmaker()() as db:
        upload = Upload(
            id=_uuid.uuid4(),
            sha256=_uuid.uuid4().hex * 2,  # exactly 64 chars (String(64) column)
            original_filename="backfill.zevtc",
            size_bytes=42,
            status="completed",
        )
        db.add(upload)
        db.flush()

        # OrmFightPlayerSummary.fight_id has a FK to OrmFight.id.
        # OrmFight.upload_id has a FK to Upload.id (NOT NULL).
        db.add(
            OrmFight(
                id=fight_id,
                upload_id=upload.id,
                build_version="20240925",
                agent_count=1,
                started_at=datetime.now(UTC),
            ),
        )
        db.flush()

        db.add(
            OrmFightPlayerSummary(
                fight_id=fight_id,
                account_name=account_name,
                name="TestPlayer",
                profession=1,
                elite_spec=27,
                total_damage=1000,
                total_healing=500,
                total_buff_removal=10,
                detected_role=detected_role,
                detected_tags=detected_tags,
            ),
        )
        db.commit()

    return fight_id, account_name


def _row_exists(fight_id: str, account_name: str) -> OrmFightPlayerSummary | None:
    """Fetch a summary row by (fight_id, account_name)."""
    with get_sessionmaker()() as db:
        return (
            db.execute(
                sa_select(OrmFightPlayerSummary).where(
                    OrmFightPlayerSummary.fight_id == fight_id,
                    OrmFightPlayerSummary.account_name == account_name,
                ),
            )
            .scalars()
            .first()
        )


def test_backfill_role_detection_updates_null_rows() -> None:
    """Rows with detected_role=None get populated."""
    fight_id, acct = _seed_summary_row(detected_role=None)

    with get_sessionmaker()() as db:
        updated, skipped, failed = backfill_role_detection(db, fight_id=fight_id)

    assert updated == 1
    assert skipped == 0
    assert failed == 0

    row = _row_exists(fight_id, acct)
    assert row is not None
    assert row.detected_role is not None  # Was populated
    assert row.detected_tags is not None  # Was populated


def test_backfill_role_detection_skips_already_populated_rows() -> None:
    """Rows with detected_role already set are skipped (idempotency)."""
    fight_id, _acct = _seed_summary_row(
        detected_role="DPS",
        detected_tags=["power_damage"],
    )

    with get_sessionmaker()() as db:
        updated, skipped, failed = backfill_role_detection(db, fight_id=fight_id)

    assert updated == 0  # Already populated, no update
    assert skipped == 0
    assert failed == 0


def test_backfill_role_detection_dry_run() -> None:
    """dry_run=True computes roles but does not commit."""
    fight_id, acct = _seed_summary_row(detected_role=None)

    with get_sessionmaker()() as db:
        updated, skipped, failed = backfill_role_detection(db, fight_id=fight_id, dry_run=True)

    assert updated == 1  # Computed but not committed
    assert skipped == 0
    assert failed == 0

    row = _row_exists(fight_id, acct)
    assert row is not None
    assert row.detected_role is None  # Still NULL — dry run


def test_backfill_role_detection_empty_db() -> None:
    """No rows with detected_role=NULL -> 0 updated."""
    with get_sessionmaker()() as db:
        updated, skipped, failed = backfill_role_detection(db)

    assert updated == 0
    assert skipped == 0
    assert failed == 0
