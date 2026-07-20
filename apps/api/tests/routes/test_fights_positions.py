"""Route-level + helper tests for GET /api/v1/fights/{id}/positions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import gw2analytics_api.routes.fights as routes_module
from gw2_core import PositionEvent
from gw2analytics_api.main import app
from gw2analytics_api.routes.fights.aggregators import (
    AgentIdentity,
    aggregate_player_positions,
)

client = TestClient(app)


def _identity(agent_id: int, account: str, name: str = "") -> AgentIdentity:
    return AgentIdentity(
        agent_id=agent_id,
        name=name or account,
        subgroup=1,
        account_name=account,
        profession="Guardian",
        elite_spec="Firebrand",
        is_player=True,
        is_commander=False,
    )


def test_aggregate_player_positions_two_players() -> None:
    """Two players at (0,0) and (10,0) produce symmetric metrics."""
    events: list[PositionEvent] = [
        PositionEvent(time_ms=0, source_agent_id=1, target_agent_id=0, skill_id=0, x=0.0, y=0.0),
        PositionEvent(time_ms=0, source_agent_id=2, target_agent_id=0, skill_id=0, x=10.0, y=0.0),
    ]
    identity_map = {1: _identity(1, ":a", "A"), 2: _identity(2, ":b", "B")}
    rows = aggregate_player_positions(events, identity_map)
    assert len(rows) == 2
    # stack_dist == 10 for both (distance to the other player).
    for row in rows:
        assert row.stack_dist == 10.0
        # dist_to_com should be 5.0 (distance to center of mass at (5,0)).
        assert row.dist_to_com == 5.0
        assert len(row.samples) == 1


def test_aggregate_player_positions_single_player_returns_none_stack() -> None:
    """Single player cannot compute stack distance or center-of-mass distance."""
    events: list[PositionEvent] = [
        PositionEvent(time_ms=0, source_agent_id=1, target_agent_id=0, skill_id=0, x=0.0, y=0.0),
    ]
    rows = aggregate_player_positions(events, {1: _identity(1, ":a")})
    assert len(rows) == 1
    assert rows[0].stack_dist is None
    assert rows[0].dist_to_com is None


def test_aggregate_player_positions_no_players() -> None:
    """Empty identity map returns empty list."""
    assert aggregate_player_positions([], {}) == []


def test_aggregate_player_positions_downsamples_to_500ms() -> None:
    """Two samples in the same 500ms bucket collapse to one."""
    events = [
        PositionEvent(time_ms=0, source_agent_id=1, target_agent_id=0, skill_id=0, x=0.0, y=0.0),
        PositionEvent(time_ms=100, source_agent_id=1, target_agent_id=0, skill_id=0, x=1.0, y=1.0),
        PositionEvent(time_ms=600, source_agent_id=1, target_agent_id=0, skill_id=0, x=2.0, y=2.0),
    ]
    rows = aggregate_player_positions(events, {1: _identity(1, ":a")})
    assert len(rows) == 1
    assert len(rows[0].samples) == 2


def test_aggregate_player_positions_caps_at_2000() -> None:
    """More than 2000 downsampled buckets per player are capped."""
    events = [
        PositionEvent(
            time_ms=i * 500,
            source_agent_id=1,
            target_agent_id=0,
            skill_id=0,
            x=float(i),
            y=float(i),
        )
        for i in range(2500)
    ]
    rows = aggregate_player_positions(events, {1: _identity(1, ":a")})
    assert len(rows) == 1
    assert len(rows[0].samples) == 2000


def test_get_fight_positions_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route returns per-player position metrics."""
    events: list[PositionEvent] = [
        PositionEvent(time_ms=0, source_agent_id=1, target_agent_id=0, skill_id=0, x=0.0, y=0.0),
        PositionEvent(time_ms=0, source_agent_id=2, target_agent_id=0, skill_id=0, x=10.0, y=0.0),
    ]

    def _fake_load(_db: object, _fight_id: str) -> list[PositionEvent]:
        return events

    def _fake_identity(_db: object, _fight_id: str) -> dict[int, AgentIdentity]:
        return {
            1: _identity(1, ":a", "A"),
            2: _identity(2, ":b", "B"),
        }

    monkeypatch.setattr(routes_module, "_load_fight_events", _fake_load)
    monkeypatch.setattr(routes_module, "agent_id_to_identity", _fake_identity)

    resp = client.get("/api/v1/fights/fake/positions")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["fight_id"] == "fake"
    assert len(payload["players"]) == 2


def test_get_fight_positions_404_no_fight() -> None:
    """Unknown fight returns 404 (the shared helper raises it)."""
    resp = client.get("/api/v1/fights/nonexistent/positions")
    assert resp.status_code == 404


def test_aggregate_player_positions_no_events() -> None:
    """No PositionEvents yields empty list."""
    identity = _identity(1, ":a")
    assert aggregate_player_positions([], {1: identity}) == []


def test_aggregate_player_positions_drops_missing_account_name() -> None:
    """Player agents without an account name are excluded."""
    events = [
        PositionEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=0,
            skill_id=0,
            x=0.0,
            y=0.0,
        ),
    ]
    identity = _identity(1, "")
    rows = aggregate_player_positions(events, {1: identity})
    assert rows == []


def test_get_fight_positions_empty_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fight with no PositionEvents returns empty players list."""
    monkeypatch.setattr(routes_module, "_load_fight_events", lambda _db, _fid: [])
    monkeypatch.setattr(
        routes_module,
        "agent_id_to_identity",
        lambda _db, _fid: {1: _identity(1, ":a")},
    )
    resp = client.get("/api/v1/fights/empty/positions")
    assert resp.status_code == 200
    assert resp.json() == {"fight_id": "empty", "players": []}
