"""v0.11.0: _complete_agents creates UNKNOWN entries for agent IDs not in the agent table.

Background
==========

The parser's ``_complete_agents`` function scans all events for
``src_agent`` and ``dst_agent`` values not present in the agent
table and creates synthetic UNKNOWN agent entries for them. This is
critical for WvW logs where the agent table can be incomplete (e.g.
the arcdps agent limit truncation in large fights).

This test verifies the UNKNOWN agent creation through the full API
pipeline: upload → parse → readout.

What this test pins
===================

A 1-player-agent zevtc where events reference an unknown dst agent:
- The parser creates an UNKNOWN entry for the missing agent_id.
- The fight readout includes the UNKNOWN agent.
- The UNKNOWN agent has ``name="UNKNOWN <id>"``, ``is_player=False``,
  ``profession="UNKNOWN"``, ``elite_spec="BASE"`` (``format_elite_spec(0)`` returns ``"BASE"``).
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from _fixtures import make_cbtevent as _make_cbtevent
from _fixtures import make_minimal_zevtc as _make_minimal_zevtc
from fastapi.testclient import TestClient
from test_uploads_helpers import _wait_for_upload_completion

from gw2analytics_api.main import app

client: TestClient = TestClient(app)


def test_unknown_agent_created_when_event_references_missing_id() -> None:
    """A zevtc with events referencing a dst agent not in the table creates an UNKNOWN entry.

    The flow:
      1. Build a zevtc with 1 known player agent (id=1001) and a
         cbtevent where dst=9999 (not in the agent table).
      2. POST → parse → ``_complete_agents`` creates an UNKNOWN
         entry for 9999.
      3. GET /fights/{id} → verify the UNKNOWN agent appears in
         the fight's agents list with the correct fallback fields.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2024{suffix[:4]}" if len(suffix) >= 4 else "20240925"

    player_id = 1001
    unknown_id = 9999

    # 1 known player agent + 1 damage event with dst=9999 (unknown)
    blob = _make_minimal_zevtc(
        agents=[
            (player_id, 2, 18, f"V11 Warrior {suffix}", True),
        ],
        build=build,
        skills=[(500_001, f"Whirlwind {suffix}")],
        events=[
            _make_cbtevent(
                time_ms=1_000,
                src=player_id,
                dst=unknown_id,
                value=100,
                skill_id=500_001,
            ),
        ],
    )

    # POST → parse (in-request fallback)
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("unknown.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    # GET fight detail → agents list includes the UNKNOWN agent
    fight_resp = client.get(f"/api/v1/fights/{fight_id}")
    assert fight_resp.status_code == 200, fight_resp.text
    fight = fight_resp.json()

    # Should have 2 agents: 1 known + 1 UNKNOWN
    assert len(fight["agents"]) == 2, (
        f"expected 2 agents (1 known + 1 UNKNOWN), got {len(fight['agents'])}"
    )

    known = [a for a in fight["agents"] if not a["name"].startswith("UNKNOWN")]
    unknown = [a for a in fight["agents"] if a["name"].startswith("UNKNOWN")]
    assert len(known) == 1, f"expected 1 known agent, got {len(known)}"
    assert len(unknown) == 1, f"expected 1 UNKNOWN agent, got {len(unknown)}"

    # Known agent preserved
    assert known[0]["account_name"] is not None
    assert known[0]["is_player"] is True

    # UNKNOWN agent has fallback fields
    u = unknown[0]
    assert u["name"] == f"UNKNOWN {unknown_id}"
    assert u["is_player"] is False
    assert u["profession"] == "UNKNOWN"
    assert u["elite_spec"] == "BASE"
    assert u["account_name"] is None
    assert u["subgroup"] is None


def test_unknown_agent_src_and_dst_are_separate_entries() -> None:
    """Events referencing different unknown IDs in src AND dst create separate UNKNOWN entries.

    Flow:
      1. Build a zevtc with 1 known player agent + 4 events:
         - 2 events: known → unknown_dst (1001 → 0x9999)
         - 2 events: unknown_src → known_dst (0xAAAA → 1001)
      2. After parse, ``_complete_agents`` creates 2 UNKNOWN entries
         (one for 0x9999, one for 0xAAAA).
      3. GET /fights/{id} → verify 3 agents total (1 known + 2 UNKNOWN).
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2024{suffix[:4]}" if len(suffix) >= 4 else "20240925"

    player_id = 1001
    unknown_dst = 0x9999
    unknown_src = 0xAAAA

    blob = _make_minimal_zevtc(
        agents=[
            (player_id, 1, 27, f"V11 Warrior {suffix}", True),
        ],
        build=build,
        skills=[(500_002, f"Axe {suffix}")],
        events=[
            # 2 events with known → unknown dst (passes _validate_event_candidate)
            _make_cbtevent(1_000, player_id, unknown_dst, 100, 500_002),
            _make_cbtevent(2_000, player_id, unknown_dst, 50, 500_002),
            # 2 events with unknown src → known dst
            _make_cbtevent(3_000, unknown_src, player_id, 75, 500_002),
            _make_cbtevent(4_000, unknown_src, player_id, 25, 500_002),
        ],
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("unknown2.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    fight_resp = client.get(f"/api/v1/fights/{fight_id}")
    assert fight_resp.status_code == 200, fight_resp.text
    fight = fight_resp.json()

    # 1 known + 2 UNKNOWN = 3 agents
    assert len(fight["agents"]) == 3, (
        f"expected 3 agents (1 known + 2 UNKNOWN), got {len(fight['agents'])}"
    )

    known = [a for a in fight["agents"] if not a["name"].startswith("UNKNOWN")]
    unknown = [a for a in fight["agents"] if a["name"].startswith("UNKNOWN")]
    assert len(known) == 1
    assert len(unknown) == 2

    unknown_names = {u["name"] for u in unknown}
    assert f"UNKNOWN {unknown_dst}" in unknown_names, (
        f"UNKNOWN for dst {hex(unknown_dst)} not found in {unknown_names}"
    )
    assert f"UNKNOWN {unknown_src}" in unknown_names, (
        f"UNKNOWN for src {hex(unknown_src)} not found in {unknown_names}"
    )


def test_unknown_agents_dont_leak_between_fights() -> None:
    """UNKNOWN agents from one fight are isolated and NOT shared with another fight.

    Creates 2 separate fights, each with different unknown IDs, and
    verifies the UNKNOWN agents are scoped to their respective fight.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2024{suffix[:4]}" if len(suffix) >= 4 else "20240925"

    player_id_a = 1101
    player_id_b = 1102
    unknown_a = 0xBBBB
    unknown_b = 0xCCCC

    # Fight 1: player 1101 → unknown 0xBBBB
    blob_a = _make_minimal_zevtc(
        agents=[(player_id_a, 2, 18, f"FightA {suffix}", True)],
        build=build,
        skills=[(600_001, f"SkillA {suffix}")],
        events=[_make_cbtevent(1_000, player_id_a, unknown_a, 100, 600_001)],
    )
    resp_a = client.post(
        "/api/v1/uploads",
        files={"file": ("leak_a.zevtc", blob_a, "application/octet-stream")},
    )
    assert resp_a.status_code == 201, resp_a.text
    fight_id_a = _wait_for_upload_completion(resp_a.json()["id"])

    # Fight 2: player 1102 → unknown 0xCCCC
    blob_b = _make_minimal_zevtc(
        agents=[(player_id_b, 2, 18, f"FightB {suffix}", True)],
        build=build,
        skills=[(600_002, f"SkillB {suffix}")],
        events=[_make_cbtevent(1_000, player_id_b, unknown_b, 200, 600_002)],
    )
    resp_b = client.post(
        "/api/v1/uploads",
        files={"file": ("leak_b.zevtc", blob_b, "application/octet-stream")},
    )
    assert resp_b.status_code == 201, resp_b.text
    fight_id_b = _wait_for_upload_completion(resp_b.json()["id"])

    # Fight A: only has UNKNOWN for 0xBBBB, NOT 0xCCCC
    fight_a = client.get(f"/api/v1/fights/{fight_id_a}").json()
    unknown_names_a = {a["name"] for a in fight_a["agents"] if a["name"].startswith("UNKNOWN")}
    assert f"UNKNOWN {unknown_a}" in unknown_names_a
    assert f"UNKNOWN {unknown_b}" not in unknown_names_a, (
        f"Fight A leaked UNKNOWN {hex(unknown_b)} from Fight B"
    )

    # Fight B: only has UNKNOWN for 0xCCCC, NOT 0xBBBB
    fight_b = client.get(f"/api/v1/fights/{fight_id_b}").json()
    unknown_names_b = {a["name"] for a in fight_b["agents"] if a["name"].startswith("UNKNOWN")}
    assert f"UNKNOWN {unknown_b}" in unknown_names_b
    assert f"UNKNOWN {unknown_a}" not in unknown_names_b, (
        f"Fight B leaked UNKNOWN {hex(unknown_a)} from Fight A"
    )


def test_unknown_agents_large_scale_500_entries() -> None:
    """500 events each referencing a different unknown dst agent: all 500 UNKNOWN entries created.

    Simulates a large WvW log where the arcdps agent table is
    truncated and many event-referenced agent IDs are missing.
    The parser's ``_complete_agents`` must create UNKNOWN entries
    for ALL 500 distinct IDs without crashing or timing out.
    The fight readout must include all 500 UNKNOWN agents.
    """
    suffix = _uuid.uuid4().hex[:8]
    build = f"2024{suffix[:4]}" if len(suffix) >= 4 else "20240925"

    n_unknown = 500
    player_id = 1001
    unknown_ids = list(range(500_000, 500_000 + n_unknown))

    events: list[bytes] = []
    for i, uid in enumerate(unknown_ids):
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 10,
                src=player_id,
                dst=uid,
                value=100,
                skill_id=500_001,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=[
            (player_id, 2, 18, f"V11 Mass {suffix}", True),
        ],
        build=build,
        skills=[(500_001, f"MassSkill {suffix}")],
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("mass_unknown.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    fight_resp = client.get(f"/api/v1/fights/{fight_id}")
    assert fight_resp.status_code == 200, fight_resp.text
    fight = fight_resp.json()

    # 1 known + 500 UNKNOWN = 501 agents
    assert len(fight["agents"]) == 1 + n_unknown, (
        f"expected {1 + n_unknown} agents (1 known + {n_unknown} UNKNOWN), "
        f"got {len(fight['agents'])}"
    )

    known = [a for a in fight["agents"] if not a["name"].startswith("UNKNOWN")]
    unknown = [a for a in fight["agents"] if a["name"].startswith("UNKNOWN")]
    assert len(known) == 1
    assert len(unknown) == n_unknown

    # All 500 UNKNOWN IDs are present
    unknown_ids_found = set()
    for u in unknown:
        # Parse the integer from "UNKNOWN <id>"
        parts = u["name"].split()
        assert len(parts) == 2
        assert parts[0] == "UNKNOWN"
        uid = int(parts[1])
        unknown_ids_found.add(uid)
        assert u["is_player"] is False
        assert u["profession"] == "UNKNOWN"
        assert u["elite_spec"] == "BASE"
        assert u["account_name"] is None
        assert u["subgroup"] is None

    assert unknown_ids_found == set(unknown_ids), (
        f"UNKNOWN IDs mismatch: expected {len(set(unknown_ids))} unique IDs, "
        f"found {len(unknown_ids_found)}"
    )

    # Known player preserved
    assert known[0]["account_name"] is not None
    assert known[0]["is_player"] is True

    # Verify the event roll-up is still functional with 501 agents
    events_resp = client.get(
        f"/api/v1/fights/{fight_id}/events",
        params={"window_s": 10},
    )
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()
    assert summary["duration_s"] == pytest.approx((1_000 + (n_unknown - 1) * 10) / 1000, rel=0.1)
    # target_dps has 500 rows (capped at 100 by the rollup cap)
    assert len(summary["target_dps"]) == 100, (
        f"target_dps should be capped at 100 rows, got {len(summary['target_dps'])}"
    )
