"""Route-level tests for GET /api/v1/guilds.

Targets the 0% coverage in guilds.py (P1 from COVERAGE-90-PLAN):

- ``list_guilds``: GET /api/v1/guilds?account_name=X → 200 with guild list
- ``get_guild``: GET /api/v1/guilds/{id} → 200 with guild + members
- ``get_guild`` 404: GET /api/v1/guilds/unknown → 404
"""

from __future__ import annotations

import uuid as _uuid

from fastapi.testclient import TestClient

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import Guild, GuildMember

client = TestClient(app)


def _seed_guild(
    guild_id: str | None = None,
    account_name: str | None = None,
) -> tuple[str, str]:
    """Create a Guild + GuildMember row directly in the DB.

    Returns ``(guild_id, account_name)`` so the caller can use them
    in assertions.
    """
    gid = guild_id or _uuid.uuid4().hex[:12]
    acct = account_name or f"test.{_uuid.uuid4().hex[:8]}"

    with get_sessionmaker()() as db:
        db.add(Guild(id=gid, name="Test Guild", tag="TEST"))
        db.add(GuildMember(guild_id=gid, account_name=acct, rank="Leader"))
        db.commit()

    return gid, acct


def test_guilds_list_200() -> None:
    """Existing account returns guild list."""
    gid, acct = _seed_guild()
    resp = client.get(f"/api/v1/guilds?account_name={acct}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert rows[0]["id"] == gid
    assert rows[0]["name"] == "Test Guild"
    assert rows[0]["tag"] == "TEST"


def test_guilds_list_empty() -> None:
    """Unknown account returns empty list."""
    resp = client.get("/api/v1/guilds?account_name=does.not.exist.9999")
    assert resp.status_code == 200
    assert resp.json() == []


def test_guilds_detail_200() -> None:
    """Existing guild returns guild info + members."""
    gid, acct = _seed_guild()
    resp = client.get(f"/api/v1/guilds/{gid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == gid
    assert data["name"] == "Test Guild"
    assert data["tag"] == "TEST"
    assert isinstance(data["members"], list)
    assert len(data["members"]) >= 1
    assert data["members"][0]["account_name"] == acct
    assert data["members"][0]["rank"] == "Leader"


def test_guilds_detail_404() -> None:
    """Unknown guild returns 404."""
    resp = client.get("/api/v1/guilds/unknown-guild-id-999999")
    assert resp.status_code == 404


def test_guilds_detail_multiple_members() -> None:
    """Guild with 2 members returns both."""
    gid = _uuid.uuid4().hex[:12]
    acct_a = f"test.{_uuid.uuid4().hex[:8]}"
    acct_b = f"test.{_uuid.uuid4().hex[:8]}"

    with get_sessionmaker()() as db:
        db.add(Guild(id=gid, name="Multi Guild", tag="MULTI"))
        db.add(GuildMember(guild_id=gid, account_name=acct_a, rank="Leader"))
        db.add(GuildMember(guild_id=gid, account_name=acct_b, rank="Member"))
        db.commit()

    resp = client.get(f"/api/v1/guilds/{gid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["members"]) == 2
    member_accounts = {m["account_name"] for m in data["members"]}
    assert acct_a in member_accounts
    assert acct_b in member_accounts
