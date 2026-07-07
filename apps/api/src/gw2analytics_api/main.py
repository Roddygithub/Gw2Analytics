"""FastAPI application entrypoint.

Wiring lives here; routes import no FastAPI primitives, only their
sub-router. We expose CORS, ``/healthz``, and the v1 routers.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import FastApiMCP  # type: ignore[import-untyped]

from gw2analytics_api.routes import account, fights, uploads

app = FastAPI(
    title="GW2Analytics API",
    description=(
        "WvW combat-log ingestion + analytics. Wires gw2_evtc_parser behind "
        "a MinIO blob store and Postgres fight tables (Phase 2)."
    ),
    version="0.2.0",
)

# CORS — wide-open for local dev; tighten in production (Phase 3).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(uploads.router)
app.include_router(fights.router)
app.include_router(account.router)

FastApiMCP(app).mount()

__all__ = ["app"]
