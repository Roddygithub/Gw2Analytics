"""Smoke test for the /healthz endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gw2analytics_api.main import app

client = TestClient(app)


def test_healthz_returns_ok() -> None:
    """GET /healthz returns 200 with body {'status': 'ok'}."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
