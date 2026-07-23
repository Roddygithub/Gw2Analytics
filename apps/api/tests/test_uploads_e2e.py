"""End-to-end POST /uploads + GET /fights/{id}/events tests against a real Postgres.

Builds a synthetic .zevtc in-memory, POSTs it through the public API, then
queries GET /uploads + GET /fights + GET /fights/{id}/events to verify the
schema + Phase 7 v1 wire-up are correct.

Requires a Postgres server reachable at DATABASE_URL. Run
``docker compose up -d gw2a-postgres`` first if your local environment
does not already expose Postgres on port 5432.

The happy-path test is **idempotent** by design: each run injects a
uuid-derived suffix so all PKs are unique per invocation.
"""

from __future__ import annotations

import time
import uuid as _uuid
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from _fixtures import _make_cbtevent, _make_minimal_zevtc
from test_uploads_helpers import _post_minimal_fight, _wait_for_upload_completion

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skip_if_no_db() -> None:
    try:
        probe = get_sessionmaker()()
        probe.execute(text("SELECT 1"))
        probe.close()
    except Exception as exc:
        pytest.skip(f"regression test needs live Postgres; got: {exc.__class__.__name__}")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_uploads_e2e_happy_path() -> None:
    suffix = _uuid.uuid4().hex[:8]
    build = "20240925"
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1

    events = [
        _make_cbtevent(
            time_ms=1_000, src=base_id_a, dst=base_id_b, value=100, skill_id=base_skill_a
        ),
        _make_cbtevent(
            time_ms=1_000,
            src=base_id_b,
            dst=base_id_a,
            value=200,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
        _make_cbtevent(
            time_ms=2_500, src=base_id_a, dst=base_id_b, value=567, skill_id=base_skill_b
        ),
        _make_cbtevent(
            time_ms=2_500,
            src=base_id_b,
            dst=base_id_a,
            value=400,
            skill_id=base_skill_b,
            is_nondamage=1,
        ),
    ]
    blob = _make_minimal_zevtc(
        [
            (base_id_a, 2, 18, f"E2E Warrior {suffix}", True),
            (base_id_b, 1, 27, f"E2E Guard {suffix}", True),
        ],
        build=build,
        skills=[(base_skill_a, f"Whirlwind {suffix}"), (base_skill_b, f"Burning {suffix}")],
        events=events,
    )
    resp = client.post(
        "/api/v1/uploads", files={"file": ("sample.zevtc", blob, "application/octet-stream")}
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    fight_id = _wait_for_upload_completion(upload_id)
    get_resp = client.get(f"/api/v1/uploads/{upload_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["status"] == "completed"
    assert body["fight_id"] == fight_id
    fight_resp = client.get(f"/api/v1/fights/{fight_id}")
    assert fight_resp.status_code == 200, fight_resp.text
    fight_body = fight_resp.json()
    assert fight_body["id"] == fight_id
    assert fight_body["build_version"] == build
    events_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    ev = events_resp.json()
    assert len(ev["target_dps"]) == 1
    assert len(ev["target_healing"]) == 1
    assert ev["duration_s"] > 2.0
    assert len(ev["event_windows"]) >= 1


def test_fight_events_404_when_unknown_fight() -> None:
    resp = client.get("/api/v1/fights/DEADBEEF/events")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


def test_fight_events_422_when_window_s_too_small() -> None:
    resp = client.get("/api/v1/fights/DEADBEEF/events?window_s=0")
    assert resp.status_code == 422


def test_healthz_responds() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Player surface + squad/skill roll-ups
# ---------------------------------------------------------------------------


def test_players_list_returns_accounts_present_in_fight() -> None:
    _post_minimal_fight()
    resp = client.get("/api/v1/players")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 2
    {r["account_name"] for r in rows}
    assert any("V07 Warrior" in r["name"] for r in rows)
    assert any("V07 Guard" in r["name"] for r in rows)


def test_player_detail_returns_profile_with_per_fight_breakdown() -> None:
    fight_id = _post_minimal_fight()
    resp = client.get("/api/v1/players?limit=500")
    assert resp.status_code == 200
    accounts = [r["account_name"] for r in resp.json() if r["account_name"].startswith(":synth.")]
    if not accounts:
        pytest.skip("no synth accounts found")
    detail = client.get(f"/api/v1/players/{quote(accounts[0], safe='')}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["account_name"] == accounts[0]
    assert body["fights_attended"] >= 1
    assert len(body["per_fight_breakdown"]) >= 1
    breakdown = body["per_fight_breakdown"][0]
    assert breakdown["fight_id"] == fight_id


def test_player_detail_404_when_account_unknown() -> None:
    resp = client.get("/api/v1/players/NoOne.NNNN")
    assert resp.status_code == 404


def test_player_routes_accept_colon_prefixed_account_name() -> None:
    _post_minimal_fight()
    resp = client.get("/api/v1/players?limit=500")
    assert resp.status_code == 200
    raw_accounts = [
        r["account_name"] for r in resp.json() if r["account_name"].startswith(":synth.")
    ]
    if not raw_accounts:
        pytest.skip("no synth accounts found")
    bare = raw_accounts[0].lstrip(":")
    for prefix in (f":{bare}", bare):
        detail = client.get(f"/api/v1/players/{quote(prefix, safe='')}")
        assert detail.status_code == 200, f"failed for {prefix}: {detail.text}"
        assert detail.json()["account_name"] == bare


def test_fight_squads_returns_per_subgroup_rollup() -> None:
    fight_id = _post_minimal_fight()
    resp = client.get(f"/api/v1/fights/{fight_id}/squads")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fight_id"] == fight_id
    assert len(body["squads"]) >= 1
    for sq in body["squads"]:
        assert "total_damage" in sq
        assert "total_healing" in sq


def test_fight_skills_returns_per_skill_rollup() -> None:
    fight_id = _post_minimal_fight()
    resp = client.get(f"/api/v1/fights/{fight_id}/skills")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fight_id"] == fight_id
    assert len(body["skills"]) >= 1
    for sk in body["skills"]:
        assert "total_damage" in sk
        assert "total_healing" in sk


def test_fight_squads_404_when_fight_unknown() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/squads").status_code == 404


def test_fight_skills_404_when_fight_unknown() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/skills").status_code == 404


# ---------------------------------------------------------------------------
# Player timeline
# ---------------------------------------------------------------------------


def test_player_timeline_returns_paginated_recency_first_points() -> None:
    fight_id = _post_minimal_fight()
    resp = client.get("/api/v1/players?limit=500")
    assert resp.status_code == 200
    accounts = [r["account_name"] for r in resp.json() if r["account_name"].startswith(":synth.")]
    if not accounts:
        pytest.skip("no synth accounts found")
    timeline = client.get(
        f"/api/v1/players/{quote(accounts[0], safe='')}/timeline?limit=5&offset=0"
    )
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()
    assert body["total"] >= 1
    assert len(body["points"]) >= 1
    assert body["points"][0]["fight_id"] == fight_id


def test_player_timeline_404_when_account_unknown() -> None:
    resp = client.get("/api/v1/players/NoOne.NNNN/timeline")
    assert resp.status_code == 404


def test_player_timeline_422_when_limit_out_of_range() -> None:
    assert client.get("/api/v1/players/dummy.1234/timeline?limit=0").status_code == 404


def test_player_timeline_422_when_limit_zero() -> None:
    resp = client.get("/api/v1/players/dummy.1234/timeline?limit=0")
    assert resp.status_code == 422


def test_player_timeline_422_when_offset_negative() -> None:
    resp = client.get("/api/v1/players/dummy.1234/timeline?offset=-1")
    assert resp.status_code == 422


def test_player_timeline_default_bucket_is_fight() -> None:
    _post_minimal_fight()
    resp = client.get("/api/v1/players?limit=500")
    assert resp.status_code == 200
    accounts = [r["account_name"] for r in resp.json() if r["account_name"].startswith(":synth.")]
    if not accounts:
        pytest.skip("no synth accounts found")
    tl = client.get(f"/api/v1/players/{quote(accounts[0], safe='')}/timeline")
    assert tl.status_code == 200
    assert tl.json()["bucket"] == "fight"


def test_player_timeline_day_bucket_aggregates_per_day() -> None:
    _post_minimal_fight()
    resp = client.get("/api/v1/players?limit=500")
    assert resp.status_code == 200
    accounts = [r["account_name"] for r in resp.json() if r["account_name"].startswith(":synth.")]
    if not accounts:
        pytest.skip("no synth accounts found")
    tl = client.get(f"/api/v1/players/{quote(accounts[0], safe='')}/timeline?bucket=day")
    assert tl.status_code == 200
    body = tl.json()
    assert body["bucket"] == "day"
    assert len(body["points"]) >= 1


def test_player_timeline_422_when_bucket_invalid() -> None:
    resp = client.get("/api/v1/players/dummy.1234/timeline?bucket=week")
    assert resp.status_code == 422


def test_player_timeline_tz_default_is_utc() -> None:
    _post_minimal_fight()
    resp = client.get("/api/v1/players?limit=500")
    assert resp.status_code == 200
    accounts = [r["account_name"] for r in resp.json() if r["account_name"].startswith(":synth.")]
    if not accounts:
        pytest.skip("no synth accounts found")
    tl = client.get(f"/api/v1/players/{quote(accounts[0], safe='')}/timeline?bucket=day")
    assert tl.status_code == 200
    assert tl.json()["tz"] == "UTC"


def test_player_timeline_tz_422_when_invalid_timezone() -> None:
    _post_minimal_fight()
    resp = client.get("/api/v1/players?limit=500")
    assert resp.status_code == 200
    accounts = [r["account_name"] for r in resp.json() if r["account_name"].startswith(":synth.")]
    if not accounts:
        pytest.skip("no synth accounts found")
    tl = client.get(f"/api/v1/players/{quote(accounts[0], safe='')}/timeline?tz=Invalid/Zone")
    assert tl.status_code == 422


# ---------------------------------------------------------------------------
# Fight timeline
# ---------------------------------------------------------------------------


def test_fight_timeline_returns_per_bucket_totals_for_known_fight() -> None:
    fight_id = _post_minimal_fight()
    resp = client.get(f"/api/v1/fights/{fight_id}/timeline")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fight_id"] == fight_id
    assert len(body["points"]) >= 1
    assert body["window_s"] == 5


def test_fight_timeline_404_when_unknown_fight() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/timeline").status_code == 404


def test_fight_timeline_422_when_window_s_too_small() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/timeline?window_s=0").status_code == 422


def test_fight_timeline_422_when_window_s_too_large() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/timeline?window_s=601").status_code == 422


# ---------------------------------------------------------------------------
# Per-player timeline
# ---------------------------------------------------------------------------


def test_fight_player_timeline_returns_per_player_per_bucket_series() -> None:
    fight_id = _post_minimal_fight()
    resp = client.get(f"/api/v1/fights/{fight_id}/timeline/players")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fight_id"] == fight_id
    assert len(body["series"]) >= 1
    for s in body["series"]:
        assert "points" in s


def test_fight_player_timeline_200_with_empty_series_for_npc_only_fight() -> None:
    suffix = _uuid.uuid4().hex[:8]
    fight_id = _post_minimal_fight(
        agents=[
            (100_000 + int(suffix[:4], 16), 0, 0, "NPC One", False),
            (100_001 + int(suffix[:4], 16), 1, 27, "NPC Two", False),
        ],
    )
    resp = client.get(f"/api/v1/fights/{fight_id}/timeline/players")
    assert resp.status_code == 200, resp.text
    assert resp.json()["series"] == []


def test_fight_player_timeline_404_when_unknown_fight() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/timeline/players").status_code == 404


def test_fight_player_timeline_422_when_window_s_too_small() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/timeline/players?window_s=0").status_code == 422


def test_fight_player_timeline_422_when_window_s_too_large() -> None:
    assert client.get("/api/v1/fights/DEADBEEF/timeline/players?window_s=601").status_code == 422


# ---------------------------------------------------------------------------
# Background task regression
# ---------------------------------------------------------------------------


def test_background_task_session_alive_at_invocation() -> None:
    _skip_if_no_db()
    blob = _make_minimal_zevtc(
        agents=[(123456789, 0, 0, "Player.One.1234", True)],
        build="20240925",
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("regression.zevtc", blob, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    deadline = time.monotonic() + 2.0
    status_value = None
    while time.monotonic() < deadline:
        get_resp = client.get(f"/api/v1/uploads/{upload_id}")
        if get_resp.status_code == 200:
            status_value = get_resp.json().get("status")
            if status_value in ("completed", "failed"):
                break
        time.sleep(0.05)
    assert status_value == "completed", (
        f"BG task left upload in {status_value!r}; expected 'completed'."
    )
