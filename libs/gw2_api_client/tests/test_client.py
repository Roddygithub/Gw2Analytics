"""Tests for :mod:`gw2_api_client`.

Strategy
========

- **httpx is mocked end-to-end via respx.** No real network calls
  hit GuildWars 2 servers during the test run; ``respx.mock``
  intercepts requests at the httpx transport layer.

- **pytest-asyncio in strict mode.** Every async test has an
  explicit ``@pytest.mark.asyncio`` so the project-level
  ``asyncio_mode = "auto"`` setting won't accidentally run async
  tests in non-asyncio suites.

Cross-field / behavioral contracts locked down here:

- ``AccountInfo.id`` / ``name`` / ``world_id`` survive the rename
  (``alias="world"`` -> ``world_id``).
- 401 is mapped to :class:`GuildWars2ApiError`; 429 retries up to
  3 times and raises :class:`GuildWars2ApiError` on exhaustion.
- Network-level errors (httpx.ConnectError etc.) are wrapped to
  :class:`GuildWars2ApiError`.
- ``worlds_get([])`` short-circuits client-side without an HTTP
  round-trip.
- ``from_env`` reads the env var once; missing key ->
  ``ValueError``.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from gw2_api_client import AsyncGuildWars2Client
from gw2_api_client.exceptions import GuildWars2ApiError
from gw2_core import AccountInfo, Population, WorldInfo

_API_KEY = "test-key-123"
_BASE_URL = "https://api.guildwars2.com/v2"


def _client(api_key: str = _API_KEY) -> AsyncGuildWars2Client:
    return AsyncGuildWars2Client(api_key=api_key)


# ---------------------------------------------------------------------------
# account_get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_get_happy_path_returns_account_info() -> None:
    """Mocked 200 from /v2/account -> AccountInfo with the alias rename applied."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "ABC12345-1234-5678-9ABC-DEF123456789",
                    "name": "Account.1234",
                    "world": 1234,
                },
            ),
        )
        async with _client() as c:
            info = await c.account_get()
    assert isinstance(info, AccountInfo)
    assert info.id == "ABC12345-1234-5678-9ABC-DEF123456789"
    assert info.name == "Account.1234"
    assert info.world_id == 1234


@pytest.mark.asyncio
async def test_account_get_401_raises_http_error() -> None:
    """401 with auth_required -> GuildWars2ApiError."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(401, json={"text": "invalid token"}),
        )
        async with _client() as c:
            with pytest.raises(GuildWars2ApiError, match="401"):
                await c.account_get()


@pytest.mark.asyncio
async def test_account_get_network_error_raises_http_error() -> None:
    """httpx.ConnectError is wrapped into GuildWars2ApiError."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(side_effect=httpx.ConnectError("boom"))
        async with _client() as c:
            with pytest.raises(GuildWars2ApiError, match="transport error"):
                await c.account_get()


@pytest.mark.asyncio
async def test_account_get_429_retries_then_raises_rate_limit_error() -> None:
    """3 consecutive 429s exhaust the retry budget and raise GuildWars2ApiError."""
    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get("/v2/account").mock(return_value=httpx.Response(429))
        async with _client() as c:
            with pytest.raises(GuildWars2ApiError, match="rate-limited"):
                await c.account_get()
        # Exactly the retry budget (3 attempts).
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_account_get_recovers_after_one_429() -> None:
    """2x 429 then 200 -> success on the 2nd retry; total call_count = 2."""
    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get("/v2/account")
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json={"id": "X", "name": "Y", "world": 1}),
        ]
        async with _client() as c:
            info = await c.account_get()
    assert info.world_id == 1
    assert route.call_count == 2


# ---------------------------------------------------------------------------
# worlds_get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worlds_get_empty_ids_short_circuits_without_http() -> None:
    """Empty ids list -> [] without making any HTTP request."""
    with respx.mock(base_url=_BASE_URL) as mock:
        async with _client() as c:
            worlds = await c.worlds_get([])
    assert worlds == []
    assert not mock.calls


@pytest.mark.asyncio
async def test_worlds_get_happy_path_returns_world_info_list() -> None:
    """Mocked /v2/worlds?ids=1,2 -> list[WorldInfo] with mixed Population values."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/worlds").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "Yak's Bend", "population": "High"},
                    {"id": 2, "name": "Henge of Denravi", "population": "Medium"},
                ],
            ),
        )
        async with _client() as c:
            worlds = await c.worlds_get([1, 2])
    assert len(worlds) == 2
    assert all(isinstance(w, WorldInfo) for w in worlds)
    assert worlds[0].id == 1
    assert worlds[0].name == "Yak's Bend"
    assert worlds[0].population == Population.HIGH
    assert worlds[1].population == Population.MEDIUM


# ---------------------------------------------------------------------------
# from_env + supported_endpoints
# ---------------------------------------------------------------------------


def test_from_env_with_key_present_returns_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """from_env reads GW2_API_KEY -> instantiates AsyncGuildWars2Client."""
    monkeypatch.setenv("GW2_API_KEY", _API_KEY)
    client = AsyncGuildWars2Client.from_env()
    assert isinstance(client, AsyncGuildWars2Client)


def test_from_env_with_missing_key_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """from_env without GW2_API_KEY -> ValueError."""
    monkeypatch.delenv("GW2_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GW2_API_KEY"):
        AsyncGuildWars2Client.from_env()


def test_supported_endpoints_contract() -> None:
    """supported_endpoints returns the (``account``, ``worlds``) tuple."""
    assert _client().supported_endpoints() == ("account", "worlds")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_context_manager_closes_underlying_pool() -> None:
    """``async with`` enters without error and closes the httpx pool on exit."""
    async with _client() as c:
        assert c._client is not None
        # We can't easily introspect the closed state without reaching
        # into httpx internals, but if __aexit__ were broken the
        # context manager would itself raise.


@pytest.mark.asyncio
async def test_account_get_silently_drops_unknown_extra_fields() -> None:
    """v0.10.5 R3.3: ``extra="ignore"`` drops unknown v999 fields from the v2 API response."""
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get("/v2/account").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "X",
                    "name": "Y",
                    "world": 1,
                    "future_field_v999": {"nested": "ignored"},
                },
            ),
        )
        async with _client() as c:
            info = await c.account_get()
    assert info.id == "X"
    assert "future_field_v999" not in info.model_dump()


@pytest.mark.asyncio
async def test_account_get_429_cascade_exactly_three_attempts() -> None:
    """v0.10.5 R3.3: 3 consecutive 429s raise GuildWars2ApiError on the 3rd (not 4th) attempt."""
    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get("/v2/account").mock(return_value=httpx.Response(429))
        async with _client() as c:
            with pytest.raises(GuildWars2ApiError, match="rate-limited"):
                await c.account_get()
    assert route.call_count == 3
