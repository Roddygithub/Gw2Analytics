"""Tests for the stuck-upload sweeper (plan 014)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import (
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_PENDING,
    OrmFight,
    Upload,
)
from gw2analytics_api.workers.stuck_upload_sweeper import (
    _sweep_failed_once,
    _sweep_once,
)


@pytest.fixture()
def _seed_stale_upload() -> uuid.UUID:
    """Insert a pending upload older than the threshold."""
    session = get_sessionmaker()()
    upload = Upload(
        id=uuid.uuid4(),
        sha256=f"stale-{uuid.uuid4().hex[:16]}",
        original_filename="stale.zevtc",
        size_bytes=1024,
        status=UPLOAD_STATUS_PENDING,
        uploaded_at=datetime.now(UTC) - timedelta(seconds=600),
        parser_version="0.5.0",
    )
    session.add(upload)
    session.commit()
    session.close()
    return upload.id


@pytest.fixture()
def _seed_fresh_upload() -> uuid.UUID:
    """Insert a pending upload newer than the threshold."""
    session = get_sessionmaker()()
    upload = Upload(
        id=uuid.uuid4(),
        sha256=f"fresh-{uuid.uuid4().hex[:16]}",
        original_filename="fresh.zevtc",
        size_bytes=2048,
        status=UPLOAD_STATUS_PENDING,
        uploaded_at=datetime.now(UTC) - timedelta(seconds=60),
        parser_version="0.5.0",
    )
    session.add(upload)
    session.commit()
    session.close()
    return upload.id


def _get_upload(upload_id: uuid.UUID) -> Upload | None:
    """Fetch an upload by ID in a fresh session."""
    session = get_sessionmaker()()
    result = session.execute(select(Upload).where(Upload.id == upload_id))
    upload = result.scalar_one_or_none()
    session.close()
    return upload


def test_sweep_marks_stale_upload_as_failed(_seed_stale_upload: uuid.UUID) -> None:
    """Stale pending upload (> threshold) is marked failed."""
    upload_id = _seed_stale_upload
    session_factory = get_sessionmaker()
    count = _sweep_once(session_factory, threshold_s=300)
    assert count == 1
    upload = _get_upload(upload_id)
    assert upload is not None
    assert upload.status == UPLOAD_STATUS_FAILED
    assert "stuck-pending-sweeper" in (upload.error_message or "")


def test_sweep_skips_fresh_upload(_seed_fresh_upload: uuid.UUID) -> None:
    """Fresh pending upload (< threshold) is NOT modified."""
    upload_id = _seed_fresh_upload
    session_factory = get_sessionmaker()
    count = _sweep_once(session_factory, threshold_s=300)
    assert count == 0
    upload = _get_upload(upload_id)
    assert upload is not None
    assert upload.status == UPLOAD_STATUS_PENDING


def test_sweep_mixed_uploads(
    _seed_stale_upload: uuid.UUID,
    _seed_fresh_upload: uuid.UUID,
) -> None:
    """Only stale uploads are marked; fresh ones are untouched."""
    stale_id = _seed_stale_upload
    fresh_id = _seed_fresh_upload
    session_factory = get_sessionmaker()
    count = _sweep_once(session_factory, threshold_s=300)
    assert count == 1
    stale = _get_upload(stale_id)
    fresh = _get_upload(fresh_id)
    assert stale is not None
    assert fresh is not None
    assert stale.status == UPLOAD_STATUS_FAILED
    assert fresh.status == UPLOAD_STATUS_PENDING


def test_sweep_no_pending_uploads() -> None:
    """Sweep with no pending uploads returns 0."""
    session_factory = get_sessionmaker()
    count = _sweep_once(session_factory, threshold_s=300)
    assert count == 0


# ---------------------------------------------------------------------------
# v0.10.26-pre plan 170: failed-upload cleanup sweep tests.
#
# The helper is :func:`_sweep_failed_once` -- DB-blocking, called from the
# lifespan ticker. The 5 tests below exercise the 5 branches the design
# doc lists (option c with ``NOT EXISTS`` subquery):
# 1. no eligible rows (huge retention)
# 2. happy path: stale collision without dependents IS deleted
# 3. safety guard: stale collision WITH dependents NOT deleted
# 4. LIKE filter: non-collision failure mode NOT deleted
# 5. retention window: fresh collision (in-window) NOT deleted
#
# Fixture sha256 prefixes are stable so a followup teardown can sweep
# them out by pattern if the test DB ever needs cleanup.
# ---------------------------------------------------------------------------


@pytest.fixture()
def _seed_stale_collision_no_dependents() -> uuid.UUID:
    """Failed-upload row older than the retention window, error message
    matches the plan 160 idempotency collision signature, no dependent
    OrmFight row (the cleanup sweep's happy path).
    """
    session = get_sessionmaker()()
    upload = Upload(
        id=uuid.uuid4(),
        sha256=f"collision-no-dep-{uuid.uuid4().hex[:16]}",
        original_filename="collision.zevtc",
        size_bytes=4096,
        status=UPLOAD_STATUS_FAILED,
        # 91 days old — > 90-day default retention window.
        uploaded_at=datetime.now(UTC) - timedelta(days=91),
        parser_version="0.5.0",
        error_message="Duplicate fight: abc123def456...",
    )
    session.add(upload)
    session.commit()
    session.close()
    return upload.id


@pytest.fixture()
def _seed_stale_collision_with_dependents() -> tuple[uuid.UUID, str]:
    """Failed-upload row + a dependent OrmFight row. The cleanup
    sweep's NOT EXISTS guard MUST preserve the upload (otherwise
    the FK cascade orphans the fight + 3 child tables).
    Returns ``(upload_id, fight_id)``.
    """
    session = get_sessionmaker()()
    upload_id = uuid.uuid4()
    upload = Upload(
        id=upload_id,
        sha256=f"collision-with-dep-{uuid.uuid4().hex[:16]}",
        original_filename="collision-dep.zevtc",
        size_bytes=4096,
        status=UPLOAD_STATUS_FAILED,
        uploaded_at=datetime.now(UTC) - timedelta(days=91),
        parser_version="0.5.0",
        error_message="Duplicate fight: def789abc123...",
    )
    session.add(upload)
    # Flush so the upload.id is valid before assigning to fight.
    session.flush()
    # Required :class:`OrmFight` fields: id (String 64 inner-EVTC
    # sha256), upload_id (UUID FK), build_version, encounter_id,
    # agent_count, started_at, game_type.
    fight_id = uuid.uuid4().hex
    fight = OrmFight(
        id=fight_id,
        upload_id=upload_id,
        build_version="20250714-123456",
        encounter_id=1,
        agent_count=10,
        started_at=datetime.now(UTC) - timedelta(days=91),
        game_type=4,
    )
    session.add(fight)
    session.commit()
    session.close()
    return upload_id, fight_id


@pytest.fixture()
def _seed_stale_parse_error_upload() -> uuid.UUID:
    """Failed-upload row whose error message is NOT the plan 160
    collision signature — the cleanup sweep's LIKE clause MUST
    preserve it even when no dependents exist (the LIKE exclusion
    is the operator-facing safety belt).
    """
    session = get_sessionmaker()()
    upload = Upload(
        id=uuid.uuid4(),
        sha256=f"parse-error-{uuid.uuid4().hex[:16]}",
        original_filename="bad.zevtc",
        size_bytes=2048,
        status=UPLOAD_STATUS_FAILED,
        uploaded_at=datetime.now(UTC) - timedelta(days=91),
        parser_version="0.5.0",
        error_message="Parse failed: zlib checksum invalid",
    )
    session.add(upload)
    session.commit()
    session.close()
    return upload.id


@pytest.fixture()
def _seed_fresh_collision_no_dependents() -> uuid.UUID:
    """Failed-upload row INSIDE the retention window (89 days <
    90-day default). The LIKE clause matches, but the
    uploaded_at cutoff gate MUST preserve it.
    """
    session = get_sessionmaker()()
    upload = Upload(
        id=uuid.uuid4(),
        sha256=f"fresh-collision-{uuid.uuid4().hex[:16]}",
        original_filename="fresh.zevtc",
        size_bytes=4096,
        status=UPLOAD_STATUS_FAILED,
        # 89 days old -> within 90-day retention default.
        uploaded_at=datetime.now(UTC) - timedelta(days=89),
        parser_version="0.5.0",
        error_message="Duplicate fight: recentabc123...",
    )
    session.add(upload)
    session.commit()
    session.close()
    return upload.id


def test_failed_sweep_no_eligible_rows_with_huge_retention() -> None:
    """retention_days=10_000 (≈ 27 years) makes NO row in any
    sane test DB old enough to match. The ``LIKE`` + status + age
    pre-conditions compound to zero rows; sweep returns 0.
    """
    session_factory = get_sessionmaker()
    count = _sweep_failed_once(session_factory, retention_days=10_000)
    assert count == 0


def test_failed_sweep_deletes_stale_collision_no_dependents(
    _seed_stale_collision_no_dependents: uuid.UUID,
) -> None:
    """Happy path: stale collision row with no OrmFight dependents
    IS hard-deleted. Verifies the cleanup is observable on the
    candidate row's exact uuid (count-based assertions would be
    brittle against pre-existing test DB rows).
    """
    upload_id = _seed_stale_collision_no_dependents
    upload_before = _get_upload(upload_id)
    assert upload_before is not None
    assert upload_before.status == UPLOAD_STATUS_FAILED
    assert upload_before.error_message is not None
    assert upload_before.error_message.startswith("Duplicate fight:")

    session_factory = get_sessionmaker()
    _sweep_failed_once(session_factory, retention_days=90)

    upload_after = _get_upload(upload_id)
    assert upload_after is None, (
        "stale collision without dependents must be hard-deleted by the sweep"
    )


def test_failed_sweep_skips_collisions_with_dependents(
    _seed_stale_collision_with_dependents: tuple[uuid.UUID, str],
) -> None:
    """Safety guard: stale collision row WITH a dependent
    :class:`OrmFight` row is NOT deleted -- the FK CASCADE
    would orphan the fight + 3 child tables otherwise. Verified
    on BOTH the upload (still present) AND the dependent fight
    (still present + still references the upload).
    """
    upload_id, fight_id = _seed_stale_collision_with_dependents

    session_factory = get_sessionmaker()
    _sweep_failed_once(session_factory, retention_days=90)

    upload_after = _get_upload(upload_id)
    assert upload_after is not None, (
        "must NOT delete upload with dependent OrmFight (FK cascade would orphan)"
    )
    assert upload_after.status == UPLOAD_STATUS_FAILED

    # The dependent fight row must also remain intact + reference
    # the upload (a corrupted FK would be a critical regression).
    verify_session = get_sessionmaker()()
    fight_after = verify_session.execute(
        select(OrmFight).where(OrmFight.id == fight_id)
    ).scalar_one_or_none()
    verify_session.close()
    assert fight_after is not None, (
        "dependent OrmFight must remain intact post-sweep"
    )
    assert fight_after.upload_id == upload_id, (
        "FK reference must still point at the surviving upload"
    )


def test_failed_sweep_skips_non_collision_failures(
    _seed_stale_parse_error_upload: uuid.UUID,
) -> None:
    """LIKE filter: a stale upload whose error message is NOT
    ``Duplicate fight:...`` is NOT deleted. The operator-facing
    safety belt — actionable failure modes (parse errors, network
    blips) are kept for inspection even when old.
    """
    upload_id = _seed_stale_parse_error_upload

    session_factory = get_sessionmaker()
    _sweep_failed_once(session_factory, retention_days=90)

    upload_after = _get_upload(upload_id)
    assert upload_after is not None, (
        "non-collision failure mode must NOT be deleted"
    )


def test_failed_sweep_skips_fresh_collisions(
    _seed_fresh_collision_no_dependents: uuid.UUID,
) -> None:
    """Retention window: a collision row INSIDE the retention
    window (89 days old, default 90) is NOT deleted even though
    the LIKE + status pre-conditions match. The uploaded_at
    cutoff gate is the second safety belt.
    """
    upload_id = _seed_fresh_collision_no_dependents

    session_factory = get_sessionmaker()
    _sweep_failed_once(session_factory, retention_days=90)

    upload_after = _get_upload(upload_id)
    assert upload_after is not None, (
        "fresh collision inside retention window must NOT be deleted"
    )
