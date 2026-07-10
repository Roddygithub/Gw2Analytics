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

Runtime prerequisites (v0.10.5 audit followup)
=============================================

This conftest mocks MinIO + Postgres at the per-test fixture layer
(see :func:`_disable_arq_for_tests` + the placeholder env vars
below), but the *runtime* needs a real Postgres + MinIO container
running on the test host BEFORE ``pytest`` is invoked:

  * Postgres on ``localhost:5433`` (the ``5433:5432`` mapping in
    ``docker-compose.yml``) with the seed ``gw2analytics:gw2analytics``
    creds + the ``gw2analytics`` database. The default URL below
    matches; if your host uses different creds, set ``DATABASE_URL``
    in the outer shell and the ``setdefault`` below will NOT clobber
    it. The CI workflow brings this up via ``docker compose up -d
    postgres`` (see ``.github/workflows/ci.yml``).
  * MinIO on ``localhost:9000`` with the ``test-bucket`` bucket +
    the [DEV-ONLY PLACEHOLDER] creds ``test-access-key`` /
    ``test-secret-key`` (placeholder block below). The placeholder
    URL/creds match; outer-shell overrides win via ``setdefault``.
    Do NOT copy the placeholder creds into a production ``.env`` --
    they're committed-to-git hardcoded for unit-test repeatability
    only.

A fresh host WITHOUT the containers will see ``OperationalError``
or ``S3Error`` on the first fixture call -- this is by design
(fixture mocks layer on top of real services, NOT in place of them).
"""

from __future__ import annotations

# v0.10.5 audit followup #1: environment bootstrap BEFORE regular imports.
# The ``from gw2analytics_api.main import app`` import below triggers
# a module-level ``Settings()`` Pydantic validation; without these
# placeholders the import raises ``ValidationError`` which pytest
# misleadingly wraps as ``ModuleNotFoundError``. We use ``setdefault``
# (NOT ``=``) so an outer CI / dev shell with the real env vars
# already set is not clobbered -- only dev laptops that lack the var
# receive the placeholder.
#
# The placeholder values are dev-only; per-test fixtures mock MinIO
# and Postgres so the real services never see these strings.
# Production reads from a managed ``.env`` / secret manager.
# ruff: noqa: E402 -- the env-bootstrap above MUST run before any
# import below it; do NOT add new imports at the very top of this
# file (the ``Settings()`` Pydantic instantiation will fail with
# ValidationError otherwise). A single file-level mark is more
# robust than N per-line marks (a stray new import won't silently
# regress E402) AND more grep-discoverable for test-infra audits.
import base64
import os
import secrets

# Per-INVOCATION random 44-char Fernet placeholder; eliminates the
# copy-paste footgun of a deterministic literal. Per-test fixtures
# mock MinIO+Postgres so cross-invocation key rotation is not a
# test-stability concern (no cross-invocation ciphertext assertions).
# Length is 44 by CONSTRUCTION (32 bytes base64-urlsafe-encoded).
_fernet_placeholder = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("S3_ACCESS_KEY", "test-access-key")
os.environ.setdefault("S3_SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://gw2analytics:gw2analytics@localhost:5433/gw2analytics",
)
os.environ.setdefault("SECRETS_KEK", _fernet_placeholder)
os.environ.setdefault("ALLOW_INREQUEST_PARSE_FALLBACK", "1")

from collections.abc import Callable

import pytest
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
    """Disable the Arq pool init at lifespan startup so the route
    handler exercises the in-request fallback path (gated on
    ``ALLOW_INREQUEST_PARSE_FALLBACK=1``).

    Two side effects:

    1. ``arq.create_pool`` is monkey-patched to raise
       :class:`ConnectionError` so the lifespan's
       ``await create_pool(...)`` fails fast and the broad
       ``except Exception`` in :mod:`gw2analytics_api.main`
       sets ``app.state.arq_pool = None``. The patch targets
       the module attribute (``arq.create_pool``) so it
       applies to the lazy ``from arq import create_pool``
       import inside the lifespan. This is more robust than
       the previous ``RedisSettings(host=..., port=1)`` trick
       (port 1 = ``tcpmux``) which depended on the test host
       refusing connections on the reserved port; containerised
       CI hosts sometimes expose the port via permissive
       firewall rules, which would let the real pool init
       succeed and silently break the test contract.
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

    async def _fake_create_pool(*_args: object, **_kwargs: object) -> None:
        msg = "arq disabled in test fixture (_disable_arq_for_tests)"
        raise ConnectionError(msg)

    monkeypatch.setenv("ALLOW_INREQUEST_PARSE_FALLBACK", "1")
    monkeypatch.setattr("arq.create_pool", _fake_create_pool)


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
