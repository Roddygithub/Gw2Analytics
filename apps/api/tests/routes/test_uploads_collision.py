"""v0.10.28 plan 160 regression: fight_id collision handler marks upload as failed.

Background
==========

The :class:`gw2_analytics.Fight.id` field is content-derived from the
parsed EVTC (a deterministic hash of the fight's signature). When
2 distinct uploads contain the SAME parsed fight content, the 2nd
``_save_fight`` call inserts an ``OrmFight`` row with a duplicate
``id`` column, firing Postgres's ``unique constraint`` violation.

Pre-v0.10.28 plan 160: the ``IntegrityError`` propagated up to
:func:`process_parse`'s generic ``except (RuntimeError, ValueError)``
clause (which did NOT catch ``IntegrityError`` -- a subclass of
``SQLAlchemyError``) and surfaced as a bare ``"IntegrityError: ..."``
message in ``upload.error_message``. Operators had no way to pivot
to the existing successful parse via ``/fights/{existing_id}``.

Post-v0.10.28 plan 160: the ``IntegrityError`` is caught SPECIFICALLY
in :func:`process_parse`, immediately after ``_save_fight`` +
``_persist_event_blob``. The handler:

1. Logs a warning with the colliding ``upload_id`` + ``core_fight.id``.
2. Calls ``db.rollback()`` to discard the failed transaction.
3. Re-fetches the ``Upload`` row via ``db.get(Upload, upload_id)``
   (SQLAlchemy expires ALL session objects after ``rollback()`` --
   the original ``upload`` is detached + mutating it would raise
   ``DetachedInstanceError``).
4. Sets ``upload.status = 'failed'`` + ``upload.error_message =
   f"The content is already analyzed as fight {core_fight.id}"``
   so an operator can pivot to the prior successful parse via
   ``GET /api/v1/fights/{existing_id}``.
5. Commits the status change.
6. Returns early so the upload does NOT flip to ``completed``.

The audit row is preserved (no DELETE) so the duplicate upload is
still inspectable via ``GET /api/v1/uploads/{id}``.

What this test pins
===================

A ``_save_fight`` ``IntegrityError`` (mocked at the parse.py namespace)
during a valid POST surfaces as:

- ``upload.status == 'failed'``
- ``upload.error_message`` contains the literal phrase
  ``"The content is already analyzed as fight"``
- ``upload.error_message`` ends with a parseable UUID
  (the ``core_fight.id`` surfaced for operator pivot)
- The ``Upload`` row still exists in the DB (audit trail preserved)

Mocking strategy
================

``_save_fight`` is patched at the parse.py namespace
(``gw2analytics_api.services.parse._save_fight``) because that is
where the import lives -- patching the source namespace
(``gw2analytics_api.services.fight_persistence._save_fight``) would
not reach the call site. This mirrors the monkeypatch contract
documented in :mod:`gw2analytics_api.routes.fights.aggregators`'s
module docstring.

The IntegrityError is constructed with the canonical 3-arg signature
(``statement``, ``params``, ``orig``). ``params=None`` + ``orig`` set
to a stub ``Exception`` is the minimum-diff construction that
matches the production shape (SQLAlchemy's real IntegrityError in
the collision path includes a ``UniqueViolation`` wrapped orig).
"""

from __future__ import annotations

import re
import time
import uuid as _uuid
from unittest.mock import patch

# NOTE: _uuid.UUID is still used for upload_id parsing below
# but fight_id is now SHA-256 hex (gw2_core Fight.id).
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import UPLOAD_STATUS_FAILED, Upload

client: TestClient = TestClient(app)


