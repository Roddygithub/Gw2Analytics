"""FastAPI application factory and route registrations.

Only the :func:`app` instance is exported. New routes / dependencies
are wired in :mod:`.routers` (added in subsequent phases).
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="GW2Analytics API",
    version="0.0.1",
    description="WvW combat analytics for Guild Wars 2.",
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe. Returns OK if the process is alive."""
    return {"status": "ok"}
