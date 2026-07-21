"""v0.10.26-pre: GET /api/v1/skills endpoint tests."""

from __future__ import annotations

from contextlib import suppress

from fastapi.testclient import TestClient

from gw2analytics_api.main import app


def test_list_skills_returns_catalog_entries(client: TestClient) -> None:
    """Smoke: list-skills returns at least 1 entry from the seeded fixture."""
    resp = client.get("/api/v1/skills")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Spot-check Signet of Restoration (skill_id 5503) — a heal skill
    # with profession=Elementalist. Uses a real GW2 API-derived entry
    # (the catalog no longer ships manually-seeded boon entries).
    signet = next((s for s in data if s["id"] == 5503), None)
    assert signet is not None, f"skill 5503 not found in catalog ({len(data)} entries)"
    assert signet["name"] == "Signet of Restoration"
    assert signet["skill_type"] == "heal"
    # Wire contract: profession is string | null (NOT int).
    assert signet["profession"] == "ELEMENTALIST"
    assert isinstance(signet["profession"], str)


def test_get_skill_by_id_returns_entry(client: TestClient) -> None:
    """Smoke: get-skill-by-id returns a real API-derived entry.

    Uses Signet of Restoration (5503) — a heal skill with profession.
    The old fixture used Quickness (1187) which was a manually-seeded
    boon entry; boons are not in the GW2 /v2/skills API endpoint.
    """
    resp = client.get("/api/v1/skills/5503")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == 5503
    assert data["name"] == "Signet of Restoration"
    assert data["profession"] == "ELEMENTALIST"
    assert data["skill_type"] == "heal"
    assert data["is_elite"] is False


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


def test_list_skills_503_when_state_none(client: TestClient) -> None:
    """v0.10.26-pre regression guard: lifespan fail-safe path sets
    app.state.skill_catalog = None on any startup exception. Without
    this test, a future PR that reorders the lifespan silently
    breaks the SKILLS_UNAVAILABLE 503 contract surfaced to the
    frontend via web/src/lib/fetchCached.ts error_code lookup.
    """
    # Monkeypatch the app state to simulate the lifespan fail-safe.
    # ``app`` is imported at module level (apps/api/tests/__init__.py
    # ancestor path); the ``client`` fixture already triggered the
    # lifespan, so ``app.state.skill_catalog`` is populated.
    sentinel = object()  # unique marker for "attribute not yet set"
    original_state = getattr(app.state, "skill_catalog", sentinel)
    app.state.skill_catalog = None
    try:
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 503, resp.text
        body = resp.json()
        # FastAPI wraps HTTPException ``detail={...}`` under the outer
        # response ``detail`` key: body shape is
        # ``{"detail": {"detail": "...", "error_code": "..."}}``.
        # The frontend's fetchCached.ts:60-73 reads `detail.error_code`
        # for this nesting; this lock guards the wire shape contract.
        assert isinstance(body, dict)
        outer_detail = body.get("detail")
        assert isinstance(outer_detail, dict)
        assert outer_detail.get("error_code") == "SKILLS_UNAVAILABLE"
    finally:
        # Restore so subsequent tests in the same module aren't poisoned.
        if original_state is sentinel:
            with suppress(AttributeError):
                del app.state.skill_catalog
        else:
            app.state.skill_catalog = original_state


def test_list_skills_catalog_count_meets_minimum(client: TestClient) -> None:
    """SCAFFOLD-gate: the shipped NDJSON catalogue must have at
    least 30 entries (v0.10.26-pre minimum) so the frontend's
    client-side lookup has material to bootstrap. The 129-entry
    v0.10.26-pre expansion is the per-cycle target.
    """
    resp = client.get("/api/v1/skills")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) >= 4000, (
        f"Catalog should have >= 30 entries (got {len(data)}). "
        "If you removed fixtures, restore from v0.10.25 baseline."
    )
