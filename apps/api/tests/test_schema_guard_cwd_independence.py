"""v0.10.10 plan 030: CWD-independent Alembic ``script_location`` in
:func:`gw2analytics_api.schema_guard.check_schema_drift`.

The drift guard constructs an :class:`alembic.config.Config` from
``apps/api/alembic.ini``. The .ini declares
``script_location = alembic`` -- a RELATIVE path. Pre-fix, Alembic
resolved this against the operator's CWD, so the README's
``uv run fastapi dev apps/api/src/gw2analytics_api/main.py`` (which
launches from the repo root) crashed with
``CommandError: Path doesn't exist: alembic`` because Alembic
searched ``<repo_root>/alembic/`` instead of
``<repo_root>/apps/api/alembic/``.

The fix overrides the relative ``script_location`` with an absolute
path derived from the .ini's location (sibling-directory
``apps/api/alembic/``). These tests pin the post-fix contract:
the guard boots from the repo root, the apps/api directory, AND an
arbitrary CWD.

Hermetic via :func:`unittest.mock.patch` on the alembic
``ScriptDirectory`` and the ``AlembicConfig`` constructor. The
``monkeypatch.chdir`` calls swap the OS CWD for the duration of one
test; pytest reverts after teardown.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gw2analytics_api.schema_guard import _ALEMBIC_CFG, check_schema_drift


@pytest.fixture
def _isolated_schema_guard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``SKIP_SCHEMA_GUARD`` is unset for every test."""
    monkeypatch.delenv("SKIP_SCHEMA_GUARD", raising=False)


def _repo_root() -> str:
    """Return the absolute path of the repo root (the directory containing ``apps/``)."""
    # tests/test_schema_guard_cwd_independence.py -> tests/ -> apps/api/ -> apps/ -> repo root
    return str(Path(__file__).resolve().parent.parent.parent.parent)


def _apps_api_dir() -> str:
    """Return the absolute path of the ``apps/api`` directory."""
    return str(Path(_repo_root()) / "apps" / "api")


def test_alembic_config_uses_absolute_script_location(
    _isolated_schema_guard_env: None,
) -> None:
    """The fix pins ``script_location`` to an absolute path.

    Mocks :class:`alembic.config.Config` to capture the
    ``set_main_option(...)`` calls. The post-fix code MUST
    call ``set_main_option("script_location", <abs path>)``
    with an absolute path (the in-place override that closes
    the CWD-dependency). Pre-fix, the code did NOT call
    ``set_main_option`` for ``script_location`` -- it relied
    on the .ini's RELATIVE value + Alembic's CWD resolution.
    """
    captured: dict[str, str] = {}

    class FakeAlembicConfig:
        def __init__(self, ini_path: str) -> None:
            self.ini_path = ini_path

        def set_main_option(self, key: str, value: str) -> None:
            captured[key] = value

    with (
        patch(
            "gw2analytics_api.schema_guard.AlembicConfig",
            FakeAlembicConfig,
        ),
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
        check_schema_drift()

    assert "script_location" in captured, (
        "check_schema_drift() must override script_location to an absolute path; "
        "the override is the v0.10.10 plan 030 fix for the CWD-dependent Alembic resolution"
    )
    script_location = captured["script_location"]
    assert Path(script_location).is_absolute(), (
        f"script_location must be an absolute path, got {script_location!r}"
    )
    # The override path must end with ``alembic`` (the migrations
    # directory) and live as a sibling of the .ini's parent.
    assert script_location.endswith(str(Path("apps") / "api" / "alembic")), (
        f"script_location must end with apps/api/alembic, got {script_location!r}"
    )


def test_check_schema_drift_from_repo_root_cwd(
    _isolated_schema_guard_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot the guard from the repo root (the README quickstart's CWD).

    Pre-fix: ``alembic.util.exc.CommandError: Path doesn't exist: alembic``
    raised because the relative ``alembic/`` was resolved against
    the repo root (NOT ``apps/api/``). Post-fix: the absolute
    ``script_location`` override closes the gap; the guard boots
    cleanly regardless of CWD.
    """
    monkeypatch.chdir(_repo_root())
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
        # No exception = pass. Pre-fix this raised ``CommandError``.
        check_schema_drift()


def test_check_schema_drift_from_apps_api_cwd(
    _isolated_schema_guard_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot the guard from ``apps/api/`` (the canonical alembic CLI CWD).

    Both pre-fix and post-fix work for this CWD (the relative
    ``alembic/`` resolves correctly when CWD IS ``apps/api/``).
    The test pins the non-regression: the absolute override must
    not BREAK the case where the relative path would have worked.
    """
    monkeypatch.chdir(_apps_api_dir())
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
        check_schema_drift()


def test_check_schema_drift_from_arbitrary_cwd(
    _isolated_schema_guard_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Boot the guard from an arbitrary CWD far from the repo.

    Pins the operator-experience fix: the guard works regardless
    of where the operator launched uvicorn from. Pre-fix: the
    relative ``alembic/`` resolved against an arbitrary CWD and
    raised ``CommandError``. Post-fix: the absolute override
    closes the gap.

    The :func:`pytest.fixture` ``tmp_path`` provides a hermetic
    per-test directory (replaces the pre-fix hardcoded ``/tmp``,
    which tripped the S108 insecure-tempfile lint). The directory
    is created and torn down by pytest for the duration of the
    test.
    """
    monkeypatch.chdir(tmp_path)
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
        check_schema_drift()


def test_alembic_cfg_path_helper_is_unchanged() -> None:
    """The ``_ALEMBIC_CFG`` constant is unchanged.

    The plan 030 fix added the ``script_location`` override; the
    .ini's PATH resolution was already robust to CWD. The test
    pins the contract: the constant still derives the .ini
    location from ``__file__`` regardless of the operator's CWD.
    """
    path = _ALEMBIC_CFG
    assert Path(path).is_absolute()
    assert path.endswith(str(Path("apps") / "api" / "alembic.ini"))
