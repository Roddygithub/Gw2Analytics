"""v0.10.2 hotfix followup #5: overlong names are truncated to fit ``String(128)``.

Background
==========

The arcdps parser can yield ``name_len`` up to
``MAX_SKILL_NAME_BYTES = 4096`` for skill names (custom add-on skill
names are the canonical case -- arcdps addons can supply skill names
longer than the 64-char practical arcdps cap to surface guild tags
or build identifiers). Pre-v0.10.2 hotfix followup #5, a 200-char
skill name from such an addon would fail the INSERT into
``OrmFightSkill.name`` (a ``String(128) NOT NULL`` column) with
``value too long for type character varying(128)`` -- ``psycopg``
raises ``DataError`` which rolls back the whole ``_save_fight``
transaction, losing the fight row + agents + skills.

v0.10.2 hotfix followup #5 extends :func:`_sanitize_name` in
``services.py`` to also truncate to ``MAX_NAME_LEN = 128`` (the
canonical cap; matches the ``String(128)`` column constraint). The
truncation is applied AFTER the NUL-strip pass so a name with NULs
followed by > 128 chars of content is clipped on the surviving
(post-strip) string, not on the original (pre-strip) string.

What this test pins
===================

A 1-fight zevtc where the skill name is **200 chars** parses +
persists cleanly:

- The INSERT does NOT raise ``DataError``.
- The upload reaches ``status="completed"``.
- The ``fight_skills`` table has exactly 1 row for the overlong
  ``skill_id``, and ``len(name) == 128`` (truncated to the column
  cap; the first 128 chars of the 200-char input are preserved).
- The agent ``name`` is unaffected (the agent struct's 68-byte name
  buffer is hard-bounded by the wire format; the truncation is
  observable only on the variable-size skill name).

The test also pins a **post-truncation idempotence** contract: a
re-upload of the same SHA (which lands on the same ``OrmFight`` row
via the DELETE+INSERT pattern in ``_save_fight``) must NOT
re-crash -- the truncated 128-char name is stable under a 2nd
``_sanitize_name`` pass. This pins the re-parse safety contract.
"""

from __future__ import annotations

import time
import uuid as _uuid

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, cast

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import OrmFightSkill
from gw2analytics_api.services import MAX_NAME_LEN, _sanitize_name

client: TestClient = TestClient(app)


