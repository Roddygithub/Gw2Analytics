"""v0.10.26-pre followup-8 regression: lock the URL-driver rewrite contract.

The :func:`gw2analytics_api.database._normalise_database_url`
helper auto-cor rewrites unbound / legacy ``DATABASE_URL``
shapes to ``postgresql+psycopg://`` so the lifespan's first
:func:`schema_guard.check_schema_drift` call resolves to the
workspace's installed ``psycopg`` v3 driver instead of the
uninstalled legacy ``psycopg2``.

Without this test, a future PR that simplifies or removes the
rewrite would crash the lifespan with
``ModuleNotFoundError: No module named 'psycopg2'`` because
SQLAlchemy defaults to the legacy driver when the URL has no
``+<driver>`` hint.
"""

from __future__ import annotations

import pytest

from gw2analytics_api.database import _normalise_database_url


@pytest.mark.parametrize(
    ("input_url", "expected_url"),
    [
        # Unbound form (the bug this fix closes) -> +psycopg
        (
            "postgresql://gw2analytics:gw2analytics@localhost:5432/gw2analytics",
            "postgresql+psycopg://gw2analytics:gw2analytics@localhost:5432/gw2analytics",
        ),
        # ``postgres://`` shorthand (Heroku, some asyncpg recipes) -> +psycopg
        (
            "postgres://gw2analytics:gw2analytics@localhost:5432/gw2analytics",
            "postgresql+psycopg://gw2analytics:gw2analytics@localhost:5432/gw2analytics",
        ),
        # Explicit-legacy (workspace will crash on it) -> +psycopg
        (
            "postgresql+psycopg2://user:pw@host:5432/db",
            "postgresql+psycopg://user:pw@host:5432/db",
        ),
        # Idempotent pass-through (already correct)
        (
            "postgresql+psycopg://user:pw@host:5432/db",
            "postgresql+psycopg://user:pw@host:5432/db",
        ),
        # Other dialects are LEFT ALONE (worker might need them)
        (
            "postgresql+asyncpg://user:pw@host:5432/db",
            "postgresql+asyncpg://user:pw@host:5432/db",
        ),
        (
            "postgresql+pg8000://user:pw@host:5432/db",
            "postgresql+pg8000://user:pw@host:5432/db",
        ),
        # Query strings pass through unchanged
        (
            "postgresql://user:pw@host:5432/db?sslmode=require",
            "postgresql+psycopg://user:pw@host:5432/db?sslmode=require",
        ),
    ],
)
def test_normalise_database_url(input_url: str, expected_url: str) -> None:
    """Every URL shape the helper pledges to handle is preserved + rewritten."""
    assert _normalise_database_url(input_url) == expected_url


def test_normalise_database_url_preserves_auth_host_port_db() -> None:
    """The schema prefix swap must NOT corrupt auth + host + port + db name."""
    plain = "postgresql://alice:secret@db.example.com:5433/myapp"
    out = _normalise_database_url(plain)
    assert out == "postgresql+psycopg://alice:secret@db.example.com:5433/myapp"
    assert "alice:secret" in out
    assert "db.example.com:5433/myapp" in out
