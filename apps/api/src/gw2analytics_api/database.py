from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gw2analytics_api.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in this app."""


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
