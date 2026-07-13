"""SQLAlchemy 2.0 engine, sessionmaker, and declarative base.

Engine is constructed **lazily** so importing this module does not require
the database to be reachable. The :func:`get_session` dependency is what
FastAPI routes use; tests can call it directly.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gw2analytics_api.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model in this app."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine, built on first call."""
    settings = get_settings()
    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
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
