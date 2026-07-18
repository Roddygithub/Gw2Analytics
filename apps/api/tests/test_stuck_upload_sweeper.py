"""Tests for the stuck-upload sweeper (plan 014)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import (
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_PENDING,
    OrmFight,
    Upload,
)
from gw2analytics_api.workers.stuck_upload_sweeper import (
    _observe_sweep_durations,
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


# ---------------------------------------------------------------------------
# v0.10.26-pre plan 170 follower: operator-tunable batch size.
#
# Settings.stuck_sweeper_failed_batch_size (env STUCK_SWEEPER_FAILED_BATCH_SIZE,
# default 1000, ge=10, le=100_000) threads through lifespan_stuck_upload_sweeper
# into _sweep_failed_once(session_factory, retention_days, batch_size). The
# default module-level _BATCH_DELETE_SIZE (1000) is the helper's Python
# signature default so direct-from-pytest callers (this file's 5 prior tests)
# stay backward-compatible. This 6th test exercises the threading: seed 3
# eligible rows, sweep with batch_size=2, assert exactly 2 deleted + 1
# survivor, then sweep again with the default to confirm the survivor IS
# picked up on the next tick.
# ---------------------------------------------------------------------------


@pytest.fixture()
def _seed_three_eligible_collisions() -> list[uuid.UUID]:
    """Seed 3 stale collision rows (no dependents, same error signature).
    All three would be eligible for the default sweep in a single tick;
    passing batch_size=2 should leave the 3rd for a subsequent tick.
    """
    session = get_sessionmaker()()
    ids: list[uuid.UUID] = []
    for i in range(3):
        upload = Upload(
            id=uuid.uuid4(),
            sha256=f"batch-{i}-{uuid.uuid4().hex[:16]}",
            original_filename=f"batch{i}.zevtc",
            size_bytes=4096,
            status=UPLOAD_STATUS_FAILED,
            uploaded_at=datetime.now(UTC) - timedelta(days=91),
            parser_version="0.5.0",
            error_message=f"Duplicate fight: batch-{i}-hash...",
        )
        session.add(upload)
        ids.append(upload.id)
    session.commit()
    session.close()
    return ids


def test_failed_sweep_respects_explicit_batch_size_override(
    _seed_three_eligible_collisions: list[uuid.UUID],
) -> None:
    """Operator-tunable batch size threading: 3 eligible rows seeded,
    sweep with batch_size=2 deletes exactly 2, the 3rd survives until
    the next sweep (with default batch_size) cleans it up. Verifies
    both the per-tick LIMIT cap AND the across-tick completeness
    invariant (no row is permanently stranded by the batch cap).
    """
    [id_a, id_b, id_c] = _seed_three_eligible_collisions
    session_factory = get_sessionmaker()
    # Teardown guard: if any assertion fails between the seed and the
    # final sweep tick, the 3 seeded rows would otherwise leak into
    # the shared test DB and pollute downstream tests (the sweep is
    # global -- any other test seeding sha256 collisions would race
    # against the leaked rows). The finally block hard-deletes any
    # seeded row still present, regardless of which sweep tick
    # failed. On the happy path the block is a no-op (all 3 are
    # already deleted by the 2nd sweep tick).
    try:
        # Tick 1: explicit batch_size=2 should hard-delete exactly 2 of 3.
        deleted_first = _sweep_failed_once(
            session_factory,
            retention_days=90,
            batch_size=2,
        )
        assert deleted_first == 2, (
            f"batch_size=2 must cap the per-tick delete at 2; got {deleted_first}"
        )

        # Exactly 1 of the 3 must survive (the 3rd). We can't predict
        # WHICH one Postgres returns from the DELETE-with-IN-subquery
        # (the IN subquery order is implementation-defined), so we assert
        # set membership: exactly one of {a, b, c} survives.
        survivors = [
            uid
            for uid in (id_a, id_b, id_c)
            if _get_upload(uid) is not None
        ]
        assert len(survivors) == 1, (
            f"exactly 1 row must survive a batch_size=2 sweep of 3 rows; "
            f"survivors={survivors}"
        )

        # Tick 2: default batch_size (the module-level _BATCH_DELETE_SIZE
        # constant) must clean up the survivor — verifies the across-tick
        # completeness invariant (no permanent stranding).
        deleted_second = _sweep_failed_once(session_factory, retention_days=90)
        assert deleted_second == 1, (
            f"followup default-batch sweep must delete the surviving row; "
            f"got {deleted_second}"
        )

        # All 3 seeded rows are now hard-deleted.
        for uid in (id_a, id_b, id_c):
            assert _get_upload(uid) is None, (
                f"row {uid} must be hard-deleted after the 2nd sweep tick"
            )
    finally:
        # Hard-delete any seeded row still present. The DELETE is a
        # no-op for already-deleted rows (rowcount=0), so the finally
        # block is idempotent against the happy path AND partial
        # failures (e.g. assertion failure after tick 1 leaves the
        # survivor behind).
        teardown_session = get_sessionmaker()()
        try:
            for uid in (id_a, id_b, id_c):
                if _get_upload(uid) is not None:
                    teardown_session.execute(
                        delete(Upload).where(Upload.id == uid)
                    )
            teardown_session.commit()
        finally:
            teardown_session.close()


# ---------------------------------------------------------------------------
# v0.10.26-pre plan 170 follower: per-sweep histogram attribution.
#
# The pure ``_observe_sweep_durations`` helper extracted from the lifespan
# ticker is unit-tested directly here. The helper is responsible for
# routing the per-iteration timestamps to the 3 histograms:
#   - STUCK_SWEEPER_PENDING_ITERATION_DURATION: pending sweep only
#   - STUCK_SWEEPER_FAILED_ITERATION_DURATION: failed sweep only
#   - STUCK_SWEEPER_ITERATION_DURATION: backward-compat combined
#
# The helper observes via prometheus_client's documented public
# ``.observe(seconds)`` contract; the test asserts via the histogram's
# ``_sum`` accessor (private but stable in the prometheus_client library)
# to verify the helper correctly splits the durations without standing up
# the asyncio loop / DB dependency.
# ---------------------------------------------------------------------------


def test_observe_sweep_durations_helper() -> None:
    """Pure helper correctly computes 3 durations AND fires .observe() on the 3 histograms.

    v0.10.27-pre polish: the helper now returns the computed
    durations as a ``(pending_dur, failed_dur, combined_dur)``
    tuple (eliminating the prometheus_client private ``_sum.get()``
    dependency from the test). The test ALSO uses
    ``unittest.mock.patch`` on the 3 histogram objects to assert
    that ``.observe()`` was called with the right values -- this
    restores the implicit coverage the old ``_sum.get()`` assertion
    provided (proving the .observe() side effect fired).

    A future refactor that accidentally drops the ``.observe()``
    calls would still return the right tuple (the return value
    proves the COMPUTATION is correct), but the mock assertion
    would fail -- so the side-effect regression is caught.

    Synthetic timestamps: pending took 2s (failed_start - iteration_start
    = 102.0 - 100.0 = 2.0), failed took 3s (iteration_end - failed_start
    = 105.0 - 102.0 = 3.0), total iteration 5s (iteration_end -
    iteration_start = 105.0 - 100.0 = 5.0).
    """
    with (
        patch(
            "gw2analytics_api.workers.stuck_upload_sweeper.STUCK_SWEEPER_PENDING_ITERATION_DURATION"
        ) as pending_mock,
        patch(
            "gw2analytics_api.workers.stuck_upload_sweeper.STUCK_SWEEPER_FAILED_ITERATION_DURATION"
        ) as failed_mock,
        patch(
            "gw2analytics_api.workers.stuck_upload_sweeper.STUCK_SWEEPER_ITERATION_DURATION"
        ) as combined_mock,
    ):
        pending_dur, failed_dur, combined_dur = _observe_sweep_durations(
            iteration_start=100.0,
            failed_start=102.0,
            iteration_end=105.0,
        )

        # Assert the return values (the COMPUTATION contract).
        assert pending_dur == 2.0, (
            "pending duration must be the 2s gap between iteration_start and failed_start"
        )
        assert failed_dur == 3.0, (
            "failed duration must be the 3s gap between failed_start and iteration_end"
        )
        assert combined_dur == 5.0, (
            "combined duration must be the 5s gap between iteration_start and iteration_end"
        )

        # Assert the .observe() side effects (the OBSERVATION contract).
        pending_mock.observe.assert_called_once_with(2.0)
        failed_mock.observe.assert_called_once_with(3.0)
        combined_mock.observe.assert_called_once_with(5.0)
