"""Async-first typed wrapper for the official Guild Wars 2 v2 REST API."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any, Final

import httpx

from gw2_api_client.exceptions import GuildWars2ApiError
from gw2_core import AccountInfo, WorldInfo

_BASE_URL: Final[str] = "https://api.guildwars2.com/v2"

_DEFAULT_TIMEOUT: Final[float] = 10.0

_MAX_RATE_LIMIT_RETRIES: Final[int] = 3

_RETRY_BASE_DELAY: Final[float] = 0.5

_DEFAULT_API_KEY_ENV: Final[str] = "GW2_API_KEY"


class AsyncGuildWars2Client:
    """Async httpx-backed GW2 v2 API client."""

    def __init__(self, api_key: str, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        if not api_key:
            msg = "api_key must be non-empty"
            raise ValueError(msg)
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = _DEFAULT_API_KEY_ENV,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> AsyncGuildWars2Client:
        key = os.getenv(env_var)
        if not key:
            msg = f"{env_var} not found in environment"
            raise ValueError(msg)
        return cls(api_key=key, timeout=timeout)

    async def __aenter__(self) -> AsyncGuildWars2Client:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._client.aclose()

    def supported_endpoints(self) -> tuple[str, ...]:
        return ("account", "worlds")

    async def account_get(self) -> AccountInfo:
        url = "/v2/account"
        data = await self._get_with_retries(url, auth_required=True)
        return AccountInfo.model_validate(data)

    async def worlds_get(self, ids: Sequence[int]) -> list[WorldInfo]:
        if not ids:
            return []
        url = "/v2/worlds"
        params = {"ids": ",".join(str(i) for i in ids)}
        data = await self._get_with_retries(url, params=params, auth_required=False)
        return [WorldInfo.model_validate(row) for row in data]

    async def _get_with_retries(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        auth_required: bool = True,
    ) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                msg = f"{url}: transport error: {exc}"
                raise GuildWars2ApiError(msg) from exc

            if response.status_code == 429:
                if attempt >= _MAX_RATE_LIMIT_RETRIES:
                    msg = f"{url}: rate-limited after {attempt} attempts"
                    raise GuildWars2ApiError(msg)
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
                continue

            if response.status_code == 401 and auth_required:
                msg = f"{url}: 401 unauthorized (check GW2_API_KEY scope)"
                raise GuildWars2ApiError(msg)

            if response.status_code >= 400:
                msg = f"{url}: HTTP {response.status_code}: {response.text[:200]}"
                raise GuildWars2ApiError(msg)

            return response.json()


__all__ = [
    "AsyncGuildWars2Client",
]
