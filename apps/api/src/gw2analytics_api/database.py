from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import cache

from sqlalchemy import DateTime, Engine, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from gw2analytics_api.config import get_settings


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


@cache
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine, built on first call."""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
    )


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
