"""v0.10.10 plan 031: ``schema_guard.check_schema_drift`` gracefully
handles a fresh DB (the ``alembic_version`` table is missing).

The drift guard queries ``SELECT version_num FROM alembic_version``.
On a fresh DB (e.g. docker-compose stack boots the API container
before running migrations), the table does NOT exist. Pre-fix, the
raw ``psycopg.errors.UndefinedTable: relation "alembic_version"
does not exist`` surfaced as a confusing traceback that operators
misread as a Postgres outage. Post-fix, the catch routes to a
:class:`RuntimeError` with the same actionable "did you run
migrations?" diagnosis as the ``actual is None`` case.

Hermetic via :func:`unittest.mock.patch` on the ``db.execute``
target. The catch is broad (``sqlalchemy.exc.ProgrammingError``)
because psycopg's ``UndefinedTable`` + SQLite's
``OperationalError`` + asyncpg's ``UndefinedTableError`` all
surface as that parent class. The tests pin both the catch's
behaviour AND the rationale (a documentation test asserts the
source uses ``ProgrammingError``, not a DBAPI-specific class).
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest
from sqlalchemy.exc import ProgrammingError

from gw2analytics_api.schema_guard import check_schema_drift


@pytest.fixture
def _isolated_schema_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``SKIP_SCHEMA_GUARD`` is unset for every test."""
    monkeypatch.delenv("SKIP_SCHEMA_GUARD", raising=False)


def test_undefined_table_raises_runtime_error_with_actionable_hint(
    _isolated_schema_guard_env: None,
) -> None:
    """``ProgrammingError`` (DBAPI "relation does not exist") routes to ``RuntimeError``.

    Pre-fix: the raw ``psycopg.errors.UndefinedTable`` propagated.
    Post-fix: the catch routes to a friendly ``RuntimeError`` with
    the operator-facing actionable message.

    Patches the ``db.execute`` target to raise
    :class:`sqlalchemy.exc.ProgrammingError` with the
    psycopg-typical "relation ... does not exist" message. Asserts
    the post-fix code catches the parent class and re-raises as
    ``RuntimeError`` with the diagnostic substrings.
    """
    with (
        patch(
            "gw2analytics_api.schema_guard.ScriptDirectory.from_config",
        ) as mock_script_dir,
        patch(
            "gw2analytics_api.schema_guard.get_sessionmaker",
        ) as mock_sf,
    ):
        mock_get_current_head = mock_script_dir.return_value.get_current_head
        mock_get_current_head.return_value = "0009_webhook_secret_at_rest"
        mock_session = mock_sf.return_value.return_value.__enter__.return_value
        mock_session.execute.side_effect = ProgrammingError(
            'relation "alembic_version" does not exist',
            params=None,
            orig=Exception('relation "alembic_version" does not exist'),
        )
        with pytest.raises(RuntimeError) as exc_info:
            check_schema_drift()
    msg = str(exc_info.value)
    # All 3 operator-facing substrings must be in the error message
    # so the runbook greps continue to match and the hint is
    # actionable.
    assert "alembic_version table missing" in msg
    assert "alembic upgrade head" in msg
    assert "SKIP_SCHEMA_GUARD" in msg


def test_programming_error_with_other_relation_message_still_routes_correctly(
    _isolated_schema_guard_env: None,
) -> None:
    """A ``ProgrammingError`` with a different relation name still routes to ``RuntimeError``.

    The SQL query targets ``alembic_version`` LITERALLY; any
    ``ProgrammingError`` on that query IS the missing-table case.
    This test pins that the broad catch fires regardless of the
    specific relation-name in the message (the discrimination is
    by exception TYPE, not by message content).
    """
    with (
        patch(
            "gw2analytics_api.schema_guard.ScriptDirectory.from_config",
        ) as mock_script_dir,
        patch(
            "gw2analytics_api.schema_guard.get_sessionmaker",
        ) as mock_sf,
    ):
        mock_get_current_head = mock_script_dir.return_value.get_current_head
        mock_get_current_head.return_value = "0009_webhook_secret_at_rest"
        mock_session = mock_sf.return_value.return_value.__enter__.return_value
        mock_session.execute.side_effect = ProgrammingError(
            'relation "some_other_table" does not exist',
            params=None,
            orig=Exception("..."),
        )
        with pytest.raises(RuntimeError) as exc_info:
            check_schema_drift()
    assert "alembic_version table missing" in str(exc_info.value)


def test_routing_rationale_covers_all_dbadp_drivers() -> None:
    """Documentation-style: the catch uses SQLAlchemy's ``ProgrammingError`` (not DBAPI-specific).

    Pins the multi-driver operand rationale. Any DBAPI's
    "relation does not exist" surfaces as
    :class:`sqlalchemy.exc.ProgrammingError` (psycopg's
    ``UndefinedTable``, SQLite's ``OperationalError``,
    asyncpg's ``UndefinedTableError``). A future executor who
    swaps the catch for a DBAPI-specific class (e.g.
    ``psycopg.errors.UndefinedTable``) would break the
    multi-driver contract; this test fails such a regression.
    """
    src = inspect.getsource(check_schema_drift)
    assert "ProgrammingError" in src
    # A negative check: the catch must NOT use a DBAPI-specific
    # class (which would couple the helper to psycopg alone).
    assert "psycopg.errors.UndefinedTable" not in src
    assert "asyncpg.UndefinedTableError" not in src
    assert "sqlite3.OperationalError" not in src
