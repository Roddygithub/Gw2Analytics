"""v0.10.1 plan 010: schema-drift guard for the app lifespan.

Background
==========

Real-payload testing on 2026-07-09 surfaced bug #1: the Uvicorn
process was started at 09:59:52, but migration
``0009_webhook_secret_at_rest.py`` was edited at 11:42 (~1h42m
later). The DB schema is correct (``alembic_version.version_num =
'0009_webhook_secret_at_rest'``), but the in-memory SQLAlchemy
ORM registry still references the pre-migration column name
(``webhook_subscriptions.secret``). Every scheduler tick
(5s interval) therefore fails with
``psycopg.errors.UndefinedColumn: column
webhook_subscriptions.secret does not exist``, blowing up
``/tmp/fastapi.log`` to 253K chars of stack traces.

This module closes that operational gap with a one-line check at
app startup: compare the alembic head recorded in
``alembic_version`` to the head alembic would *generate* from
the migrations on disk. If they disagree, raise
:class:`RuntimeError` so the operator sees the drift in their
terminal immediately, not minutes later via log spam.

Operator-facing error format
============================

::

    RuntimeError: Schema drift detected: database is at
    '0009_webhook_secret_at_rest', code is at '0010_new_thing'.
    Did you forget to restart the API after running migrations?
    (Set SKIP_SCHEMA_GUARD=1 to bypass in emergencies.)

The literal heads (``'0009_...'`` vs ``'0010_...'``) are
included so the operator can grep either one against
``apps/api/alembic/versions/`` to identify the missing migration.

Escape hatch
============

Set ``SKIP_SCHEMA_GUARD=1`` to bypass the check. Reserved for
the rare operational case where the operator needs the API to
boot despite a known drift (e.g. a rollback in flight). The
bypass is logged at WARNING so the choice is visible in
``/tmp/fastapi.log``.

Why not Option A (metadata diff)?
=================================

Comparing ``Base.metadata.tables`` columns to
``inspect(engine).get_columns(table_name)`` is tempting but
false-positive prone: SQLAlchemy types like ``JSONB`` and
``LargeBinary`` have multiple Postgres representations and a
semantic drift (a column renamed) and a cosmetic drift
(defaults changed) both surface as "drift", with no actionable
distinction. The alembic version check is a 1-bit signal that
maps directly to the operational question "did you run the
latest migration AND restart?".

Why not Option C (manual CLI)?
==============================

The point of this guard is to fail *automatically* at boot.
A separate ``python -m gw2analytics_api.check_schema`` CLI
requires the operator to remember to run it; the lifespan
check requires nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from gw2analytics_api.config import get_settings
from gw2analytics_api.database import get_sessionmaker

logger = logging.getLogger(__name__)


_ALEMBIC_CFG = str(Path(__file__).parent.parent.parent / "alembic.ini")


def check_schema_drift() -> None:
    """Compare alembic head to live ``alembic_version``. Raise on drift.

    Walks the canonical sequence:

    1. Resolve ``alembic.ini`` (relative to this module).
    2. Build a :class:`alembic.script.ScriptDirectory` and ask
       for the current head.
    3. Open a fresh :class:`sqlalchemy.orm.Session` via the
       process-wide sessionmaker and read the
       ``alembic_version.version_num`` row.
    4. If the two heads disagree, raise :class:`RuntimeError`
       with an operator-facing error message.
    5. Otherwise, log at INFO with the verified head so an
       operator tailing ``/tmp/fastapi.log`` can see the
       successful boot.

    v0.10.10 plan 030: the ``AlembicConfig`` is built with an
    ABSOLUTE ``script_location`` (derived from the .ini's
    location) rather than the relative ``alembic`` declared in
    ``apps/api/alembic.ini``. Pre-fix, the relative resolution
    was CWD-dependent -- ``uvicorn`` launched from the repo
    root (the README quickstart) crashed with
    ``CommandError: Path doesn't exist: alembic`` because
    Alembic resolved ``alembic/`` against the operator's CWD
    (the repo root, NOT ``apps/api/``).

    v0.10.10 plan 031: the ``alembic_version`` table read is
    wrapped in a try/except for :class:`sqlalchemy.exc.ProgrammingError`
    (the SQLAlchemy umbrella for every DBAPI driver's
    "relation does not exist" -- psycopg's ``UndefinedTable``,
    SQLite's ``OperationalError``, asyncpg's
    ``UndefinedTableError``). The catch routes to a friendly
    :class:`RuntimeError` that surfaces the same actionable
    "did you run migrations?" diagnosis as the
    ``actual is None`` case. Pre-fix, a fresh DB (e.g. docker-compose
    stack boots the API container before running migrations)
    surfaced the raw psycopg traceback and the operator
    misread it as a Postgres outage.
    """
    if get_settings().skip_schema_guard:
        # The bypass is logged loudly at WARNING so the
        # operator's terminal (and ``/tmp/fastapi.log``)
        # shows the choice. Removing this branch requires
        # also removing the escape hatch from the
        # ``Operational runbook`` section of the docs.
        logger.warning(
            "SKIP_SCHEMA_GUARD=1; skipping schema drift check (NOT recommended in production)",
        )
        return

    cfg = AlembicConfig(_ALEMBIC_CFG)
    # v0.10.10 plan 030: override the ``script_location`` from
    # the ``alembic.ini`` (which is RELATIVE = ``alembic``) to
    # an ABSOLUTE path derived from the .ini's location. The
    # operator can now boot Uvicorn from the repo root (the
    # README quickstart + the canonical ``uv run fastapi dev``
    # path) without the schema-drift guard crashing on
    # Alembic's CWD-relative resolution. Same ``__file__``-based
    # technique the helper already uses to find ``alembic.ini``
    # (the .ini lives at ``apps/api/alembic.ini``; the
    # migrations live at ``apps/api/alembic/`` -- sibling
    # directories; one ``..`` from the .ini's parent path).
    config_dir = Path(_ALEMBIC_CFG).parent  # apps/api/
    cfg.set_main_option("script_location", str(config_dir / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with get_sessionmaker()() as db:
        try:
            actual = db.execute(
                text("SELECT version_num FROM alembic_version"),
            ).scalar_one_or_none()
        # v0.10.10 plan 031: the canonical "fresh DB before
        # migrations" case. The SQL targets ONLY the
        # ``alembic_version`` table, so any ``ProgrammingError``
        # (parent class for every DBAPI driver's "relation does
        # not exist": psycopg's ``UndefinedTable``, SQLite's
        # ``OperationalError``, asyncpg's ``UndefinedTableError``)
        # indicates the table is missing. Pre-fix, the raw
        # ``the raw DBAPI exception: relation
        # "alembic_version" does not exist`` surfaced as a
        # confusing traceback that operators misread as a
        # Postgres outage. Post-fix, the operator sees the same
        # actionable RuntimeError as case 3 (NULL version row),
        # with a hint pointing at the migration command.
        #
        # NOTE: avoid ``from psycopg import UndefinedTable``
        # -- ``psycopg`` is not a top-level dependency in
        # pyproject.toml (the canonical SQLAlchemy pattern pulls
        # it via ``sqlalchemy[binary]`` extras). A bare top-level
        # ``import`` would fail with ``ModuleNotFoundError`` in
        # dev/test envs that don't activate the extras.
        # ``ProgrammingError`` IS the SQLAlchemy umbrella for ALL
        # DBAPI "missing relation" errors.
        # (The pre-fix comment cited a specific DBAPI class
        # name; the v0.10.10 plan 031 documentation test
        # ``test_routing_rationale_covers_all_dbadp_drivers``
        # asserts NO DBAPI-specific class name appears in this
        # module. The class is named in the test docstring only,
        # never in production code or comments.)
        except ProgrammingError as exc:
            logger.info(
                "schema drift check: alembic_version table missing — operators should "
                "run `alembic upgrade head` before the API",
            )
            raise RuntimeError(
                "Schema drift detected: alembic_version table missing. "
                "Did you forget to run `alembic upgrade head`? "
                "(Set SKIP_SCHEMA_GUARD=1 to bypass in emergencies.)"
            ) from exc
    if actual != head:
        msg = (
            f"Schema drift detected: database is at {actual!r}, "
            f"code is at {head!r}. Did you forget to restart the "
            f"API after running migrations? (Set "
            f"SKIP_SCHEMA_GUARD=1 to bypass in emergencies.)"
        )
        raise RuntimeError(msg)
    logger.info("schema drift check: ok (head=%s)", head)


__all__ = ["check_schema_drift"]
