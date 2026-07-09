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
import os
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import text

from gw2analytics_api.database import get_sessionmaker

logger = logging.getLogger(__name__)


def _alembic_cfg_path() -> str:
    """Locate ``alembic.ini`` relative to this module.

    This module lives at
    ``apps/api/src/gw2analytics_api/schema_guard.py``; the
    alembic config lives at ``apps/api/alembic.ini``. The
    path is computed at call time from ``__file__`` so the
    helper is robust to the current working directory
    (operators sometimes run ``uv run alembic`` from the repo
    root, not from ``apps/api/``).
    """
    return str(Path(__file__).parent.parent.parent / "alembic.ini")


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

    The helper does NOT catch the SQLAlchemy exception on
    step 3; a Postgres outage at startup is a different
    operational concern (the sessionmaker itself will fail
    at first use) and should NOT be masked behind a
    "schema drift" error message.
    """
    if os.environ.get("SKIP_SCHEMA_GUARD"):
        # The bypass is logged loudly at WARNING so the
        # operator's terminal (and ``/tmp/fastapi.log``)
        # shows the choice. Removing this branch requires
        # also removing the escape hatch from the
        # ``Operational runbook`` section of the docs.
        logger.warning(
            "SKIP_SCHEMA_GUARD=1; skipping schema drift check (NOT recommended in production)",
        )
        return

    cfg = AlembicConfig(_alembic_cfg_path())
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with get_sessionmaker()() as db:
        actual = db.execute(
            text("SELECT version_num FROM alembic_version"),
        ).scalar_one_or_none()
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
