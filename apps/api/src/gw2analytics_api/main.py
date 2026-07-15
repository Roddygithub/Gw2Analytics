"""FastAPI application entrypoint.

Wiring lives here; routes import no FastAPI primitives, only their
sub-router. We expose CORS, ``/healthz``, and the v1 routers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from fastapi_mcp import FastApiMCP  # type: ignore[import-untyped]
from prometheus_client import generate_latest

# v0.10.8 plan 140 plan 140 Fix-E: switched from module-local binding to
# live attribute lookup. The module-local binding (``from ... import
# check_schema_drift``) created a snapshot at import time; conftest.py
# autouse fixtures monkeypatching ``gw2analytics_api.schema_guard.
# check_schema_drift`` then had no effect on main.py's local binding,
# surfacing ``alembic.util.exc.CommandError: Path doesn't exist: alembic``
# when the lifespan ran. Live attribute lookup via
# ``schema_guard.check_schema_drift()`` resolves the monkeypatch path
# mismatch (test_main_mount_order.py:1 Fix-D residual failure).
from gw2analytics_api import schema_guard
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
from gw2analytics_api.workers.stuck_upload_sweeper import lifespan_stuck_upload_sweeper
from gw2analytics_api.workers.webhook_scheduler import lifespan_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """App-wide lifespan.

    v0.10.1 plan 010: schema-drift guard + Arq pool init are the
    first two steps. The webhook retry+DLQ scheduler (v0.9.1) keeps
    running in-process as before.

    Order of operations
    -------------------
    1. **Schema-drift guard** (fail-fast): if the live DB
       ``alembic_version`` does not match the alembic head on
       disk, raise :class:`RuntimeError` BEFORE any other init.
       A misconfigured DB schema would otherwise produce a
       silent log-spam failure (every scheduler tick would
       fail with ``UndefinedColumn``).
    2. **Arq pool init** (graceful fallback): try to connect
       to the Redis broker. On success, the CPU-bound parser
       pipeline runs in a dedicated Arq worker process (no
       GIL contention with the API event loop). On failure
       (Redis down, port misconfigured), log a WARNING + set
       the pool to ``None``; the upload route's
       ``BackgroundTasks`` fallback then handles parses
       synchronously. The API still serves traffic, just
       slower at high upload volume.
    3. **Webhook retry+DLQ scheduler** (v0.9.1, unchanged):
       5s poll loop, runs in-process.
    """
    # Step 1: schema-drift guard. Raises RuntimeError on
    # drift (with an actionable operator-facing message
    # naming both heads). Set ``SKIP_SCHEMA_GUARD=1`` to
    # bypass in emergencies.
    schema_guard.check_schema_drift()

    # Step 2: Arq pool init with graceful fallback. The
    # lazy imports keep the cold-start path lightweight
    # (the upload route's asyncio.to_thread fallback does
    # not need arq + redis to be importable for the API
    # to start; only the enqueue_job path needs them).
    # ``noqa: PLC0415`` suppresses ruff's "import should be
    # at the top of the file" because the lazy import is
    # intentional: a misconfigured env without arq installed
    # should NOT prevent the API from starting (the route
    # handler's BackgroundTasks fallback handles uploads
    # without arq).
    _app.state.arq_pool = None
    try:
        import redis.exceptions  # noqa: PLC0415
        from arq import create_pool  # noqa: PLC0415

        from gw2analytics_api.workers.parser_settings import WorkerSettings  # noqa: PLC0415

        _app.state.arq_pool = await create_pool(WorkerSettings.redis_settings)
        logger.info("arq pool initialised (host=%s)", WorkerSettings.redis_settings.host)
    except (
        ConnectionError,
        OSError,
        TimeoutError,
        redis.exceptions.RedisError,
    ) as exc:
        # The try/except is intentionally narrow: arq is documented
        # to raise ``ConnectionError`` (Redis unreachable), ``OSError``
        # (DNS), and ``TimeoutError`` (slow broker) on init failure.
        # In practice the underlying ``redis-py`` library's exceptions
        # (``redis.exceptions.ConnectionError``,
        # ``redis.exceptions.TimeoutError``) are SUBCLASSES of
        # ``redis.exceptions.RedisError`` (NOT the builtin
        # ``ConnectionError`` / ``TimeoutError``), so the bare
        # builtins do NOT catch them. We add ``RedisError`` to the
        # tuple to catch the unwrapped redis exceptions that reach
        # ``arq.create_pool`` in some arq versions. Other exception
        # classes (e.g. ``AttributeError`` from a typo'd
        # ``redis_settings``) propagate so a misconfigured deployment
        # surfaces the underlying misconfiguration rather than masking
        # it with a misleading "arq pool init failed" warning.
        # v0.10.15 plan 032: narrowed from ``except Exception`` to the
        # 4 specific exception classes documented in this comment;
        # an ``AttributeError`` / ``KeyError`` / ``ImportError`` now
        # propagates.
        logger.exception(
            "arq pool init failed (type=%s); uploads will use the "
            "BackgroundTasks fallback (slower on parallel "
            "uploads, but functional)",
            type(exc).__name__,
        )

    # Step 3: webhook retry+DLQ scheduler (v0.9.1, unchanged).
    scheduler_task = asyncio.create_task(lifespan_scheduler(get_sessionmaker()))
    # v0.10.12 plan 014: stuck-upload sweeper (marks stale pending
    # uploads as failed when the arq worker dies mid-parse).
    sweeper_task = asyncio.create_task(
        lifespan_stuck_upload_sweeper(get_sessionmaker()),
    )
    try:
        yield
    finally:
        sweeper_task.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper_task
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
        if _app.state.arq_pool is not None:
            await _app.state.arq_pool.aclose()


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


@app.get("/api/v1/metrics", include_in_schema=False)
def metrics() -> FastAPIResponse:
    """Prometheus metrics endpoint (plan 017).

    Returns all registered metrics in Prometheus exposition format.
    The Content-Type is set to text/plain; version 0.0.4 of the
    Prometheus exposition format is used.
    """
    return FastAPIResponse(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


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
