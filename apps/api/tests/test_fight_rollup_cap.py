"""v0.10.2 hotfix followup #12: per-target roll-up lists are capped at 100 rows.
"""

from __future__ import annotations

import time
import uuid as _uuid

from fastapi.testclient import TestClient
from tests._fixtures import _make_cbtevent, _make_minimal_zevtc

from gw2analytics_api.main import app

client = TestClient(app)


def _wait_for_upload_completion(upload_id: str) -> str:
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        if upload_resp.status_code == 200 and upload_resp.json()["status"] == "completed":
            time.sleep(0.1)
            return str(upload_resp.json()["fight_id"])
        time.sleep(0.1)
    msg = f"upload {upload_id} did not reach 'completed' within 5s"
    raise AssertionError(msg)


def test_target_dps_rollup_capped_at_100_rows() -> None:
    suffix = _uuid.uuid4().hex[:8]
    n_targets = 150
    n_keep = 100
    base_id_player = 200_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    npc_ids = list(range(1_000_000_000, 1_000_000_000 + n_targets))
    base_skill_a = 2_000_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_player, 2, 18, f"CapDpsTester {suffix}", True),
    ]
    for npc_id in npc_ids:
        agents.append((npc_id, 0, 0, f"NPC_{npc_id}", False))

    events: list[bytes] = []
    for i, npc_id in enumerate(npc_ids):
        damage = n_targets - i
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_player,
                dst=npc_id,
                value=damage,
                skill_id=base_skill_a,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build="20240925",
        skills=[(base_skill_a, f"CapDpsSkill {suffix}")],
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    events_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()

    assert len(summary["target_dps"]) == n_keep
    damages = [r["total_damage"] for r in summary["target_dps"]]
    assert damages == sorted(damages, reverse=True)
    assert min(damages) == n_targets - n_keep + 1
    assert max(damages) == n_targets
    dropped = set(range(1, n_targets - n_keep + 1))
    leaked = set(damages) & dropped
    assert not leaked


def test_target_healing_rollup_capped_at_100_rows() -> None:
    suffix = _uuid.uuid4().hex[:8]
    n_targets = 150
    n_keep = 100
    base_id_player = 200_001 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    npc_ids = list(range(1_000_000_000, 1_000_000_000 + n_targets))
    base_skill_a = 2_000_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_player, 2, 18, f"CapHealTester {suffix}", True),
    ]
    for npc_id in npc_ids:
        agents.append((npc_id, 0, 0, f"NPC_{npc_id}", False))

    events: list[bytes] = []
    for i, npc_id in enumerate(npc_ids):
        heal = (n_targets - i) * 10
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_player,
                dst=npc_id,
                value=heal,
                skill_id=base_skill_a,
                is_nondamage=1,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build="20240925",
        skills=[(base_skill_a, f"CapHealSkill {suffix}")],
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    events_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()

    assert len(summary["target_healing"]) == n_keep
    heals = [r["total_healing"] for r in summary["target_healing"]]
    assert heals == sorted(heals, reverse=True)
    assert min(heals) == (n_targets - n_keep + 1) * 10
    assert max(heals) == n_targets * 10
    dropped = {v * 10 for v in range(1, n_targets - n_keep + 1)}
    leaked = set(heals) & dropped
    assert not leaked


def test_target_buff_removal_rollup_capped_at_100_rows() -> None:
    suffix = _uuid.uuid4().hex[:8]
    n_targets = 150
    n_keep = 100
    base_id_player = 200_002 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    npc_ids = list(range(1_000_000_000, 1_000_000_000 + n_targets))
    base_skill_a = 2_000_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_player, 2, 18, f"CapStripTester {suffix}", True),
    ]
    for npc_id in npc_ids:
        agents.append((npc_id, 0, 0, f"NPC_{npc_id}", False))

    events: list[bytes] = []
    for i, npc_id in enumerate(npc_ids):
        strip = (n_targets - i) * 5
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_player,
                dst=npc_id,
                value=0,
                buff_dmg=strip,
                skill_id=base_skill_a,
                is_nondamage=1,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build="20240925",
        skills=[(base_skill_a, f"CapStripSkill {suffix}")],
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    events_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    summary = events_resp.json()

    assert len(summary["target_buff_removal"]) == n_keep
    strips = [r["total_buff_removal"] for r in summary["target_buff_removal"]]
    assert strips == sorted(strips, reverse=True)
    assert min(strips) == (n_targets - n_keep + 1) * 5
    assert max(strips) == n_targets * 5
    dropped = {v * 5 for v in range(1, n_targets - n_keep + 1)}
    leaked = set(strips) & dropped
    assert not leaked


def test_skills_rollup_capped_at_100_rows() -> None:
    suffix = _uuid.uuid4().hex[:8]
    n_skills = 150
    n_keep = 100
    base_id_a = 200_003 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    skill_ids = list(range(3_000_000_000, 3_000_000_000 + n_skills))

    agents: list[tuple[int, int, int, str, bool]] = [
        (base_id_a, 2, 18, f"CapSkillA {suffix}", True),
        (base_id_b, 1, 27, f"CapSkillB {suffix}", True),
    ]

    skills = [(sid, f"Skill_{sid}") for sid in skill_ids]

    events: list[bytes] = []
    for i, sid in enumerate(skill_ids):
        damage = n_skills - i
        events.append(
            _make_cbtevent(
                time_ms=1_000 + i * 100,
                src=base_id_a,
                dst=base_id_b,
                value=damage,
                skill_id=sid,
            ),
        )

    blob = _make_minimal_zevtc(
        agents=agents,
        build="20240925",
        skills=skills,
        events=events,
    )

    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    fight_id = _wait_for_upload_completion(resp.json()["id"])

    skills_resp = client.get(f"/api/v1/fights/{fight_id}/skills")
    assert skills_resp.status_code == 200, skills_resp.text
    payload = skills_resp.json()

    assert len(payload["skills"]) == n_keep
    damages = [r["total_damage"] for r in payload["skills"]]
    assert damages == sorted(damages, reverse=True)
    assert min(damages) == n_skills - n_keep + 1
    assert max(damages) == n_skills
    dropped = set(range(1, n_skills - n_keep + 1))
    leaked = set(damages) & dropped
    assert not leaked
