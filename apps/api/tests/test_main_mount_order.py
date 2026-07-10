"""v0.10.0 plan 032: mount-order invariant test.

FastAPI matches routes in declaration order. The cross-account
comparison route (``/api/v1/players/compare/timeline``) MUST
be registered BEFORE the players router's catch-all
(``{account_name:path}``) or the catch-all will greedily
match ``/api/v1/players/compare/timeline`` with
``account_name="compare/timeline"`` and return 404.

This test pins the include order so a future refactor that
alphabetises the ``app.include_router`` calls (a common
style preference) fails the test suite rather than
silently 404'ing every ``/players/compare/*`` call.

Why ``TestClient`` (not ``app.openapi()["paths"]`` or
``app.routes``)
====================================================

``app.routes`` stores ``include_router`` calls as
``_IncludedRouter`` objects with ``path=None`` in modern
FastAPI/Starlette; the actual ``Route`` objects are nested
inside. A simple ``r.path == ...`` check returns False for
every route. ``app.openapi()["paths"]`` produces a flat dict
but its insertion order is the order routes were FIRST
registered per-path, not the strict include order -- if the
players catch-all is registered first, the cross-account
path is still present in the dict but its position doesn't
reflect the match order.

The behavior-driven ``TestClient`` check is the only
version-robust, path-template-agnostic way to assert the
mount-order invariant: a request to the cross-account path
that returns anything OTHER than 404 proves the cross-account
route matched (not the catch-all). A 422 (missing accounts)
or 500 (DB unavailable) is acceptable -- both prove the
route was matched.
"""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from gw2analytics_api.main import app


def test_compare_route_included_before_players_catchall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-account route MUST be registered BEFORE
    the players catch-all. A misconfiguration here is a
    silent 404 on every cross-account request -- a 100%
    functionality loss for a maintainer-flagged core
    feature (the squad-comparison use case from
    ``docs/ROADMAP.md`` §1).

    v0.10.8 plan 140 Fix-D: monkeypatches the lifespan's
    schema-drift guard to a no-op so the lifespan's first
    step does not raise on test DBs whose ``alembic_version``
    row may differ from the on-disk alembic head. Strict
    function-scoped pytest monkeypatch restores the original
    ``check_schema_drift`` automatically after this test.
    """
    monkeypatch.setattr(
        "gw2analytics_api.schema_guard.check_schema_drift",
        lambda: None,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/players/compare/timeline",
            params={"accounts": ["A", "B"]},
        )
    # The players catch-all would return 404 with
    # "player not found" for ``account_name="compare/timeline"``.
    # The cross-account route returns 422 (missing accounts)
    # or 500 (DB not available) but NEVER 404 from the
    # catch-all. Asserting ``!= 404`` proves the cross-account
    # route matched first, not the catch-all.
    assert response.status_code != 404, (
        f"v0.10.0 plan 032 mount-order INVARIANT VIOLATED: "
        f"/api/v1/players/compare/timeline returned 404. "
        f"The players catch-all matched first; the cross-account "
        f"router MUST be included BEFORE the players router in "
        f"main.py (or every /players/compare/* call will 404). "
        f"See the comment block above the include_router calls "
        f"for the rationale. Response body: {response.text!r}"
    )
