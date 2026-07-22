"""Tests for ``GET /api/v1/account``.

All upstream Guild Wars 2 v2 calls are intercepted via ``respx`` so the
test suite never touches ArenaNet servers. We exercise the FastAPI
:class:`fastapi.testclient.TestClient` (sync) which spins the app in
process; async routes reach the event loop via :mod:`anyio`.

Cross-field / behavioral contracts locked down here:

- Happy path: /v2/account + /v2/worlds responses compose into
  ``(world_id, world_name, world_population)`` exactly.
- Missing or empty bearer -> 401 with ``WWW-Authenticate: Bearer``.
- Upstream ``401`` -> ``401`` (innermost "key was rejected" outcome).
- Upstream ``5xx`` -> ``502`` (innermost "upstream broken" outcome).
- Upstream ``429`` exhausts the 3-attempt retry budget then surfaces
  as ``503``.
- Empty ``worlds_get`` response -> ``502`` (we cannot enrich).
- 1x ``429`` then ``200`` -> succeeds on retry 2 (proves the retry
  policy is wired through the route).
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from gw2analytics_api.main import app

client = TestClient(app)

_API_KEY = "test-key-123"
_BASE_URL = "https://api.guildwars2.com/v2"


def _account_payload(world: int = 1234) -> dict[str, object]:
    return {
        "id": "ABC12345-1234-5678-9ABC-DEF123456789",
        "name": "Account.1234",
        "world": world,
    }


def _worlds_payload(world_id: int, name: str, pop: str) -> list[dict[str, object]]:
    return [{"id": world_id, "name": name, "population": pop}]


def _auth_header(key: str = _API_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_account_happy_path_returns_world_triple() -> None:
    """Mocked 200 from /v2/account + /v2/worlds -> (id, name, population)."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(200, json=_account_payload(world=1234)),
        )
        mock.get("/v2/worlds").mock(
            return_value=httpx.Response(
                200,
                json=_worlds_payload(1234, "Yak's Bend", "High"),
            ),
        )
        resp = client.get("/api/v1/account", headers=_auth_header())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "world_id": 1234,
        "world_name": "Yak's Bend",
        "world_population": "High",
    }


# ---------------------------------------------------------------------------
# Auth surface
# ---------------------------------------------------------------------------


def test_account_missing_bearer_returns_401_with_www_authenticate() -> None:
    """No Authorization header -> 401 with WWW-Authenticate: Bearer."""
    resp = client.get("/api/v1/account")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_account_empty_bearer_returns_401() -> None:
    """``Authorization: Bearer`` (empty) -> 401."""
    resp = client.get("/api/v1/account", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Upstream error mapping
# ---------------------------------------------------------------------------


def test_account_upstream_401_maps_to_401() -> None:
    """GW2 upstream 401 (bad key) -> the API surfaces its own 401."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(401, json={"text": "invalid token"}),
        )
        resp = client.get("/api/v1/account", headers=_auth_header())
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_account_upstream_500_maps_to_502() -> None:
    """GW2 upstream 5xx -> the API surfaces 502 (Bad Gateway)."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(503, json={"text": "down for maintenance"}),
        )
        resp = client.get("/api/v1/account", headers=_auth_header())
    assert resp.status_code == 502


def test_account_upstream_429_maps_to_503_after_retry_budget() -> None:
    """3 consecutive 429s exhaust the retry budget then surface as 503."""
    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get("/v2/account").mock(return_value=httpx.Response(429))
        resp = client.get("/api/v1/account", headers=_auth_header())
    assert resp.status_code == 503
    # Exactly the retry budget is consumed before the surface error.
    assert route.call_count == 3


def test_account_recovers_after_one_429() -> None:
    """1x 429 + 200 succeeds on attempt 2 -- proves retry policy hits the route."""
    with respx.mock(base_url=_BASE_URL) as mock:
        account = mock.get("/v2/account")
        account.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json=_account_payload(world=1234)),
        ]
        mock.get("/v2/worlds").mock(
            return_value=httpx.Response(
                200,
                json=_worlds_payload(1234, "Yak's Bend", "Medium"),
            ),
        )
        resp = client.get("/api/v1/account", headers=_auth_header())
    assert resp.status_code == 200
    assert resp.json()["world_population"] == "Medium"


def test_account_no_worlds_returns_502() -> None:
    """account_get succeeds but worlds_get returns [] -> 502."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(200, json=_account_payload(world=9999)),
        )
        mock.get("/v2/worlds").mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/api/v1/account", headers=_auth_header())
        assert resp.status_code == 502


def test_account_whitespace_only_bearer_returns_401() -> None:
    """Whitespace-only bearer token -> 401 (not forwarded upstream)."""
    resp = client.get(
        "/api/v1/account",
        headers={"Authorization": "Bearer    "},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Edge cases locked at unit level (drift guard)
# ---------------------------------------------------------------------------


def test_account_lowercase_bearer_scheme_still_works() -> None:
    """RFC 7235 §2.1 says the scheme name is case-insensitive; the route
    accepts ``bearer`` (lowercase) just like ``Bearer``.
    """
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(200, json=_account_payload(world=1234)),
        )
        mock.get("/v2/worlds").mock(
            return_value=httpx.Response(
                200,
                json=_worlds_payload(1234, "Yak's Bend", "High"),
            ),
        )
        resp = client.get(
            "/api/v1/account",
            headers={"Authorization": f"bearer {_API_KEY}"},
        )
    assert resp.status_code == 200, resp.text


def test_account_upstream_connect_timeout_maps_to_502() -> None:
    """Network timeout (httpx.ConnectTimeout) -> 502 Bad Gateway.

    The gateway wraps ``httpx.HTTPError`` subclasses into
    :class:`GuildWars2ApiError` upstream; the route must surface
    any transport failure (not just 5xx) as 502.
    """
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            side_effect=httpx.ConnectTimeout("connect timed out"),
        )
        resp = client.get("/api/v1/account", headers=_auth_header())
    assert resp.status_code == 502
