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

import pytest
from sqlalchemy import delete

from gw2analytics_api.database import get_sessionmaker
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
    with get_sessionmaker()() as db:
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
