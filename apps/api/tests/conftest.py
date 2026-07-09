"""Shared pytest fixtures for ``apps/api/tests/``.

Auto-cleanup fixture
====================

The function-scoped :func:`_isolate_test_state` fixture wipes the
state-accumulating tables before EVERY test. This addresses the
v0.9.2 plan 009 Step 0 finding: 4 SLOW modules
(``test_uploads_e2e``, ``test_players``, ``test_health_summary``,
``test_backfill``) hung at the 30s wallclock ceiling because
``uploads`` + ``fights`` + ``fight_player_summaries`` +
``webhook_subscriptions`` + ``webhook_deliveries`` + ``webhook_dlq``
rows accumulated across runs without per-test cleanup. The
``uploads`` table alone was the bottleneck (the parser-side
write-path materialises 1 fight + 1 player_summary per upload; the
read-side ``GET /api/v1/players`` walks every summary row, and the
scheduler-side ``/api/v1/health/summary`` query joins every
``OrmFightPlayerSummary`` row to compute the drift_pct).

The cleanup is BROAD SCOPE (every test in apps/api/tests/) because
the 5 fast modules (``test_account``, ``test_healthz``,
``test_config``, ``test_ci_health_gate``, ``test_health_summary``
itself after the conftest) don't depend on accumulated state in
any of the 6 cleaned tables. The bulk-delete is a no-op for those
tests' isolated concerns. If a future test depends on
accumulated state in any of these 6 tables, scope the autouse
via ``pytest_collection_modifyitems`` to a specific test path
(plan 009 maintenance note).

DELETE order respects the FK relationships (children before
parents; ``OrmWebhookDlq`` has NO FK so it can go anywhere but
is sequenced adjacent to ``OrmWebhookDelivery`` for clarity):

    1. OrmFightPlayerSummary (FK -> OrmFight)
    2. OrmWebhookDelivery (FK -> OrmWebhookSubscription)
    3. OrmWebhookDlq (NO FK -- deliberate forensics per v0.9.0)
    4. OrmWebhookSubscription (no incoming FKs of interest)
    5. OrmFight (FK -> Upload; cascades to OrmFightAgent +
       OrmFightSkill via SQLAlchemy relationship)
    6. Upload (parent)

Test results post-conftest (per plan 009 Step 5): 22/23 webhook
tests pass; the 4 SLOW modules drop from >30s to <5s each. The
cumulative ``uv run pytest tests/`` wallclock drops from >600s
to <120s.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from arq.connections import RedisSettings
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from gw2analytics_api.database import get_sessionmaker as _get_sessionmaker_factory
from gw2analytics_api.main import app
from gw2analytics_api.models import (
    OrmFight,
    OrmFightPlayerSummary,
    OrmWebhookDelivery,
    OrmWebhookDlq,
    OrmWebhookSubscription,
    Upload,
)
from gw2analytics_api.workers import parser_settings


@pytest.fixture(autouse=True)
def _isolate_test_state() -> None:
    """Bulk-delete from state-accumulating tables before each test.

    The cleanup is hermetic to the apps/api test database only
    (``get_sessionmaker()`` is the process-wide sessionmaker
    bound to the apps/api engine). The fixture is function-scoped
    so each test sees hermetic state; the bulk-delete is a single
    transaction so the cleanup is atomic (a torn DELETE on
    ``uploads`` + ``fights`` mid-test would surface a partial
    state to the test).
    """
    with _get_sessionmaker_factory()() as db:
        # Order: children before parents. ``OrmFight`` has SQLAlchemy
        # relationship cascades to ``OrmFightAgent`` + ``OrmFightSkill``
        # so those are auto-cleaned; we delete the others explicitly
        # so the cleanup contract is self-documenting.
        db.execute(delete(OrmFightPlayerSummary))
        db.execute(delete(OrmWebhookDelivery))
        db.execute(delete(OrmWebhookDlq))
        db.execute(delete(OrmWebhookSubscription))
        db.execute(delete(OrmFight))
        db.execute(delete(Upload))
        db.commit()


@pytest.fixture(autouse=True)
def _disable_arq_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the Arq broker at a non-existent host so the lifespan's
    pool init fails fast (sets ``app.state.arq_pool = None``),
    AND opt-in to the in-request parse fallback so the route
    handler doesn't 503 the test upload.

    Two side effects:
    1. ``RedisSettings(host="127.0.0.1", port=1)`` makes the
       lifespan's ``create_pool`` call raise ``ConnectionError``
       on init; the lifespan's broad ``except Exception``
       catches it + sets the pool to ``None``. Port ``1`` is
       reserved (``tcpmux``) and refuses connections on every
       test host seen.
    2. ``ALLOW_INREQUEST_PARSE_FALLBACK=1`` opts the route
       handler's :func:`_enqueue_parse` into the in-request
       fallback path (production raises 503 without this env
       var; the test env uses the fallback to preserve the
       pre-v0.10.1 ``wait_for_upload_completion`` contract).

    Without this fixture, the test env's real Redis (if
    running) would accept the jobs but no Arq worker would
    dequeue them → ``wait_for_upload_completion`` would time
    out at 5s.
    """
    monkeypatch.setenv("ALLOW_INREQUEST_PARSE_FALLBACK", "1")
    monkeypatch.setattr(
        parser_settings.WorkerSettings,
        "redis_settings",
        RedisSettings(host="127.0.0.1", port=1),
    )


# ---------------------------------------------------------------------------
# v0.9.2 plan 006 regression test fixtures
# ---------------------------------------------------------------------------
# The ``test_background_task_session_alive_at_invocation`` regression
# test (added in plan 006 to lock the ``process_parse`` session_factory
# refactor) requests ``client`` + ``get_sessionmaker`` as pytest
# fixture parameters, NOT as module-level names. The conftest provides
# them here so the regression test can ship without a per-file
# ``client`` fixture shadowing the module-level ``client`` already
# defined in ``test_uploads_e2e.py``.
#
# Why this lives in conftest (not the test file): the regression test
# is the ONLY test in the suite that uses fixture-injected ``client``
# + ``get_sessionmaker``; a per-file fixture would add ~15 lines of
# boilerplate to ``test_uploads_e2e.py`` for a single consumer. A
# conftest fixture is the idiomatic pytest pattern for fixtures
# consumed by 1+ test files.
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """Fresh ``TestClient(app)`` per test.

    Mirrors the module-level ``client = TestClient(app)`` at the top
    of ``test_uploads_e2e.py``; the regression test prefers
    fixture-injected ``client`` for explicitness (the test signature
    advertises its dependencies).
    """
    return TestClient(app)


@pytest.fixture
def get_sessionmaker() -> Callable[[], sessionmaker[Session]]:
    """The sessionmaker factory from :mod:`gw2analytics_api.database`.

    Returns a callable that, when invoked, returns a
    ``sessionmaker[Session]`` instance. To open a fresh
    ``Session`` for query/insert, callers invoke
    ``get_sessionmaker()()`` (the standard double-call
    pattern used everywhere else in the test suite -- see
    :func:`test_uploads_e2e_happy_path` for the canonical
    example).

    The regression test's signature is
    ``def test_background_task_session_alive_at_invocation(
    client: TestClient, get_sessionmaker: Any)``. The fixture
    shadows the imported symbol so the test does not need a
    top-level ``from gw2analytics_api.database import
    get_sessionmaker`` -- the fixture IS the import.
    """
    return _get_sessionmaker_factory
