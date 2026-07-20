"""Route-level tests for GET /api/v1/players."""

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


def test_list_200() -> None:
    """Returns correctly shaped player list."""
    _post_fight()
    resp = client.get("/api/v1/players")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert "account_name" in rows[0]
    assert "total_damage" in rows[0]


def test_list_empty() -> None:
    """No players returns []."""
    resp = client.get("/api/v1/players")
    assert resp.status_code == 200
    assert resp.json() == []
