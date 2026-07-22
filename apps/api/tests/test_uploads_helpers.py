"""Shared fixtures and assertion helpers for upload E2E tests.

Extracted from ``test_uploads_e2e.py`` so the main E2E file stays
under 800 lines. Re-exported helpers are imported by both
``test_uploads_e2e.py`` and other test modules that need to
POST minimal fights.
"""

from __future__ import annotations

import time
import uuid as _uuid

from fastapi.testclient import TestClient
from tests._fixtures import _make_minimal_zevtc

from gw2analytics_api.main import app

client = TestClient(app)


def _post_minimal_fight(
    events: list[bytes] | None = None,
    suffix: str | None = None,
    *,
    agents: list[tuple[int, int, int, str, bool]] | None = None,
) -> str:
    """POST a minimal 2-agent fight with optional cbtevent records.

    Returns the persisted ``fight_id``.
    """
    suffix = suffix or _uuid.uuid4().hex[:8]
    build = "20240925"
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_skill_b = base_skill_a + 1
    if agents is None:
        agents = [
            (base_id_a, 2, 18, f"V07 Warrior {suffix}", True),
            (base_id_b, 1, 27, f"V07 Guard {suffix}", True),
        ]
    blob = _make_minimal_zevtc(
        agents,
        build=build,
        skills=[
            (base_skill_a, f"Whirlwind {suffix}"),
            (base_skill_b, f"Burning {suffix}"),
        ],
        events=events or [],
    )
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]
    return _wait_for_upload_completion(upload_id)


def _wait_for_upload_completion(upload_id: str) -> str:
    """Poll the upload status until the background parser flips
    ``status`` to ``"completed"``, then return the persisted ``fight_id``.
    """
    for _ in range(50):
        upload_resp = client.get(f"/api/v1/uploads/{upload_id}")
        assert upload_resp.status_code == 200
        if upload_resp.json()["status"] == "completed":
            time.sleep(0.1)
            return str(upload_resp.json()["fight_id"])
        time.sleep(0.1)
    msg = f"upload {upload_id} did not reach 'completed' within 5s"
    raise AssertionError(msg)
