"""Behavioral coverage for the optional route-level API-key guard."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from gw2analytics_api import auth


def _request(api_key: str | None = None) -> Request:
    headers = [] if api_key is None else [(b"x-api-key", api_key.encode())]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.mark.asyncio
async def test_require_auth_is_a_noop_without_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key=None))

    @auth.require_auth
    def sync_handler() -> str:
        return "sync"

    @auth.require_auth
    async def async_handler() -> str:
        return "async"

    assert await sync_handler() == "sync"
    assert await async_handler() == "async"


@pytest.mark.asyncio
async def test_require_auth_rejects_missing_or_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key="expected"))

    @auth.require_auth
    def handler(request: Request) -> str:
        return "unreachable"

    for request in (_request(), _request("wrong")):
        with pytest.raises(HTTPException) as exc_info:
            await handler(request)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Missing or invalid X-API-Key header"


@pytest.mark.asyncio
async def test_require_auth_accepts_keyword_request_and_skips_missing_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(api_key="expected"))

    @auth.require_auth
    async def handler(*, request: Request) -> str:
        return "accepted"

    @auth.require_auth
    def internal_handler() -> str:
        return "internal"

    assert await handler(request=_request("expected")) == "accepted"
    assert await internal_handler() == "internal"
