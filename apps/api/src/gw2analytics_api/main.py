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
from fastapi_mcp import FastApiMCP
from minio.error import InvalidResponseError, S3Error
from prometheus_client import generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
from gw2analytics_api.config import get_settings, setup_logging
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.limiter import limiter
from gw2analytics_api.metrics import SKILLS_CATALOG_FRESHNESS_DAYS
from gw2analytics_api.middleware import RequestIDMiddleware
from gw2analytics_api.routes import (
    account,
    fights,
    guilds,
    health,
    player_compare,
    players,
    skills,
    uploads,
    webhooks,
)
from gw2analytics_api.storage import get_minio
from gw2analytics_api.workers.stuck_upload_sweeper import lifespan_stuck_upload_sweeper
from gw2analytics_api.workers.webhook_scheduler import lifespan_scheduler

# Phase 6.2: structured JSON logging for the API process.
setup_logging()

logger = logging.getLogger(__name__)


def _check_minio_connectivity() -> None:
    """Check MinIO connectivity at startup, logging warnings on failure."""
    s = get_settings()
    try:
        minio_client = get_minio()
        minio_client.list_buckets()
        logger.info(
            "MinIO connectivity OK (endpoint=%s, bucket=%s)",
            s.minio_endpoint,
            s.minio_bucket,
        )
    except S3Error as exc:
        s3_code = exc.code or ""
        if s3_code in ("SignatureDoesNotMatch", "InvalidAccessKeyId", "AccessDenied"):
            logger.error(
                "MinIO CREDENTIAL MISMATCH (endpoint=%s, code=%s): "
                "the configured S3_ACCESS_KEY / S3_SECRET_KEY do not "
                "match the server. Uploads will fail with 503. "
                "Fix the credentials and restart the API.",
                s.minio_endpoint,
                s3_code,
            )
        else:
            logger.error(
                "MinIO UNREACHABLE (endpoint=%s, code=%s): "
                "uploads will fail until the storage server is restored.",
                s.minio_endpoint,
                s3_code,
            )
    except (ConnectionError, OSError, TimeoutError) as exc:
        logger.error(
            "MinIO connection failed (endpoint=%s, type=%s): "
            "uploads will fail until the storage server is reachable.",
            s.minio_endpoint,
            type(exc).__name__,
        )


