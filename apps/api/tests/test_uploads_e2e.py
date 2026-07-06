"""End-to-end POST /uploads test against a real Postgres.

Builds a synthetic ``.zevtc`` in-memory (using ``struct.Struct`` to
mimic the arcdps layout), POSTs it through the public API, then
queries GET /uploads and GET /fights to verify the schema is wired
correctly.

Requires the Postgres container from ``docker-compose.yml`` to be
running. Skipped on environments where Postgres is not reachable.
"""

from __future__ import annotations

import struct
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from gw2analytics_api.config import get_settings
from gw2analytics_api.main import app

client = TestClient(app)


def _make_minimal_zevtc(agents: list[tuple[int, int, int, str, bool]]) -> bytes:
    """Build a synthetic .zevtc blob (zip wrapper around EVTC)."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        # 32-byte header (placeholder — not arcdps-valid, parser will read
        # the magic+build and ascribe 0 agents, but the upload flow still
        # exercises every layer end-to-end).
        evtc = struct.pack("<4s8sBHBI", b"EVTC", b"20250925", 0, 0, 0, len(agents))
        body = bytearray()
        for aid, prof, elite, name, is_player in agents:
            name_bytes = name.encode("latin1", errors="replace")[:64].ljust(64, b"\x00")
            record = struct.pack("<QII64s", aid, prof, elite, name_bytes)
            record += b"\x01" if is_player else b"\x00"
            record += b"\x00" * 15
            body += record
        zf.writestr("fight.evtc", evtc + bytes(body))
    return buf.getvalue()


@pytest.fixture(scope="module")
def db_reachable() -> bool:
    try:
        eng = create_engine(get_settings().database_url, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def test_uploads_e2e_happy_path(db_reachable: bool) -> None:
    if not db_reachable:
        pytest.skip("Postgres not reachable; docker compose up gw2a-postgres first")
    blob = _make_minimal_zevtc(
        [(111, 2, 18, "E2E Warrior", True), (222, 1, 27, "E2E Guard", True)],
    )

    # POST a synthetic .zevtc
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("sample.zevtc", blob, "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert "id" in created
    assert "sha256" in created
    assert created["status"] in {"pending", "completed", "failed"}

    # GET /uploads/{id} returns the persisted row
    upload_resp = client.get(f"/api/v1/uploads/{created['id']}")
    assert upload_resp.status_code == 200
    payload = upload_resp.json()
    assert payload["sha256"] == created["sha256"]
    assert payload["status"] == "completed"
    assert payload["parser_version"]  # non-empty
    assert payload["fight_id"] is not None

    # GET /fights list contains a row referencing this upload
    list_resp = client.get("/api/v1/fights")
    assert list_resp.status_code == 200
    fights = list_resp.json()
    ids = {f["id"] for f in fights}
    assert payload["fight_id"] in ids

    # GET /fights/{id} returns the parsed fight with our 2 agents
    fight_resp = client.get(f"/api/v1/fights/{payload['fight_id']}")
    assert fight_resp.status_code == 200
    fight = fight_resp.json()
    assert fight["agent_count"] == 2
    assert len(fight["agents"]) == 2
    names = {a["name"] for a in fight["agents"]}
    assert names == {"E2E Warrior", "E2E Guard"}


def test_healthz_responds() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
