"""Phase 6.2: Request ID middleware for structured log correlation.

Injects a unique ``request_id`` into every response as the
``X-Request-Id`` header. The ID is either forwarded from the
incoming ``X-Request-Id`` header (set by the reverse proxy) or
generated as a UUID4 hex string. The value is also stored on
``request.state.request_id`` for access in route handlers and
dependencies.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that injects ``X-Request-Id`` into every response.

    Reads the ``X-Request-Id`` header from the incoming request
    (set by the reverse proxy / Caddy). If absent, generates a new
    UUID4 hex string. The value is set on ``request.state.request_id``
    for downstream access and echoed back in the response header for
    client-side correlation.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id: str = request.headers.get(
            "X-Request-Id",
            uuid.uuid4().hex,
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


__all__ = ["RequestIDMiddleware"]