async def _init_arq_pool(app: FastAPI) -> None:
    """Initialise Arq pool with retry + graceful fallback.

    v0.15.1: added retry loop (3 attempts, 2s→4s→8s backoff)
    because Redis is often not ready when the API starts.
    """
    retry_attempts = 3
    retry_base_s = 2.0
    for attempt in range(1, retry_attempts + 1):
        try:
            import redis.exceptions  # noqa: PLC0415
            from arq import create_pool  # noqa: PLC0415

            from gw2analytics_api.workers.parser_settings import (  # noqa: PLC0415
                WorkerSettings,
            )

            app.state.arq_pool = await create_pool(
                WorkerSettings.redis_settings,
            )
            logger.info(
                "arq pool initialised (host=%s, attempt=%d)",
                WorkerSettings.redis_settings.host,
                attempt,
            )
            return
        except (
            ConnectionError,
            OSError,
            TimeoutError,
            redis.exceptions.RedisError,
        ) as exc:
            if attempt < retry_attempts:
                delay = retry_base_s * (2 ** (attempt - 1))
                logger.warning(
                    "arq pool init attempt %d/%d failed (type=%s); retrying in %.0fs",
                    attempt,
                    retry_attempts,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.exception(
                    "arq pool init failed after %d attempts "
                    "(type=%s); uploads will use the in-request "
                    "fallback (slower on parallel uploads, but "
                    "functional)",
                    retry_attempts,
                    type(exc).__name__,
                )


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

    # Step 1b: MinIO connectivity check (v0.10.26-pre).
    _check_minio_connectivity()

    # Phase 6.1: OpenTelemetry bootstrap. Conditional on
    # ``OTEL_EXPORTER_OTLP_ENDPOINT`` -- no-op (zero overhead) when
    # the endpoint is unset (tests, local dev without an OTLP
    # collector). When set, init_otel wires FastAPI + Redis +
    # SQLAlchemy (the latter via ``database._maybe_instrument_sqlalchemy``
    # which fires when ``get_engine()`` is first called) AND sets
    # the global TracerProvider so RequestIDMiddleware can read the
    # current span's trace_id. Lazy import keeps the cold-startup
    # footprint minimal (the OTel SDK is ~2 MB of code).
    from gw2analytics_api.observability import init_otel  # noqa: PLC0415
    init_otel(_app, get_settings())

    # Step 2: Arq pool init with retry + graceful fallback.
    # v0.15.1: added retry loop (3 attempts, 2s→4s→8s backoff).
    _app.state.arq_pool = None
    await _init_arq_pool(_app)

    # Step 3: webhook retry+DLQ scheduler (v0.9.1, unchanged).
    scheduler_task = asyncio.create_task(lifespan_scheduler(get_sessionmaker()))
    # v0.10.12 plan 014: stuck-upload sweeper (marks stale pending
    # uploads as failed when the arq worker dies mid-parse).
    sweeper_task = asyncio.create_task(
        lifespan_stuck_upload_sweeper(get_sessionmaker()),
    )
    # Step 4: skills catalog eager-load.
    try:
        catalog = skills.load_skills()
        _app.state.skill_catalog = catalog
        logger.info("skills catalog eager-loaded: %d entries", len(catalog))
        _set_catalog_freshness_gauge()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logger.warning(
            "skills catalog eager-load failed (type=%s); "
            "/api/v1/skills endpoint will return 503 SKILLS_UNAVAILABLE",
            type(exc).__name__,
            exc_info=True,
        )
        _app.state.skill_catalog = None
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
        # Phase 6.1: OTel shutdown AFTER arq_pool so any final
        # worker spans captured during arq teardown are exported
        # before the TracerProvider flushes + closes. The 5s timeout
        # bounds the synchronous provider.shutdown() flush against
        # a black-holed OTLP collector (OTel's shutdown() doesn't
        # accept a timeout arg itself; observability.shutdown_otel
        # wraps it in a future with ThreadPoolExecutor).
        # ``asyncio.to_thread`` keeps the event loop responsive
        # during the bounded 5s wait -- a synchronous call here
        # would block the entire uvicorn process for up to 5s on a
        # hung collector (FastAPI lifespan shutdown is
        # critical-path time). ``asyncio`` is already imported at
        # the top of this module.
        from gw2analytics_api.observability import shutdown_otel  # noqa: PLC0415
        await asyncio.to_thread(shutdown_otel, timeout_s=5.0)


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
    version="0.10.25",
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

# Rate limiting (slowapi) — v0.13.4.
# Uses X-Forwarded-For when behind a reverse proxy (Caddy),
# falling back to the direct client IP.
app.state.limiter = limiter
# slowapi's _rate_limit_exceeded_handler accepts RateLimitExceeded
# (a subclass of Exception) but Starlette's type signature expects
# the wider Exception type — this is a safe narrowing in practice.
app.add_exception_handler(429, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

# Phase 6.2: request ID middleware — injects X-Request-Id into
# every response and sets ``request.state.request_id`` for
# structured log correlation. Added AFTER SlowAPIMiddleware so
# rate-limited requests still get a request_id in the error log.
app.add_middleware(RequestIDMiddleware)


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness probe with catalog freshness gauge and backend checks.

    Returns ``{"status": "ok"}`` when healthy. Also checks:
    - S3/MinIO connectivity (basic bucket list attempt)
    - DB connectivity (simple SELECT 1)
    The Prometheus ``skills_catalog_freshness_days`` gauge (set at startup)
    surfaces catalog staleness via ``GET /api/v1/metrics``.

    Phase 1.4: both backend checks are best-effort (they log warnings
    on failure but do NOT degrade the health probe to ``unhealthy``)
    because the API can still serve cached/static data without them.
    """
    # DB connectivity check
    try:
        from gw2analytics_api.database import get_sessionmaker  # noqa: PLC0415

        sm = get_sessionmaker()
        with sm() as session:
            session.execute(text("SELECT 1"))
    except (SQLAlchemyError, ConnectionError, TimeoutError, OSError):
        logger.warning("/healthz: DB connectivity check failed", exc_info=True)

    # S3/MinIO connectivity check
    try:
        minio_client = get_minio()
        minio_client.list_buckets()
    except (S3Error, ConnectionError, OSError, TimeoutError, InvalidResponseError):
        logger.warning("/healthz: S3 connectivity check failed", exc_info=True)

    return {"status": "ok"}


def _set_catalog_freshness_gauge() -> None:
    """Compute the catalog NDJSON file's age in days and set the gauge.

    Reads the file's ``st_mtime`` and compares it to the current time.
    If the file path cannot be resolved (e.g. test context with a
    synthetic catalog path), the gauge is not set (no-op).
    """
    import time  # noqa: PLC0415

    try:
        mtime = skills._SKILLS_DATA_PATH.stat().st_mtime
        age_seconds = time.time() - mtime
        age_days = age_seconds / 86400.0
        SKILLS_CATALOG_FRESHNESS_DAYS.set(age_days)
        logger.info(
            "skills catalog freshness: %.1f days (mtime=%s)",
            age_days,
            skills._SKILLS_DATA_PATH,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        logger.warning(
            "skills catalog freshness gauge not set: %s (%s)",
            type(exc).__name__,
            exc,
        )


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
app.include_router(guilds.router)
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
app.include_router(skills.router)

FastApiMCP(app).mount()

__all__ = ["app"]
