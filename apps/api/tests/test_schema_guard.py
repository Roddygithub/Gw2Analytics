"""v0.10.1 plan 010: hermetic tests for the schema-drift guard.

The drift guard is a 5-line SQL query (alembic head vs
``alembic_version.version_num``) but the failure mode
("operator forgot to restart Uvicorn after a migration")
is high-severity operational debt (it was the source of
the 253K-char ``/tmp/fastapi.log`` spam found by
real-payload testing on 2026-07-09). These tests pin:

1. **No-drift case**: a clean boot logs INFO + returns.
2. **Drift case**: a mismatched alembic version raises
   :class:`RuntimeError` with an actionable error message
   that names both heads (so the operator can grep
   ``apps/api/alembic/versions/`` for either one).
3. **Escape hatch**: ``SKIP_SCHEMA_GUARD=1`` bypasses
   the check even on drift (the production escape hatch).
4. **Error message format**: the literal ``"Schema drift
   detected"`` prefix is stable so external log greps
   (``grep -E 'Schema drift detected' /tmp/fastapi.log``)
   continue to match.

Hermetic via :func:`unittest.mock.patch` on the alembic
``ScriptDirectory`` and the ``alembic_version`` table query.
No live alembic run, no live Postgres.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gw2analytics_api.schema_guard import check_schema_drift


@pytest.fixture
def _isolated_schema_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``SKIP_SCHEMA_GUARD`` is unset for every test.

    The env var persists across tests by default (it is a
    process-wide OS env). Without this fixture, a previous
    test that sets it could mask a later test's drift
    assertion. The fixture is autouse-equivalent for this
    module; the ``monkeypatch`` teardown runs after each
    test.
    """
    monkeypatch.delenv("SKIP_SCHEMA_GUARD", raising=False)


def test_no_drift_passes(_isolated_schema_guard_env: None) -> None:
    """Drift guard returns silently when alembic head matches DB row."""
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
        mock_scalar = mock_session.execute.return_value.scalar_one_or_none
        mock_scalar.return_value = "0009_webhook_secret_at_rest"
        # No exception = pass. The logger is silent at INFO; no
        # need to assert on it.
        check_schema_drift()


def test_drift_raises_runtime_error(_isolated_schema_guard_env: None) -> None:
    """Drift guard raises ``RuntimeError`` when head != DB row.

    Pins the literal error message format so external log
    greps (``grep 'Schema drift detected' /tmp/fastapi.log``)
    continue to match. The exception's ``str()`` includes
    both heads so the operator can grep
    ``apps/api/alembic/versions/`` for the missing
    migration.
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
        mock_get_current_head.return_value = "0010_new_thing"
        mock_session = mock_sf.return_value.return_value.__enter__.return_value
        mock_scalar = mock_session.execute.return_value.scalar_one_or_none
        mock_scalar.return_value = "0009_webhook_secret_at_rest"
        with pytest.raises(RuntimeError) as exc_info:
            check_schema_drift()
    msg = str(exc_info.value)
    # Both heads must appear in the error message
    # (so the operator can identify the missing migration).
    assert "0009_webhook_secret_at_rest" in msg
    assert "0010_new_thing" in msg
    assert "Schema drift detected" in msg
    # The escape-hatch hint must be in the message so
    # operators in a panic find it via ``grep``.
    assert "SKIP_SCHEMA_GUARD" in msg


def test_skip_schema_guard_env_var_bypasses_check(
    _isolated_schema_guard_env: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``SKIP_SCHEMA_GUARD=1`` bypasses the check even on drift.

    The escape hatch is the production backstop for
    rollback-in-flight scenarios. The check is skipped
    silently (no error) but the bypass MUST be visible in
    the log -- the WARNING literal is grep-stable for
    operators (``grep 'SKIP_SCHEMA_GUARD=1' /tmp/fastapi.log``
    should match every bypass).
    """
    monkeypatch.setenv("SKIP_SCHEMA_GUARD", "1")
    with (
        patch(
            "gw2analytics_api.schema_guard.ScriptDirectory.from_config",
        ) as mock_script_dir,
        patch(
            "gw2analytics_api.schema_guard.get_sessionmaker",
        ) as mock_sf,
    ):
        # Intentionally mismatch: bypass should swallow this.
        mock_get_current_head = mock_script_dir.return_value.get_current_head
        mock_get_current_head.return_value = "0010_new_thing"
        mock_session = mock_sf.return_value.return_value.__enter__.return_value
        mock_scalar = mock_session.execute.return_value.scalar_one_or_none
        mock_scalar.return_value = "0009_webhook_secret_at_rest"
        with caplog.at_level("WARNING", logger="gw2analytics_api.schema_guard"):
            # No exception = pass.
            check_schema_drift()
    # The WARNING log line is the operator's grep anchor;
    # a future refactor that rewrites the message would
    # silently break the runbook.
    assert any("SKIP_SCHEMA_GUARD=1" in rec.message for rec in caplog.records)


def test_drift_when_db_alembic_version_row_missing(
    _isolated_schema_guard_env: None,
) -> None:
    """Drift guard raises when the ``alembic_version`` table is empty.

    Catches the "fresh DB without any migrations" case: the
    table exists (alembic creates it on first run) but the
    row is NULL. The current code path treats ``None`` as
    "drift" and raises; this test pins that contract.
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
        mock_scalar = mock_session.execute.return_value.scalar_one_or_none
        mock_scalar.return_value = None
        with pytest.raises(RuntimeError) as exc_info:
            check_schema_drift()
    assert "Schema drift detected" in str(exc_info.value)
    assert "None" in str(exc_info.value)
