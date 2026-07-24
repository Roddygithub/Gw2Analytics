"""Alembic environment config.

Reads ``DATABASE_URL`` from the app's settings and points Alembic at
the ORM metadata declared in :mod:`gw2analytics_api.database`.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from gw2analytics_api import models  # noqa: F401 -- imports register ORM tables
from gw2analytics_api.config import get_settings
from gw2analytics_api.database import Base, _normalise_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# v0.10.26-pre followup-8: thread the same driver-rewrite helper
# used by :func:`gw2analytics_api.database.get_engine` so the
# alembic CLI resolves to the workspace's installed driver
# (``psycopg`` v3). Without this, ``uv run alembic upgrade head``
# on a default ``DATABASE_URL=postgresql://...`` crashes with
# ``ModuleNotFoundError: No module named 'psycopg2'`` because
# SQLAlchemy defaults to the legacy driver when the URL has no
# ``+<driver>`` hint. The rewrite is idempotent on already-correct
# URLs (``postgresql+psycopg://`` -> unchanged).
# v0.10.26-pre followup-8: thread the helper from ``database.py`` so alembic
# resolves to psycopg v3 instead of the uninstalled legacy psycopg2 (which
# SQLAlchemy silently defaults to when the URL has no ``+<driver>`` hint).
# See ``_normalise_database_url`` for the rewrite rationale; idempotent.
config.set_main_option("sqlalchemy.url", _normalise_database_url(get_settings().database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
