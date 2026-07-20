"""Route-level tests for GET /api/v1/fights/{id}/timeline."""

from __future__ import annotations

import uuid as _uuid

from fastapi.testclient import TestClient

from apps.api.tests.routes._evtc_builder import build_2025_string
from gw2analytics_api.main import app

from ._evtc_builder import make_cbtevent, make_minimal_zevtc, post_upload

client = TestClient(app)


def _post_fight(n_events: int) -> tuple[str, int, int]:
    suffix = _uuid.uuid4().hex[:8]
    a = 100_000 + int(suffix[:4], 16)
    b = a + 1
    sk = 1_000_000 + int(suffix[:4], 16)
    cbtevents = [
        make_cbtevent(1_000 + i * 2_000, src=a, dst=b, value=1000, skill_id=sk + i)
        for i in range(n_events)
    ]
    blob = make_minimal_zevtc(
        [(a, 2, 18, f"W {suffix}", True), (b, 1, 27, f"G {suffix}", True)],
        build=build_2025_string(suffix),
        skills=[(sk + i, f"S{i}") for i in range(max(n_events, 1))],
        events=cbtevents,
    )
    return post_upload(client, blob), a, b


def test_timeline_200_default_window() -> None:
    """Default 5s window returns timeline points."""
    fight_id, _, _ = _post_fight(4)
    resp = client.get(f"/api/v1/fights/{fight_id}/timeline")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["fight_id"] == fight_id
    assert payload["window_s"] == 5
    assert len(payload["points"]) > 0


def test_timeline_200_custom_window() -> None:
    """?window_s=10 returns fewer points than default."""
    fight_id, _, _ = _post_fight(4)
    default = client.get(f"/api/v1/fights/{fight_id}/timeline")
    custom = client.get(f"/api/v1/fights/{fight_id}/timeline", params={"window_s": 10})
    assert default.status_code == 200
    assert custom.status_code == 200
    assert len(custom.json()["points"]) <= len(default.json()["points"])


def test_timeline_422_out_of_bounds() -> None:
    """?window_s=0 or ?window_s=601 returns 422."""
    fight_id, _, _ = _post_fight(1)
    r0 = client.get(f"/api/v1/fights/{fight_id}/timeline", params={"window_s": 0})
    assert r0.status_code == 422
    r601 = client.get(f"/api/v1/fights/{fight_id}/timeline", params={"window_s": 601})
    assert r601.status_code == 422


def test_timeline_404_no_fight() -> None:
    """Unknown fight returns 404."""
    assert client.get("/api/v1/fights/nonexistent/timeline").status_code == 404


def test_timeline_404_no_blob() -> None:
    """Fight with no events returns 404."""
    fight_id, _, _ = _post_fight(0)
    assert client.get(f"/api/v1/fights/{fight_id}/timeline").status_code == 404
