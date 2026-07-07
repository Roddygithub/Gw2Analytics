"""``GET /api/v1/account`` -- GW2 API key -> (world_id, world_name, world_population).

Auth
====
A Guild Wars 2 API key is supplied via ``Authorization: Bearer <key>``.
The key is **not** persisted anywhere in :mod:`apps/api` -- it is used
only to compose the upstream ``account_get`` + ``worlds_get`` calls
into one response, then discarded on context manager exit.

Why this lives in :mod:`apps.api`
=================================
``gw2_core`` is the cross-layer contract and ``apps/api`` is the thin
HTTP layer around it. Composing upstream calls into a single
domain-shaped response is exactly the kind of thin serialization this
app is for. We deliberately do NOT mutate persistent state here, so
this endpoint is a pure ``GET`` with no side effects.

Why it's async
==============
The DataForged upstream path uses :class:`AsyncGuildWars2Client`
which is an ``httpx.AsyncClient``-backed wrapper. FastAPI handles
async routes by routing them through the event loop via ``anyio``;
the verification suite exercises this via :class:`fastapi.testclient.TestClient`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gw2_api_client import AsyncGuildWars2Client
from gw2_api_client.exceptions import (
    GuildWars2ClientError,
    GuildWars2HttpError,
    GuildWars2RateLimitError,
)
from gw2analytics_api.schemas import AccountEnrichedOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/account", tags=["account"])

# ``auto_error=False`` so the route body owns the 401 surface (and can
# set ``WWW-Authenticate: Bearer`` deterministically) instead of the
# framework's auto-generated message.
_bearer = HTTPBearer(auto_error=False)


@router.get("", response_model=AccountEnrichedOut)
async def get_account_enriched(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> AccountEnrichedOut:
    """Resolve a GW2 API key to ``(world_id, world_name, world_population)``.

    Composes :meth:`AsyncGuildWars2Client.account_get` with
    :meth:`AsyncGuildWars2Client.worlds_get` so a single request to
    this endpoint fans out to two upstream v2 calls (account + world)
    and returns a deterministic triple to the caller.
    """
    if credentials is None or not credentials.credentials.strip():
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    api_key = credentials.credentials.strip()
    try:
        async with AsyncGuildWars2Client(api_key=api_key) as client:
            account = await client.account_get()
            worlds = await client.worlds_get([account.world_id])
    except GuildWars2RateLimitError as exc:
        logger.warning("/api/v1/account upstream rate-limited: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "upstream rate-limited",
        ) from exc
    except GuildWars2HttpError as exc:
        # ``str(exc)`` carries the upstream status code via two
        # ``_get_with_retries`` message formats (see
        # ``libs/gw2_api_client/client.py``):
        #   - auth-required 401 -> ``"<url>: 401 unauthorized (...)"``
        #   - other 4xx/5xx ->    ``"<url>: HTTP <code>: <body[:200]>"``
        # Match the two message forms exactly so a 5xx response whose
        # body happens to contain the literal ``"401"`` does not get
        # misrouted to our 401.
        logger.warning("/api/v1/account upstream http error: %s", exc)
        msg = str(exc)
        if "401 unauthorized" in msg or "HTTP 401:" in msg:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "invalid api key",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "upstream error",
        ) from exc
    except GuildWars2ClientError as exc:
        logger.exception("/api/v1/account unexpected client error")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "upstream error",
        ) from exc

    if not worlds:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"upstream returned no world for world_id={account.world_id}",
        )

    world = worlds[0]
    return AccountEnrichedOut(
        world_id=world.id,
        world_name=world.name,
        world_population=world.population.value,
    )


__all__ = ["router"]
