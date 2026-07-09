"""FastAPI application entrypoint.

Wiring lives here; routes import no FastAPI primitives, only their
sub-router. We expose CORS, ``/healthz``, and the v1 routers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import FastApiMCP  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from gw2analytics_api.config import get_settings
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.routes import (
    account,
    fights,
    health,
    player_compare,
    players,
    uploads,
    webhooks,
)
from gw2analytics_api.workers.webhook_scheduler import lifespan_scheduler


def _open_session() -> Session:
    """Open a fresh SQLAlchemy `Session` for one scheduler poll iteration.

    `get_sessionmaker` returns the cached `sessionmaker[Session]` factory;
    calling this helper invokes `sessionmaker()` which yields a new
    `Session` instance. Defined as a NAMED function (vs inline lambda) so
    ruff does not flag `PLW0108 unnecessary-lambda` and so mypy sees a
    fully-typed ``Callable[[], Session]`` shape.
    """
    return get_sessionmaker()()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the v0.9.1 webhook retry+DLQ scheduler as a background
    asyncio task (design doc §5; 5s poll interval)."""
    scheduler_task = asyncio.create_task(lifespan_scheduler(_open_session))
    try:
        yield
    finally:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task


app = FastAPI(
    lifespan=lifespan,
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
    # v0.10.0 plan 032: adds the cross-account comparison
    # timeline endpoint
    # (``GET /api/v1/players/compare/timeline?accounts=A&accounts=B``)
    # so the analyst can overlay 2-4 accounts on the same chart.
    version="0.10.0",
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
# v0.10.0 plan 032: cross-account comparison timeline. MUST
# be included BEFORE the players router (or the players
# router's catch-all ``{account_name:path}`` would greedily
# match ``/api/v1/players/compare/timeline`` with
# ``account_name="compare/timeline"`` and return 404). The
# FastAPI router order matches the route-declaration order
# in the players.py module so the cross-account route stays
# declared BEFORE the catch-all (see the
# :mod:`gw2analytics_api.routes.player_compare` module
# docstring for the same rationale). The mount-order is
# also asserted by the dedicated pytest test
# :func:`tests.test_main_mount_order.test_compare_route_included_before_players`
# so a future PR that alphabetises the includes (a common
# style preference) fails the test suite rather than
# silently 404'ing every ``/players/compare/*`` call.
app.include_router(player_compare.router)
app.include_router(players.router)
app.include_router(webhooks.router)
app.include_router(account.router)
app.include_router(health.router)

FastApiMCP(app).mount()

__all__ = ["app"]
