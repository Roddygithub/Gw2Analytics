"""Optional authentication layer for non-public endpoints.

Provides a ``require_auth`` decorator that can be applied to routes
that should not be publicly accessible. In the current deployment
model, authentication is handled at the reverse-proxy level (Caddy);
this decorator is a defense-in-depth measure for deployments that
need an additional gate.

Usage
-----
::

    from gw2analytics_api.auth import require_auth

    @router.get("/admin/sensitive")
    @require_auth
    def sensitive_endpoint(...):
        ...

The decorator checks for an ``X-API-Key`` header matching the
``API_KEY`` env var. If the env var is not set, the decorator
is a no-op (all requests pass through). This lets local dev
environments run without an API key while production deployments
can opt in by setting ``API_KEY``.

The ``API_KEY`` is loaded from :class:`gw2analytics_api.config.Settings`
so it follows the same env-var conventions as all other config.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from fastapi import HTTPException, Request, status

from gw2analytics_api.config import get_settings

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


def require_auth(func: _F) -> _F:  # noqa: UP047
    """Decorator: require ``X-API-Key`` header matching ``API_KEY`` env var.

    When ``API_KEY`` is not set (local dev), the decorator is a no-op.
    When set, the request MUST carry the matching header or a 401 is
    returned immediately (before the handler runs).

    Supports both sync and async handler functions. FastAPI auto-detects
    the coroutine-ness and calls it appropriately.
    """

    @wraps(func)
    async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
        settings = get_settings()
        api_key: str | None = getattr(settings, "api_key", None)
        if not api_key:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result

        request: Request | None = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        if request is None:
            for _k, v in kwargs.items():
                if isinstance(v, Request):
                    request = v
                    break

        if request is None:
            logger.warning("require_auth: no Request found in handler args; skipping auth check")
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result

        header_key = request.headers.get("X-API-Key")
        if not header_key or header_key != api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid X-API-Key header",
            )

        result = func(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    return _async_wrapper  # type: ignore[return-value]


__all__ = ["require_auth"]
