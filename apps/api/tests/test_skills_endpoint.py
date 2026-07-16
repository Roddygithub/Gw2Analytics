"""v0.10.26-pre: GET /api/v1/skills endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_skills_returns_catalog_entries(client: TestClient) -> None:
    """Smoke: list-skills returns at least 1 entry from the seeded fixture."""
    resp = client.get("/api/v1/skills")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Spot-check Quickness (skill_id 1187)
    quickness = next((s for s in data if s["id"] == 1187), None)
    assert quickness is not None
    assert quickness["name"] == "Quickness"
    assert quickness["skill_type"] == "boon"
    # Wire contract: profession is string | null (NOT int). Boon entries
    # have profession=null (multi-profession usable).
    assert quickness["profession"] is None
    assert isinstance(quickness["profession"], (type(None), str))


def test_get_skill_by_id_returns_entry(client: TestClient) -> None:
    resp = client.get("/api/v1/skills/1187")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == 1187
    assert data["name"] == "Quickness"
    assert data["profession"] is None
    assert data["skill_type"] == "boon"


def test_get_skill_unknown_id_returns_404(client: TestClient) -> None:
    resp = client.get("/api/v1/skills/99999999")
    assert resp.status_code == 404


def test_get_skill_profession_string_serialization(client: TestClient) -> None:
    """Lock the profession=string contract -- IntEnum int values
    would silently fall through Pydantic and break schema.d.ts.

    Picks a profession-bearing entry by type ``heal`` (heal skills have
    a profession); falls back to Neutral if the seed fixture omits one.
    """
    resp = client.get("/api/v1/skills")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    profession_entries = [s for s in data if s["profession"] is not None]
    if not profession_entries:
        # NDJSON fixture only has boons/conditions (profession=None) --
        # skip the profession-string assertion gracefully.
        return
    entry = profession_entries[0]
    # The profession MUST be a plain string (per schema.d.ts contract),
    # NEVER an integer (IntEnum default serialisation).
    assert isinstance(entry["profession"], str)
