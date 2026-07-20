"""Route-level tests for GET /api/v1/fights/{id}/squads."""

from __future__ import annotations

import uuid as _uuid

from fastapi.testclient import TestClient

from apps.api.tests.routes._evtc_builder import build_2025_string
from gw2analytics_api.main import app

from ._evtc_builder import make_cbtevent, make_minimal_zevtc, post_upload

client = TestClient(app)


def _post_fight() -> str:
    suffix = _uuid.uuid4().hex[:8]
    a = 100_000 + int(suffix[:4], 16)
    b = a + 1
    sk = 1_000_000 + int(suffix[:4], 16)
    events = [make_cbtevent(1_000, src=a, dst=b, value=1000, skill_id=sk)]
    blob = make_minimal_zevtc(
        [(a, 2, 18, f"W {suffix}", True), (b, 1, 27, f"G {suffix}", True)],
        build=build_2025_string(suffix),
        skills=[(sk, "S")],
        events=events,
    )
    return post_upload(client, blob)


def test_squads_200() -> None:
    """Valid fight returns squad rollup."""
    fight_id = _post_fight()
    resp = client.get(f"/api/v1/fights/{fight_id}/squads")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["fight_id"] == fight_id
    assert isinstance(payload["squads"], list)
    assert len(payload["squads"]) > 0


def test_squads_404_unknown() -> None:
    """Unknown fight returns 404."""
    assert client.get("/api/v1/fights/nonexistent/squads").status_code == 404


def test_squads_404_no_events() -> None:
    """Fight with no events returns 404."""
    suffix = _uuid.uuid4().hex[:8]
    a = 100_000 + int(suffix[:4], 16)
    b = a + 1
    blob = make_minimal_zevtc(
        [(a, 2, 18, f"W {suffix}", True), (b, 1, 27, f"G {suffix}", True)],
        build=build_2025_string(suffix),
        skills=[(1_000_000 + int(suffix[:4], 16), "S")],
    )
    fight_id = post_upload(client, blob)
    assert client.get(f"/api/v1/fights/{fight_id}/squads").status_code == 404
