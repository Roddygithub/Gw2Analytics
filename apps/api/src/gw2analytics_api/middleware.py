"""Phase 6.2: Request ID middleware for structured log correlation.

Injects a unique ``request_id`` into every response as the
``X-Request-Id`` header. The ID resolution order is:

1. **OTel trace_id** when an active OTel span exists (Phase 6.1).
   The trace_id is formatted as a 32-char lowercase hex string
   (matches the W3C Trace Context format) and is used both for the
   ``X-Request-Id`` response header AND stored on
   ``request.state.request_id``. This bridges OTel traces with the
   existing structured-log request-ID contract so a single
   identifier flows through both systems.
2. **Incoming ``X-Request-Id`` header** if the client (or a
   reverse proxy) sets one; preserves traceability across
   multi-hop requests.
3. **Generated UUID4** as a final fallback.

The OTel-first read is safe-by-default: if OTel is disabled
(the env-gating from ``init_otel`` short-circuits), the span
context at this middleware is never valid, so we transparently
fall back to the same UUID4 path that shipped in v0.16.x.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Phase 6.1: read OTel trace_id first; fall back to header/UUID.

    Three-tier resolution documented in the module docstring. The
    OTel branch returns a 32-char lowering hex string via
    ``format(trace_id, "032x")`` -- same shape as the UUID4 hex
    we generate as a fallback, so downstream readers
    (``request.state.request_id`` consumers) do not need a
    special-case format check.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            request_id: str = format(span_context.trace_id, "032x")
        else:
            request_id = request.headers.get(
                "X-Request-Id",
                uuid.uuid4().hex,
            )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


__all__ = ["RequestIDMiddleware"]
