"""Route-level tests for GET /api/v1/fights/{id}/events."""

from __future__ import annotations

import uuid as _uuid

from fastapi.testclient import TestClient

from apps.api.tests.routes._evtc_builder import build_2025_string
from gw2analytics_api.main import app

from ._evtc_builder import make_cbtevent, make_minimal_zevtc, post_upload

client = TestClient(app)


def _post_fight_and_events(
    n_events: int,
    *,
    base_id_a: int | None = None,
) -> tuple[str, list[bytes]]:
    suffix = _uuid.uuid4().hex[:8]
    if base_id_a is None:
        base_id_a = 100_000 + int(suffix[:4], 16)
    base_id_b = base_id_a + 1
    base_skill = 1_000_000 + int(suffix[:4], 16)

    def _ev(i: int) -> bytes:
        return make_cbtevent(
            1_000 + i * 2_000,
            src=base_id_a,
            dst=base_id_b,
            value=1000,
            skill_id=base_skill + i,
        )

    cbtevents = [_ev(i) for i in range(n_events)]
    agents = [
        (base_id_a, 2, 18, f"Warrior {suffix}", True),
        (base_id_b, 1, 27, f"Guard {suffix}", True),
    ]
    blob = make_minimal_zevtc(
        agents,
        build=build_2025_string(suffix),
        skills=[(base_skill + i, f"Skill_{i}") for i in range(max(n_events, 1))],
        events=cbtevents,
    )
    fight_id = post_upload(client, blob)
    return fight_id, cbtevents


def test_events_200() -> None:
    """Valid fight returns 200 with correct structure."""
    fight_id, _ = _post_fight_and_events(5)
    resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["fight_id"] == fight_id
    assert summary["duration_s"] > 0
    assert isinstance(summary["target_dps"], list)
    assert isinstance(summary["target_healing"], list)
    assert isinstance(summary["target_buff_removal"], list)


def test_events_404_fight_not_found() -> None:
    """Unknown fight_id returns 404."""
    resp = client.get("/api/v1/fights/does-not-exist-1234/events")
    assert resp.status_code == 404


def test_events_404_empty_events() -> None:
    """Fight with no events returns 404."""
    fight_id, _ = _post_fight_and_events(0)
    resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert resp.status_code == 404


def test_events_window_s_param() -> None:
    """?window_s=10 vs default 5s: wider window produces fewer buckets."""
    fight_id, _ = _post_fight_and_events(4)
    default_resp = client.get(f"/api/v1/fights/{fight_id}/events")
    assert default_resp.status_code == 200
    default_buckets = len(default_resp.json()["event_windows"])
    custom_resp = client.get(f"/api/v1/fights/{fight_id}/events", params={"window_s": 10})
    assert custom_resp.status_code == 200, custom_resp.text
    custom_buckets = len(custom_resp.json()["event_windows"])
    assert custom_buckets < default_buckets
