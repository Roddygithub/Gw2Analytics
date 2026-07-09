"""v0.10.2 hotfix followup #3: dedup duplicate ``skill_id`` in ``_save_fight``.

Background
==========

arcdps can yield the same ``skill_id`` multiple times in a single
fight -- the parser misreads the skill table when ``name_len`` is
garbage from the event stream (the ``MAX_SKILL_NAME_BYTES`` check
in :mod:`gw2_evtc_parser` surfaces the boundary as a WARNING and
stops reading, but the YIELDED skills before the cut-off can share
ids). Pre-hotfix, ``process_parse`` would INSERT each skill struct
as-is, and the 2nd INSERT with the same ``(fight_id, skill_id)``
composite PK would explode with ``IntegrityError: duplicate key
value violates unique constraint "pk_fight_skills"``.

Post-hotfix, ``_save_fight`` (in ``services.py``) deduplicates
skills by ``skill_id`` BEFORE the INSERT, mirroring the existing
agent dedup from the previous hotfix followup. First-seen wins
(the parser yields skills in EVTC order, so the FIRST entry is the
canonical one).

What this test pins
===================

A 1-fight zevtc where the SAME ``skill_id`` appears TWICE (same id,
different names) parses + persists with 1 ``fight_skills`` row:
- The INSERT does NOT raise ``IntegrityError``.
- The ``fight_skills`` table has exactly 1 row for the duplicate
  ``skill_id`` (the first-seen name wins).
- The upload reaches ``status="completed"``.
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

client: TestClient = TestClient(app)


def test_duplicate_skill_id_is_deduped_on_insert() -> None:
    """A zevtc with 2 skill structs sharing the same skill_id (diff names) persists with 1 row.

    Pre-v0.10.2 hotfix followup #3: the 2nd INSERT with the same
    ``(fight_id, skill_id)`` PK raises ``IntegrityError``. The
    upload flips to ``status="failed"`` and the test fails at
    the ``status == "completed"`` assertion.

    Post-hotfix: the dedup in ``_save_fight`` skips the 2nd
    entry. The ``fight_skills`` table has exactly 1 row for the
    duplicate ``skill_id``. The first-seen name wins (the parser
    yields skills in EVTC order; the first entry is the canonical
    one).
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    # The 2 skills share the SAME skill_id (99999) but have
    # different names. This simulates the arcdps parser quirk:
    # malformed skill tables yield duplicate ids with garbage
    # names (the parser's MAX_SKILL_NAME_BYTES check stops
    # reading at the cut-off, but the yielded skills before
    # the cut-off can share ids).
    duplicate_skill_id = 99999
    blob = make_minimal_zevtc(
        agents=[(11111, 2, 18, f"Player {suffix}", True)],
        skills=[
            (duplicate_skill_id, f"FirstSkill {suffix}"),
            (duplicate_skill_id, f"SecondSkill {suffix}"),
        ],
        build=build,
    )

    # POST the zevtc. The conftest's autouse fixture sets
    # ALLOW_INREQUEST_PARSE_FALLBACK=1 so the route uses the
    # asyncio.to_thread fallback (no Arq worker needed in the
    # test env). The fallback awaits process_parse, so the
    # upload is "completed" by the time the 201 response
    # returns.
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("dedup_skills.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    # Poll for completion. 5s ceiling is generous: the parse
    # is milliseconds for a 1-agent/2-skill fixture. Pre-hotfix,
    # the 2nd INSERT would raise IntegrityError and the status
    # would flip to "failed" -- the test would fail here.
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

    # Verify the dedup: exactly 1 fight_skill row for the
    # duplicate skill_id. The first-seen name wins (the parser
    # yields skills in EVTC order).
    with get_sessionmaker()() as db:
        skills = (
            db.query(OrmFightSkill)
            .filter(OrmFightSkill.skill_id == cast(duplicate_skill_id, BigInteger))
            .all()
        )
        assert len(skills) == 1, (
            f"expected exactly 1 fight_skill with the duplicate skill_id, "
            f"got {len(skills)} (dedup failed)"
        )
        assert skills[0].name == f"FirstSkill {suffix}", (
            f"expected the first-seen name to win, got {skills[0].name!r}"
        )
