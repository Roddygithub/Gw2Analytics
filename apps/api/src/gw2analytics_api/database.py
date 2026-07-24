from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import cache

from sqlalchemy import DateTime, Engine, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from gw2analytics_api.config import get_settings

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in this app."""


class TimestampMixin:
    """Mixin adding ``created_at`` and ``updated_at`` columns.

    ``created_at`` defaults to ``now()`` on INSERT.
    ``updated_at`` updates to ``now()`` on every UPDATE.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def _maybe_instrument_sqlalchemy(engine: Engine) -> None:
    """Conditionally instrument the SQLAlchemy engine via OTel (Phase 6.1).

    Phase 6.1: when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, wrap the
    engine so SQLAlchemy query spans (``db.client.duration``,
    ``db.client.connections.usage``) are exported. The
    ``SQLAlchemyInstrumentor().instrument(engine=engine)`` call is
    idempotent across ``get_engine()`` re-invocations (post-init).
    Import is deferred to keep the import graph clean for callers
    that do not use OTel (test runs + local dev without a
    collector).
    """
    settings = get_settings()
    if not settings.otel_exporter_otlp_endpoint:
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import (
            SQLAlchemyInstrumentor,
        )
    except ImportError:
        # Defensive: the ``opentelemetry-instrumentation-sqlalchemy``
        # package is in ``pyproject.toml`` deps (Phase 6.1) but if
        # a future uv-pin removes it, instrumentation silently
        # no-ops instead of crash-on-import. Track via CI if it
        # ever fires.
        return
    try:
        if not SQLAlchemyInstrumentor().is_instrumented_by_opentelemetry:
            SQLAlchemyInstrumentor().instrument(engine=engine)
    except Exception:
        # Do NOT block startup on instrumentation glitches. Log
        # + carry on un-instrumented; the API serves traffic
        # identically either way.
        logger.warning(
            "SQLAlchemy OTel instrumentation failed; "
            "engine runs un-instrumented",
            exc_info=True,
        )


@cache
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine, built on first call.

    Phase 6.1: when OTel is env-gated, instrument the engine
    post-create via ``SQLAlchemyInstrumentor``. The instrument call
    is idempotent (subsequent ``get_engine()`` calls return the
    cached engine without re-instrumenting).
    """
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
    )
    _maybe_instrument_sqlalchemy(engine)
    return engine


@cache
def get_sessionmaker() -> sessionmaker[Session]:
    """Return the process-wide sessionmaker."""
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a SQLAlchemy Session per request."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
