"""Route-level tests for GET /api/v1/players/{name}."""

from __future__ import annotations

import uuid as _uuid
from urllib.parse import quote

from fastapi.testclient import TestClient

from gw2analytics_api.main import app

from ._evtc_builder import make_cbtevent, make_minimal_zevtc, post_upload

client = TestClient(app)


def test_detail_200() -> None:
    """Existing player returns profile with per-fight breakdown."""
    suffix = _uuid.uuid4().hex[:8]
    a = 100_000 + int(suffix[:4], 16)
    b = a + 1
    sk = 1_000_000 + int(suffix[:4], 16)
    events = [
        make_cbtevent(1_000, src=a, dst=b, value=1000, skill_id=sk),
        make_cbtevent(2_000, src=b, dst=a, value=500, skill_id=sk),
    ]
    blob = make_minimal_zevtc(
        [(a, 2, 18, f"W {suffix}", True), (b, 1, 27, f"G {suffix}", True)],
        build=f"2025{suffix[:4]}",
        skills=[(sk, "S")],
        events=events,
    )
    post_upload(client, blob)
    account_name = f"synth.{a}"
    encoded = quote(account_name, safe="")
    detail_resp = client.get(f"/api/v1/players/{encoded}")
    assert detail_resp.status_code == 200, detail_resp.text
    profile = detail_resp.json()
    assert profile["account_name"] == account_name
    assert profile["fights_attended"] >= 1
    assert profile["total_damage"] >= 0
    assert isinstance(profile["per_fight_breakdown"], list)


def test_detail_404() -> None:
    """Unknown player returns 404."""
    resp = client.get("/api/v1/players/does-not-exist-1234")
    assert resp.status_code == 404
