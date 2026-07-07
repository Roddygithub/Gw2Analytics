"""FastAPI application entrypoint.

Wiring lives here; routes import no FastAPI primitives, only their
sub-router. We expose CORS, ``/healthz``, and the v1 routers.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import FastApiMCP  # type: ignore[import-untyped]

from gw2analytics_api.config import get_settings
from gw2analytics_api.routes import account, fights, health, players, uploads

app = FastAPI(
    title="GW2Analytics API",
    description=(
        "WvW combat-log ingestion + analytics. Wires gw2_evtc_parser behind "
        "a MinIO blob store and Postgres fight tables (Phase 2)."
    ),
    # v0.7.0: adds the player-centric surface (GET /api/v1/players +
    # GET /api/v1/players/{account_name}) and the per-fight squad
    # (GET /api/v1/fights/{id}/squads) + skill (GET /api/v1/fights/{id}/skills)
    # roll-ups. The per-target damage + healing + buff-removal trio
    # and the per-bucket event windows stay locked at the 0.3.0
    # contract.
    # v0.8.4: materialises the per-(fight, account_name) roll-up in
    # the new `OrmFightPlayerSummary` table so the player routes
    # serve the per-account view with a pure SQL aggregation
    # (avoids the 5-30s latency for users with 100+ fights
    # documented in the v0.7.0 CHANGELOG).
    # v0.8.6: adds the operational health probe
    # (GET /api/v1/health/summary) that surfaces the fight-summary
    # population drift -- the integration point for the
    # operational cron that runs the v0.8.5 backfill script.
    version="0.8.6",
)

# CORS — wide-open by default for local dev (Next.js at :3000,
# curl from any origin). Override in production via
# ``CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com``.
# The ``Settings.cors_allowed_origins`` field parses a comma-separated
# env string into a list; the middleware reads it once on app init
# (lru_cached: any test that mutates the env VAR AFTER
# ``from gw2analytics_api.main import app`` will see the stale value).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(uploads.router)
app.include_router(fights.router)
app.include_router(players.router)
app.include_router(account.router)
app.include_router(health.router)

FastApiMCP(app).mount()

__all__ = ["app"]
