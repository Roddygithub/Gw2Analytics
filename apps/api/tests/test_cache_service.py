"""Behavioral tests for Redis cache fallback and invalidation semantics."""

from __future__ import annotations

from typing import Any

import pytest

from gw2analytics_api.services import cache_service


class _Redis:
    def __init__(self, *, cached: str | None = None, get_error: Exception | None = None) -> None:
        self.cached = cached
        self.get_error = get_error
        self.set_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.set_calls: list[tuple[str, int, str]] = []
        self.deleted: list[str] = []
        self.closed = False

    async def get(self, key: str) -> str | None:
        if self.get_error:
            raise self.get_error
        return self.cached

    async def setex(self, key: str, ttl: int, value: str) -> None:
        if self.set_error:
            raise self.set_error
        self.set_calls.append((key, ttl, value))

    async def delete(self, key: str) -> None:
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(key)

    async def aclose(self) -> None:
        self.closed = True


def _service(monkeypatch: pytest.MonkeyPatch, redis: _Redis) -> cache_service.CacheService:
    def factory(*_args: Any, **_kwargs: Any) -> _Redis:
        return redis

    monkeypatch.setattr(cache_service.aioredis, "from_url", factory)
    return cache_service.CacheService(default_ttl=45)


@pytest.mark.asyncio
async def test_get_or_compute_returns_json_cache_hit_without_computing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis(cached='{"players": 3}')
    service = _service(monkeypatch, redis)
    called = False

    async def compute() -> dict[str, int]:
        nonlocal called
        called = True
        return {"players": 0}

    assert await service.get_or_compute("players", compute) == {"players": 3}
    assert called is False
    assert redis.set_calls == []


@pytest.mark.asyncio
async def test_get_or_compute_recomputes_corrupt_or_unavailable_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis(cached="not-json")
    service = _service(monkeypatch, redis)

    async def compute() -> dict[str, Any]:
        return {"value": object()}

    result = await service.get_or_compute("broken", compute, ttl=12)
    assert "value" in result
    assert redis.set_calls[0][:2] == ("broken", 12)

    redis.get_error = ConnectionError("redis down")
    assert await service.get_or_compute("offline", lambda: _value("fallback")) == "fallback"
    assert redis.set_calls[1] == ("offline", 45, '"fallback"')


async def _value(value: Any) -> Any:
    return value


@pytest.mark.asyncio
async def test_cache_write_and_invalidation_failures_are_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis()
    service = _service(monkeypatch, redis)
    redis.set_error = TypeError("not serializable")

    assert await service.get_or_compute("uncacheable", lambda: _value({"ok": True})) == {"ok": True}

    redis.delete_error = ConnectionError("redis down")
    await service.invalidate("uncacheable")
    assert redis.deleted == []

    redis.delete_error = None
    await service.invalidate("uncacheable")
    await service.close()
    assert redis.deleted == ["uncacheable"]
    assert redis.closed is True
