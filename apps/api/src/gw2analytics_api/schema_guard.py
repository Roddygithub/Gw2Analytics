"""Schema-drift guard for the app lifespan (v0.10.1 plan 010).

Compares the alembic head recorded in ``alembic_version`` to the
head alembic would generate from the migrations on disk. Raises
:class:`RuntimeError` on mismatch so the operator sees the drift
immediately at boot, not minutes later via log spam.

Set ``SKIP_SCHEMA_GUARD=1`` to bypass. Reserved for emergency
rollback scenarios.

Why not Option A (metadata diff)?
=================================
SQLAlchemy types like ``JSONB`` and ``LargeBinary`` have multiple
Postgres representations — a semantic drift (renamed column) and a
cosmetic drift (changed default) both surface as "drift". The
alembic version check is a 1-bit signal: "did you run the latest
migration AND restart?".
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
    """Compare alembic head to live ``alembic_version``. Raise on drift."""
    if get_settings().skip_schema_guard:
        logger.warning(
            "SKIP_SCHEMA_GUARD=1; skipping schema drift check (NOT recommended in production)",
        )
        return

    cfg = AlembicConfig(_ALEMBIC_CFG)
    config_dir = Path(_ALEMBIC_CFG).parent
    cfg.set_main_option("script_location", str(config_dir / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()

    with get_sessionmaker()() as db:
        try:
            actual = db.execute(
                text("SELECT version_num FROM alembic_version"),
            ).scalar_one_or_none()
        except ProgrammingError as exc:
            logger.info(
                "schema drift check: alembic_version table missing — "
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
