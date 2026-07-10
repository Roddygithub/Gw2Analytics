"""v0.10.2 hotfix followup regression: process_parse dedups duplicate agent_id.

Background
==========

arcdps can yield the same ``agent_id`` multiple times in a single
fight (a player who switches accounts mid-fight triggers a second
agent struct with the same id but a different name / account_name).
Pre-hotfix, ``process_parse`` would INSERT each agent struct as-is,
and the 2nd INSERT with the same ``(fight_id, agent_id)`` PK would
explode with ``IntegrityError: duplicate key value violates unique
constraint "fight_agents_pkey"``.

Post-hotfix, ``_save_fight`` (in ``services.py``) deduplicates
agents by ``agent_id`` BEFORE the INSERT. The first-seen entry wins
(the parser yields agents in EVTC order, so the FIRST entry is the
one that was active for the longest portion of the fight). A
WARNING log line surfaces the dedup so operators can spot
files where it happens frequently (a WvW log with many account
switches will have many dedup'd entries).

What this test pins
===================

A 1-agent-pair zevtc where the SAME ``agent_id`` appears TWICE
(same id, different names) is parsed cleanly:
- The INSERT does NOT raise ``IntegrityError``.
- The fight_agents table has exactly 1 row for the duplicate
  agent_id (the first-seen entry wins).
- The upload reaches ``status="completed"``.

The test is the minimum-diff regression: 1 duplicate agent pair
exercises the dedup path. A real WvW log with many account switches
will have many duplicates, but the contract is the same.
"""

from __future__ import annotations

import time
import uuid as _uuid

import pytest
from _fixtures import make_minimal_zevtc
from fastapi.testclient import TestClient
from sqlalchemy import Numeric as SANumeric
from sqlalchemy import cast

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import OrmFightAgent

client: TestClient = TestClient(app)


def test_duplicate_agent_id_is_deduped_on_insert() -> None:
    """A 2-agent zevtc sharing 1 agent_id (diff names) persists with 1 fight_agent row.

    Pre-v0.10.2 hotfix followup: the 2nd INSERT with the same
    ``(fight_id, agent_id)`` PK raises ``IntegrityError``. The
    upload flips to ``status="failed"`` and the test fails at
    the ``status == "completed"`` assertion.

    Post-hotfix: the dedup in ``_save_fight`` skips the 2nd
    entry. The fight_agents table has exactly 1 row for the
    duplicate agent_id. The first-seen name wins (the parser
    yields agents in EVTC order; the first entry is the one
    that was active longest in the fight).
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2025{suffix[:4]}" if len(suffix) >= 4 else "20250925"

    # The 2 agents share the SAME agent_id (12345) but have
    # different names. This simulates the arcdps quirk: a player
    # who switches accounts mid-fight triggers a 2nd agent
    # struct with the same id but a different char-name.
    duplicate_agent_id = 12345
    blob = make_minimal_zevtc(
        agents=[
            (duplicate_agent_id, 2, 18, f"FirstName {suffix}", True),
            (duplicate_agent_id, 2, 18, f"SecondName {suffix}", True),
        ],
        build=build,
    )

    # POST the zevtc. The conftest's autouse fixture has set
    # ALLOW_INREQUEST_PARSE_FALLBACK=1 so the route uses the
    # asyncio.to_thread fallback (no Arq worker needed in the
    # test env). The fallback awaits process_parse, so the
    # upload is "completed" by the time the 201 response
    # returns.
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("dedup.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    # Poll for completion. 5s ceiling is generous: the parse
    # is milliseconds for a 2-agent fixture. Pre-hotfix, the
    # 2nd INSERT would raise IntegrityError and the status
    # would flip to "failed" -- the test would fail here.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"upload {upload_id} did not reach terminal status within 5s")
    final_status = upload_resp.json()["status"]
    assert final_status == "completed", (
        f"expected 'completed', got {final_status!r}; "
        f"error_message: {upload_resp.json().get('error_message')!r}"
    )

    # Verify the dedup: exactly 1 fight_agent row for the
    # duplicate agent_id. The first-seen name wins (the parser
    # yields agents in EVTC order).
    with get_sessionmaker()() as db:
        agents = (
            db.query(OrmFightAgent)
            .filter(OrmFightAgent.agent_id == cast(duplicate_agent_id, SANumeric))
            .all()
        )
        assert len(agents) == 1, (
            f"expected exactly 1 fight_agent with the duplicate agent_id, "
            f"got {len(agents)} (dedup failed)"
        )
        assert agents[0].name == f"FirstName {suffix}", (
            f"expected the first-seen name to win, got {agents[0].name!r}"
        )
        assert agents[0].is_player is True
        assert agents[0].profession == 2
        assert agents[0].elite_spec == 18