def test_fight_id_collision_marks_upload_failed_with_pivot_id() -> None:
    """Plan 160: a duplicate ``OrmFight.id`` surfaces as a pivoted failure.

    Pre-v0.10.28 plan 160: the ``IntegrityError`` from the unique
    ``OrmFight.id`` constraint propagated up to ``process_parse``'s
    generic exception handler with a bare ``"IntegrityError: ..."``
    message. Operators had no way to discover the existing
    successful fight.

    Post-v0.10.28 plan 160: the ``IntegrityError`` is caught
    specifically; the upload is marked ``status='failed'`` with
    ``error_message="The content is already analyzed as fight
    {core_fight.id}"``. The audit row is preserved so the duplicate
    upload remains inspectable via ``GET /api/v1/uploads/{id}``.
    """
    suffix = _uuid.uuid4().hex[:8]
    blob = make_minimal_zevtc(
        agents=[(100_001, 2, 18, f"Collision Test {suffix}", True)],
        build="20251023",
    )

    # Patch _save_fight at the parse.py namespace (where it was
    # imported). Patching the source namespace would not reach
    # the call site. The IntegrityError mirrors the production
    # shape (statement + params + orig).
    with patch(
        "gw2analytics_api.services.parse._save_fight",
        side_effect=IntegrityError(
            statement="INSERT INTO fights (...) VALUES (...)",
            params=None,
            orig=Exception('duplicate key value violates unique constraint "fights_pkey"'),
        ),
    ):
        resp = client.post(
            "/api/v1/uploads",
            files={
                "file": (
                    f"collision_{suffix}.zevtc",
                    blob,
                    "application/octet-stream",
                ),
            },
        )

    # The 201 is returned synchronously by the route handler before
    # the parse runs (the parse runs in the asyncio.to_thread
    # fallback). The IntegrityError surfaces in the polling loop
    # below as a failed terminal status.
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    # Poll for terminal status. 5s ceiling is generous: the parse
    # is milliseconds for a 1-agent fixture.
    deadline = time.monotonic() + 5.0
    upload_resp = None
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    else:
        raise AssertionError(
            f"upload {upload_id} did not reach terminal status within 5s "
            f"(last seen: {upload_resp.json() if upload_resp else 'no response'})"
        )

    final = upload_resp.json()
    assert final["status"] == UPLOAD_STATUS_FAILED, (
        f"expected status='failed' after IntegrityError, got {final['status']!r}; "
        f"error_message: {final.get('error_message')!r}"
    )
    # The pivoted error message must contain the literal phrase
    # so operators can find it via /fights/{existing_id}.
    assert "The content is already analyzed as fight" in (final["error_message"] or ""), (
        f"error_message must include the pivot phrase; got {final['error_message']!r}"
    )
    # The pivot id at the end of the message must be a valid
    # fight_id.  gw2_core Fight.id is a SHA-256 hex digest
    # (64 hex chars), not a UUID.
    pivot_match = re.search(
        r"fight ([0-9a-fA-F]{64})",
        final["error_message"] or "",
    )
    assert pivot_match is not None, (
        f"error_message must contain a 64-char hex fight_id; got {final['error_message']!r}"
    )
    # Sanity: the matched string is valid lowercase hex.
    assert len(pivot_match.group(1)) == 64

    # Audit trail preservation: the upload row must STILL exist in
    # the DB (no DELETE). Operators can re-inspect the failed
    # upload via GET /api/v1/uploads/{id}.
    with get_sessionmaker()() as db:
        upload_row = db.query(Upload).filter(Upload.id == upload_id).one_or_none()
        assert upload_row is not None, (
            "upload row was deleted after IntegrityError "
            "(audit trail lost; plan 160 explicitly preserves it)"
        )
        assert upload_row.status == UPLOAD_STATUS_FAILED
        assert "already analyzed as fight" in (upload_row.error_message or "")


def test_event_blob_collision_marks_upload_failed_with_distinct_message() -> None:
    """Plan 160 NICE-to-HAVE: a duplicate in ``_persist_event_blob``
    surfaces as a DISTINCT error message (NOT the fight_id pivot phrase).

    Pre-fix: the broad ``try/except IntegrityError`` wrapped both
    ``_save_fight`` and ``_persist_event_blob`` -- an event-blob
    collision would surface with the fight_id pivot phrase
    ("already analyzed as fight X") which is misleading because
    the existing fight WAS analyzed; the blob INSERT failed.

    Post-fix: the TWO narrow try/except blocks each have a
    distinct error message. The event-blob collision message
    ("Event blob persistence collision for fight X") tells the
    operator which LAYER fired, not which fight.

    The audit row is still preserved (no DELETE).
    """
    suffix = _uuid.uuid4().hex[:8]
    blob = make_minimal_zevtc(
        agents=[(100_002, 2, 18, f"EventBlob Collision {suffix}", True)],
        build="20251024",
    )

    with patch(
        "gw2analytics_api.services.parse._persist_event_blob",
        side_effect=IntegrityError(
            statement="INSERT INTO events (...) VALUES (...)",
            params=None,
            orig=Exception('duplicate key value violates unique constraint "events_pkey"'),
        ),
    ):
        resp = client.post(
            "/api/v1/uploads",
            files={
                "file": (
                    f"event_blob_collision_{suffix}.zevtc",
                    blob,
                    "application/octet-stream",
                ),
            },
        )

    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    deadline = time.monotonic() + 5.0
    upload_resp = None
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    else:
        raise AssertionError(
            f"upload {upload_id} did not reach terminal status within 5s "
            f"(last seen: {upload_resp.json() if upload_resp else 'no response'})"
        )

    final = upload_resp.json()
    assert final["status"] == UPLOAD_STATUS_FAILED, (
        f"expected status='failed' after event_blob IntegrityError, "
        f"got {final['status']!r}; error_message: {final.get('error_message')!r}"
    )
    assert "already analyzed as fight" not in (final["error_message"] or ""), (
        f"event_blob collision must NOT surface with the fight_id pivot phrase; "
        f"got {final['error_message']!r}"
    )
    assert "Event blob persistence collision" in (final["error_message"] or ""), (
        f"event_blob collision must include the distinct layer-specific phrase; "
        f"got {final['error_message']!r}"
    )

    with get_sessionmaker()() as db:
        upload_row = db.query(Upload).filter(Upload.id == upload_id).one_or_none()
        assert upload_row is not None, (
            "upload row was deleted after event_blob IntegrityError (audit trail lost)"
        )
        assert upload_row.status == UPLOAD_STATUS_FAILED
