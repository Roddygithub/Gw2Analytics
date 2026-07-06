"""Async-first typed wrapper for the official Guild Wars 2 v2 REST API.

Exposes :class:`GuildWars2Client` (a Protocol) and the concrete
:class:`AsyncGuildWars2Client` (the only implementation shipped today;
a sync sibling lands in a future phase if a non-asyncio consumer
surfaces).

Concurrency model
=================

Each :class:`AsyncGuildWars2Client` instance owns one
``httpx.AsyncClient`` connection pool. Always use as an async
context manager (``async with``) so the pool closes deterministically
on exit. The class is otherwise stateless from the caller's
perspective -- instantiate once (via :meth:`from_env` for production,
directly for tests) and reuse across many requests.

Rate-limit policy
=================

A 429 response triggers up to 3 retry attempts with exponential
backoff (0.5s, 1.0s, 2.0s) before raising
:class:`~gw2_api_client.exceptions.GuildWars2RateLimitError`. Callers
that want a longer / shorter retry budget can wrap their own policy
layer on top.

Forward-compat
==============

``AccountInfo`` + ``WorldInfo`` live in :mod:`gw2_core.models` --
NOT in this module -- so the analytics layer can consume the same
shapes without importing the HTTP client. A future
``SyncGuildWars2Client`` can implement the same
:class:`GuildWars2Client` Protocol with ``httpx.Client`` returning the
exact same frozen :class:`AccountInfo` / :class:`WorldInfo` objects.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any, Final, Protocol, runtime_checkable

import httpx

from gw2_api_client.exceptions import (
    GuildWars2HttpError,
    GuildWars2RateLimitError,
    MissingApiKeyError,
)
from gw2_core import AccountInfo, WorldInfo

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

_BASE_URL: Final[str] = "https://api.guildwars2.com/v2"
"""Base URL for the Guild Wars 2 v2 REST API."""

_DEFAULT_TIMEOUT: Final[float] = 10.0
"""Default httpx request timeout, in seconds."""

_MAX_RATE_LIMIT_RETRIES: Final[int] = 3
"""Number of attempts (including the first) before giving up on a 429."""

_RETRY_BASE_DELAY: Final[float] = 0.5
"""Base delay (seconds) for exponential backoff (0.5, 1.0, 2.0, ...)."""

_DEFAULT_API_KEY_ENV: Final[str] = "GW2_API_KEY"
"""Default env var read by :meth:`AsyncGuildWars2Client.from_env`."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class GuildWars2Client(Protocol):
    """Stable contract for a GW2 v2 API client (sync or async).

    Both :class:`AsyncGuildWars2Client` (shipped) and any future sync
    sibling implement this surface. Tests should duck-type against
    this Protocol rather than the concrete class so a sync swap-out
    does not force a test rewrite.

    Decorated with :func:`typing.runtime_checkable` so consumers can
    use ``isinstance(client, GuildWars2Client)`` to perform a
    structural duck-type check on the three public attributes
    (``supported_endpoints``, ``account_get``, ``worlds_get``).
    Python 3.12's runtime check is structural on attribute presence
    only -- it does not introspect coroutine-ness, which is fine for
    this use case (we want a yes/no answer to *"does the object
    respond to these three names?"*).
    """

    def supported_endpoints(self) -> tuple[str, ...]:
        """Names of the v2 API endpoints this client can reach."""
        ...

    async def account_get(self) -> AccountInfo:
        """Fetch the authenticated account.

        Requires an API key with the ``account`` scope. A 401 maps to
        :class:`~gw2_api_client.exceptions.GuildWars2HttpError`.
        """
        ...

    async def worlds_get(self, ids: Sequence[int]) -> list[WorldInfo]:
        """Fetch world metadata for the given ids (auth optional).

        Empty ``ids`` returns ``[]`` WITHOUT making a request -- the
        v2 API rejects ``ids=`` (empty) with a 400 so we short-circuit
        client-side.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete async implementation
# ---------------------------------------------------------------------------


class AsyncGuildWars2Client:
    """Async httpx-backed implementation of :class:`GuildWars2Client`.

    Stateless from the caller's perspective: instantiate once (via
    :meth:`from_env` for production, directly for tests) and reuse
    across many requests -- httpx manages the underlying connection
    pool.
    """

    def __init__(self, api_key: str, *, timeout: float = _DEFAULT_TIMEOUT) -> None:
        """Direct constructor -- prefer :meth:`from_env` in production.

        Raises :class:`ValueError` if ``api_key`` is empty.
        """
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
        """Construct an :class:`AsyncGuildWars2Client` from ``os.environ``.

        Raises :class:`~gw2_api_client.exceptions.MissingApiKeyError`
        if the env var is unset or empty.
        """
        key = os.getenv(env_var)
        if not key:
            msg = f"{env_var} not found in environment"
            raise MissingApiKeyError(msg)
        return cls(api_key=key, timeout=timeout)

    async def __aenter__(self) -> AsyncGuildWars2Client:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._client.aclose()

    def supported_endpoints(self) -> tuple[str, ...]:
        """Return ``("account", "worlds")`` -- the v2 endpoints this client reaches."""
        return ("account", "worlds")

    async def account_get(self) -> AccountInfo:
        """Fetch the authenticated account. Auth required (401 -> :class:`GuildWars2HttpError`)."""
        url = "/v2/account"
        data = await self._get_with_retries(url, auth_required=True)
        # Pydantic handles the ``alias="world"`` -> ``world_id`` rename.
        return AccountInfo.model_validate(data)

    async def worlds_get(self, ids: Sequence[int]) -> list[WorldInfo]:
        """Fetch world metadata for ``ids``. Empty inputs short-circuit to ``[]`` (no HTTP)."""
        # Short-circuit: an empty ``ids=`` would 400 against the v2 API and
        # waste a round trip.
        if not ids:
            return []
        url = "/v2/worlds"
        params = {"ids": ",".join(str(i) for i in ids)}
        data = await self._get_with_retries(url, params=params, auth_required=False)
        # ``data`` here is a list of world records; validate each row.
        return [WorldInfo.model_validate(row) for row in data]

    async def _get_with_retries(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        auth_required: bool = True,
    ) -> Any:
        """GET with 429 retry + non-2xx -> typed-error mapping.

        Returns the parsed JSON body, which is either ``dict[str, Any]``
        (for ``/v2/account``) or ``list[dict[str, Any]]`` (for
        ``/v2/worlds``). Both shapes come out of ``httpx.Response.json()``,
        which mypy types as ``Any``; we forward that so the caller can
        validate via the relevant pydantic model (``AccountInfo`` or
        ``WorldInfo`` respectively).
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                msg = f"{url}: transport error: {exc}"
                raise GuildWars2HttpError(msg) from exc

            if response.status_code == 429:
                if attempt >= _MAX_RATE_LIMIT_RETRIES:
                    msg = f"{url}: rate-limited after {attempt} attempts"
                    raise GuildWars2RateLimitError(msg)
                # Exponential backoff: 0.5, 1.0, 2.0, ...
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
                continue

            if response.status_code == 401 and auth_required:
                msg = f"{url}: 401 unauthorized (check GW2_API_KEY scope)"
                raise GuildWars2HttpError(msg)

            if response.status_code >= 400:
                msg = f"{url}: HTTP {response.status_code}: {response.text[:200]}"
                raise GuildWars2HttpError(msg)

            return response.json()


__all__ = [
    "AsyncGuildWars2Client",
    "GuildWars2Client",
]
