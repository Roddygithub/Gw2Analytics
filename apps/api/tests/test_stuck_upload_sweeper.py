"""Tests for the stuck-upload sweeper (plan 014)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import UPLOAD_STATUS_FAILED, UPLOAD_STATUS_PENDING, Upload
from gw2analytics_api.workers.stuck_upload_sweeper import _sweep_once


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
