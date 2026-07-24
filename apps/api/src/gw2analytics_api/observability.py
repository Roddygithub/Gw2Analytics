"""Phase 6.1: OpenTelemetry auto-instrumentation bootstrap.

Wires OTel SDK + OTLP-over-HTTP exporter + auto-instrumentation for
FastAPI and Redis (the SQLAlchemy engine instrumentation lives in
``database.py`` because the engine is at module-load time). When
``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset, this module is a no-op
(``init_otel`` returns immediately -- zero overhead in tests and
local dev).

Why env-gated
=============
The OTel SDK initialization is a global side effect (sets the
process-wide global TracerProvider). Gating on an env var means
test runs that do not set the endpoint do not accidentally
export spans to a real backend; CI integrations that do not
set the env var pay zero setup cost.

Exporter choice
===============
HTTP/protobuf (``opentelemetry-exporter-otlp-proto-http``) over
gRPC (``opentelemetry-exporter-otlp-proto-grpc``): no native
dependencies (gRPC requires compiling C extensions), so the
``Dockerfile`` keeps a pure-Python image. The HTTP exporter also
works with any OTLP-compatible collector (Tempo, Honeycomb,
Grafana Cloud, Jaeger-with-OTLP-receiver).

Why not the OTel auto-instrumentation CLI (``opentelemetry-instrument``)
=========================================================================
The OTel-distro auto-injection is opaque; we lose the clean
conditional setup + the per-instrumentation error handling the
explicit-import approach gives. The explicit-import approach also
keeps the ``init_otel`` function unit-testable (the distro swallowed
all startup events).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from gw2analytics_api.config import Settings

logger = logging.getLogger(__name__)

# Module-level idempotency guard, refactored away from a raw
# module global to satisfy Ruff PLW0603 (which discourages
# ``global`` statements). ``init_otel`` flips
# ``_otel_state.initialized`` to ``True`` after successfully
# wiring the TracerProvider + instrumentors; ``shutdown_otel``
# flips it back. Calling ``init_otel`` twice in the same process
# would otherwise log a "set_tracer_provider called multiple
# times" warning from the OTel SDK AND would re-instrument
# FastAPI middleware (duplicate span wrappers). Tests mutate
# ``_otel_state.initialized`` directly to force re-init in
# isolation.


class _OtelState:
    """Mutable OTel lifecycle state container (intentionally trivial).

    Wrapped in a class so :func:`init_otel` and :func:`shutdown_otel`
    can mutate :attr:`initialized` WITHOUT ``global`` statements
    (Ruff PLW0603 discourages touching module globals).
    """

    initialized: bool = False


_otel_state = _OtelState()


def init_otel(app: FastAPI, settings: Settings) -> bool:
    """Initialise OpenTelemetry tracing for the apps/api process.

    Auto-instruments FastAPI (on the app instance) and Redis
    (global, no per-instance wiring needed). SQLAlchemy
    instrumentation lives in ``database.py`` so the engine at
    module-load time sees the OTel provider.

    Returns ``True`` if OTel is wired, ``False`` if no endpoint is
    configured. Idempotent at the module level (the
    :attr:`_OtelState.initialized` flag on
    :data:`_otel_state` short-circuits second invocations) AND
    at the OTel SDK level (the global TracerProvider is reused
    across calls).

    Args:
        app: The FastAPI app instance to instrument. Must be the
            SAME instance the API serves under (`app` from
            ``main.py``); passing a stub triggers OTel's no-op
            guard.
        settings: The Settings instance; reads
            ``otel_exporter_otlp_endpoint`` and ``otel_service_name``.
    """
    if not settings.otel_exporter_otlp_endpoint:
        logger.info(
            "OTEL_EXPORTER_OTLP_ENDPOINT not set -- skipping init_otel; "
            "/api/v1/metrics endpoint (Prometheus) still serves."
        )
        return False
    if _otel_state.initialized:
        logger.info("OTel already initialised (idempotent no-op)")
        return True

    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    exporter = OTLPSpanExporter(
        endpoint=settings.otel_exporter_otlp_endpoint,
    )
    # Idempotent at the SDK level: set_tracer_provider is a no-op
    # if a provider was already set in this process, and
    # BatchSpanProcessor is a fresh instance for this OTel wiring.
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(
        "OTel wired: service=%s endpoint=%s",
        settings.otel_service_name,
        settings.otel_exporter_otlp_endpoint,
    )

    # FastAPI: scope to this app instance. The OTel library wraps
    # the app's middleware stack such that the OTel span opens at
    # request entry -- before RequestIDMiddleware dispatches. This
    # lets RequestIDMiddleware read trace.get_current_span() and
    # use the trace_id as the request_id (the bridge documented
    # in Phase 6.1's RequestIDMiddleware module docstring).
    FastAPIInstrumentor().instrument_app(app=app)

    # Redis (ARQ broker): global hook on the redis-py client class.
    # ``is_instrumented_by_opentelemetry`` returning True after the
    # first call prevents double-wrap on re-init from test fixtures.
    if not RedisInstrumentor().is_instrumented_by_opentelemetry:
        RedisInstrumentor().instrument()

    _otel_state.initialized = True
    return True


def shutdown_otel(*, timeout_s: float = 5.0) -> None:
    """Flush pending spans and shut down the OTel TracerProvider.

    Bounded by ``timeout_s`` (default 5 s) because
    :meth:`opentelemetry.sdk.trace.TracerProvider.shutdown` does
    NOT accept a timeout parameter and performs synchronous
    network flushes; a black-holed OTLP collector would otherwise
    block the FastAPI lifespan shutdown indefinitely. The
    executor-submit + :meth:`concurrent.futures.Future.result` pattern
    is the canonical Python workaround for sync-with-timeout
    against a parameterless blocking call.

    Safe to call when OTel was never initialised: returns
    immediately and does NOT touch the global TracerProvider.
    Safe to call multiple times: second-and-later calls are no-ops
    once :attr:`_OtelState.initialized` is back to ``False`` from
    the first shutdown.
    """
    if not _otel_state.initialized:
        return

    import concurrent.futures  # noqa: PLC0415

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(provider.shutdown)
                future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "OTel shutdown timed out after %.1fs; spans may be lost",
                timeout_s,
            )
        except Exception:
            # Belt-and-braces: an unrecoverable OTLP exporter error
            # during shutdown MUST NOT crash the lifespan teardown.
            logger.exception("OTel shutdown error (suppressed)")

    _otel_state.initialized = False
    logger.info("OTel shutdown completed")


__all__ = ["init_otel", "shutdown_otel"]