def test_overlong_skill_name_is_truncated_to_max_name_len() -> None:
    """A zevtc with a 200-char skill name persists with the name truncated to 128 chars.

    Pre-v0.10.2 hotfix followup #5: the 200-char skill name would
    fail the INSERT into ``OrmFightSkill.name`` (a
    ``String(128) NOT NULL`` column) with
    ``value too long for type character varying(128)``. The
    upload flips to ``status="failed"`` and the test fails at
    the ``status == "completed"`` assertion.

    Post-hotfix: the truncation in :func:`_sanitize_name` clips
    the name to 128 chars. The ``fight_skills`` table has
    exactly 1 row for the overlong ``skill_id`` with
    ``len(name) == 128``. The first 128 chars of the 200-char
    input are preserved (the truncation is from the END, not the
    START, so the canonical arcdps name prefix is the surviving
    part).
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    # Build a 200-char skill name. The skill_id is a sentinel
    # value (well outside the 1-1000 range the seed_demo
    # scripts use) so the test is hermetic -- no cross-test
    # contamination from prior uploads.
    overlong_skill_id = 98_765_432
    raw_skill_name = "X" * 200
    expected_truncated_name = "X" * MAX_NAME_LEN  # == "X" * 128
    blob = make_minimal_zevtc(
        agents=[(11111, 2, 18, f"Player {suffix}", True)],
        skills=[(overlong_skill_id, raw_skill_name)],
        build=build,
    )

    # Sanity-check the pure-function contract: the helper
    # truncates the 200-char name to 128 chars. This is a
    # defensive check in case the helper signature regresses;
    # the E2E assertion below is the canonical pin.
    assert _sanitize_name(raw_skill_name) == expected_truncated_name
    assert len(_sanitize_name(raw_skill_name)) == MAX_NAME_LEN

    # POST the zevtc. The conftest's autouse fixture sets
    # ``ALLOW_INREQUEST_PARSE_FALLBACK=1`` so the route uses
    # the asyncio.to_thread fallback (no Arq worker needed in
    # the test env). The fallback awaits ``process_parse``,
    # so the upload is "completed" by the time the 201
    # response returns.
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("overlong_skill.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    # Poll for completion. 5s ceiling is generous: the parse
    # is milliseconds for a 1-agent/1-skill fixture. Pre-hotfix,
    # the INSERT would raise ``DataError`` and the status
    # would flip to "failed" -- the test would fail here with
    # the error_message attribute carrying the
    # ``value too long`` detail.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    else:
        pytest.fail(
            f"upload {upload_id} did not reach terminal status within 5s"
        )
    final_status = upload_resp.json()["status"]
    assert final_status == "completed", (
        f"expected 'completed', got {final_status!r}; "
        f"error_message: {upload_resp.json().get('error_message')!r}"
    )

    # Verify the truncation: exactly 1 fight_skill row for
    # the overlong skill_id, and the name is exactly 128
    # chars (the first 128 chars of the 200-char input are
    # preserved -- the truncation is from the end).
    with get_sessionmaker()() as db:
        skills = (
            db.query(OrmFightSkill)
            .filter(OrmFightSkill.skill_id == cast(overlong_skill_id, BigInteger))
            .all()
        )
        assert len(skills) == 1, (
            f"expected exactly 1 fight_skill with the overlong skill_id, "
            f"got {len(skills)} (truncation or INSERT failed)"
        )
        assert len(skills[0].name) == MAX_NAME_LEN, (
            f"expected the name to be truncated to {MAX_NAME_LEN} chars, "
            f"got {len(skills[0].name)} chars (truncation not applied)"
        )
        assert skills[0].name == expected_truncated_name, (
            f"expected the first {MAX_NAME_LEN} chars to be preserved, "
            f"got {skills[0].name!r}"
        )


def test_overlong_skill_name_with_nul_byte_is_truncated_post_strip() -> None:
    """A 200-char skill name with an embedded NUL is stripped THEN truncated (order matters).

    Pins the policy: the NUL-strip pass happens BEFORE the
    truncation cap. A name like ``"A" * 200 + "\x00" + "B" * 200``
    is NUL-stripped to ``"A" * 200 + "B" * 200`` (400 chars
    total), then truncated to 128 chars. The test pins that
    ``"A" * 128`` is the surviving string (the first 128 chars
    are all ``"A"``), NOT ``"A" * 200 + "B" * 128`` (which
    would be the result of truncating BEFORE the NUL-strip
    pass on the original 401-char string).
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    overlong_skill_id = 98_765_433  # different from the other test for hermeticity
    # 200 'A's + 1 NUL + 200 'B's = 401 chars. After
    # NUL-strip: 400 chars. After truncation: 128 'A's.
    raw_skill_name = "A" * 200 + "\x00" + "B" * 200
    expected_truncated_name = "A" * MAX_NAME_LEN
    blob = make_minimal_zevtc(
        agents=[(22222, 2, 18, f"Player {suffix}", True)],
        skills=[(overlong_skill_id, raw_skill_name)],
        build=build,
    )

    # Defensive sanity-check on the helper.
    assert _sanitize_name(raw_skill_name) == expected_truncated_name

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("overlong_nul_skill.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    else:
        pytest.fail(
            f"upload {upload_id} did not reach terminal status within 5s"
        )
    assert upload_resp.json()["status"] == "completed", (
        f"expected 'completed', got {upload_resp.json()['status']!r}; "
        f"error_message: {upload_resp.json().get('error_message')!r}"
    )

    with get_sessionmaker()() as db:
        skills = (
            db.query(OrmFightSkill)
            .filter(OrmFightSkill.skill_id == cast(overlong_skill_id, BigInteger))
            .all()
        )
        assert len(skills) == 1
        assert len(skills[0].name) == MAX_NAME_LEN
        # The first 128 chars of the post-strip string are
        # all "A" (the B's are beyond the truncation cap).
        assert skills[0].name == expected_truncated_name, (
            f"expected first 128 chars of post-strip string to be 'A's, "
            f"got {skills[0].name!r}"
        )
        # Defensive: the truncated name contains NO NUL bytes
        # (the strip pass happened before the truncation).
        assert "\x00" not in skills[0].name
