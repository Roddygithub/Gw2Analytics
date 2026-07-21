"""Rate limiter singleton (slowapi).

Defined in a separate module so both :mod:`main` (middleware wiring)
and route modules (``@limiter.limit`` decorators) can import it
without creating a circular dependency between ``main`` and the
route modules it includes.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

# Default 100/min for all endpoints. The upload endpoint overrides
# this to 5/min via @limiter.limit("5/minute") decorator.
# Uses X-Forwarded-For when behind a reverse proxy (Caddy),
# falling back to the direct client IP.
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

__all__ = ["limiter"]
