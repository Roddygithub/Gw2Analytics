"""Phase 4.5: Redis-backed cache service for frequently-accessed data.

Provides a ``get_or_compute`` primitive that caches serialisable
values in Redis with a configurable TTL, reducing DB load on
hot paths (player listings, skill catalogues, squad roll-ups).

Usage::

    cache = CacheService("redis://localhost:6379")
    data = await cache.get_or_compute(
        key="players:list:v2",
        ttl=60,
        compute=compute_players,  # async callable
    )

The service uses ``redis.asyncio`` for non-blocking I/O. The
connection pool is process-wide (reused across request handlers).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheService:
    """Thin Redis cache with ``get_or_compute`` semantics.

    Thread-safe because ``redis.asyncio`` runs on a single event
    loop per process; ``get_or_compute`` is an async method that
    must be awaited from an async context (FastAPI route, Arq job).

    Parameters
    ----------
    redis_url:
        Redis connection string, e.g. ``redis://localhost:6379``.
        Defaults to the local dev instance.
    default_ttl:
        Default TTL in seconds for cached values when not specified
        on ``get_or_compute``. Default 60 seconds.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        default_ttl: int = 60,
    ) -> None:
        self._redis: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            redis_url,
            decode_responses=True,
        )
        self._default_ttl = default_ttl

    async def get_or_compute(
        self,
        key: str,
        compute: Callable[[], Coroutine[Any, Any, T]],
        ttl: int | None = None,
    ) -> T:
        """Return the cached value for ``key`` or compute + store it.

        If ``key`` exists in Redis, the JSON-deserialised value is
        returned immediately. Otherwise ``compute()`` is awaited,
        its return value is JSON-serialised and stored at ``key``
        with the given ``ttl`` (falls back to ``self._default_ttl``).

        The compute function MUST return a JSON-serialisable value
        (``str | int | float | bool | list | dict | None``).
        """
        ttl_s = ttl if ttl is not None else self._default_ttl

        try:
            cached = await self._redis.get(key)
        except ConnectionError:
            logger.warning("Redis unavailable for key %r; falling through to compute", key)
            cached = None

        if cached is not None:
            try:
                return json.loads(cached)  # type: ignore[no-any-return]
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted cache entry for key %r; recomputing", key)

        value = await compute()

        try:
            serialised = json.dumps(value, default=str)
            await self._redis.setex(key, ttl_s, serialised)
        except (TypeError, ConnectionError) as exc:
            logger.warning(
                "Failed to cache key %r (ttl=%ds): %s",
                key,
                ttl_s,
                exc,
            )

        return value

    async def invalidate(self, key: str) -> None:
        """Remove ``key`` from the cache (best-effort)."""
        try:
            await self._redis.delete(key)
        except ConnectionError:
            logger.warning("Redis unavailable; cache invalidation skipped for %r", key)

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self._redis.aclose()


__all__ = ["CacheService"]
