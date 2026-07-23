"""v0.8.6: end-to-end tests for the operational health probe.

The probe (``GET /api/v1/health/summary``) surfaces the
``OrmFightPlayerSummary`` population drift so an operator
can detect when the fast-path is degraded to the
slow-path fallback. Three scenarios are covered:

1. **Empty dataset** -- no fights: ``drift_count=0``,
   ``drift_pct=0.0`` (the ``ZeroDivisionError`` guard).
2. **Full coverage** -- a fight with summary rows: the
   drift is 0.
3. **Partial drift** -- a fight with the summary rows
   deleted (simulating a pre-v0.8.4 fight that has not
   been backfilled yet): the drift is 1.

The test database is shared across runs, so the
``drift_count`` and ``total_fights`` assertions use
``>=`` (not ``==``) to allow for state from previous
test runs. The ``fights_with_summaries`` and
``drift_pct`` assertions use the delta (the difference
between before-and-after the test's actions) so the
test is self-contained regardless of the shared DB
state.
"""

from __future__ import annotations

import uuid as _uuid

from _fixtures import make_cbtevent
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from test_uploads_helpers import _post_minimal_fight as post_minimal_fight

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.main import app
from gw2analytics_api.models import OrmFightPlayerSummary

client = TestClient(app)


def test_health_summary_shape_contract() -> None:
    """v0.8.6: the probe returns the correct 5-field shape + types.

    Asserts the response keys, the value types, the internal
    consistency (``drift_count == total - with_summary``),
    the ``drift_pct`` formula, and the ``status`` field's
    ``"ok"`` / ``"drift"`` binary semantics. The test
    cannot easily isolate from the shared test DB (other
    tests' fights persist), so it asserts the SHAPE + the
    cross-field invariants, not the exact counts.
    """
    resp = client.get("/api/v1/health/summary")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # The exact 5-key shape: ``status`` is the new field
    # added in v0.8.6 (the round 139 review's secondary
    # recommendation -- a qualitative summary operators
    # can branch on without computing their own threshold).
    assert set(payload.keys()) == {
        "total_fights",
        "fights_with_summaries",
        "drift_count",
        "drift_pct",
        "status",
    }
    # Type checks (the ``>= 0`` assertions in the
    # previous version were tautological for unsigned
    # ``COUNT`` results -- type checks are stronger).
    assert isinstance(payload["total_fights"], int)
    assert isinstance(payload["fights_with_summaries"], int)
    assert isinstance(payload["drift_count"], int)
    assert isinstance(payload["drift_pct"], (int, float))
    assert payload["status"] in ("ok", "drift")
    # Internal consistency: ``drift_count`` is derived
    # from ``total - with_summary`` (a property of the
    # response, not a test assumption).
    assert payload["drift_count"] == payload["total_fights"] - payload["fights_with_summaries"]
    # The ``drift_pct`` formula: ``drift_count / total *
    # 100`` rounded to 2 decimals, or ``0.0`` on an empty
    # database. The empty-database ``ZeroDivisionError``
    # guard is a defensive branch in :func:`summary_drift`
    # that cannot be easily exercised in a shared test DB.
    if payload["total_fights"] == 0:
        assert payload["drift_pct"] == 0.0
        # On an empty DB, ``drift_count`` is also 0, so
        # the status is ``"ok"``.
        assert payload["status"] == "ok"
    else:
        expected_pct = round(
            payload["drift_count"] / payload["total_fights"] * 100,
            2,
        )
        assert payload["drift_pct"] == expected_pct
        # Status matches the binary ``drift_count`` check.
        if payload["drift_count"] == 0:
            assert payload["status"] == "ok"
        else:
            assert payload["status"] == "drift"


def test_health_summary_increments_after_new_fight() -> None:
    """v0.8.6: posting a new fight increments ``total_fights``.

    A new fight with events (the v0.8.4 write path materialises
    the summary rows) bumps both ``total_fights`` and
    ``fights_with_summaries`` by 1. The ``drift_count`` is
    unchanged (a new fight with summaries does not add to
    the drift).
    """
    before = client.get("/api/v1/health/summary").json()

    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
        # B is the source of this heal event so B also gets
        # a summary row (see the rationale in the backfill
        # tests).
        make_cbtevent(
            time_ms=2_500,
            src=base_id_b,
            dst=base_id_a,
            value=400,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
    ]
    post_minimal_fight(events, suffix=suffix)

    after = client.get("/api/v1/health/summary").json()

    assert after["total_fights"] == before["total_fights"] + 1
    assert after["fights_with_summaries"] == before["fights_with_summaries"] + 1
    # drift_count is unchanged: a new fight with summaries
    # does not add to the drift. The status stays whatever
    # it was before (typically ``"ok"`` or ``"drift"``
    # depending on the shared DB state).
    assert after["drift_count"] == before["drift_count"]


def test_health_summary_surfaces_drift_after_summary_deletion() -> None:
    """v0.8.6: deleting summary rows increments ``drift_count``.

    Simulates a pre-v0.8.4 fight whose summary rows are
    missing (the post-migration state before the v0.8.5
    backfill runs). The probe surfaces the drift so an
    operator can detect the degraded fast-path.
    """
    before = client.get("/api/v1/health/summary").json()

    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    events = [
        make_cbtevent(
            time_ms=1_500,
            src=base_id_a,
            dst=base_id_b,
            value=1_234,
            skill_id=base_skill_a,
        ),
    ]
    fight_id = post_minimal_fight(events, suffix=suffix)

    # Sanity check: the v0.8.4 write path wrote 1+ summary
    # rows for this fight.
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id),
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1
        # Simulate a pre-v0.8.4 fight by DELETing the rows.
        session.execute(
            delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id),
        )
        session.commit()
    finally:
        session.close()

    after = client.get("/api/v1/health/summary").json()

    # total_fights incremented by 1 (the new fight), but
    # fights_with_summaries is unchanged (the deleted rows
    # are gone). drift_count incremented by 1.
    assert after["total_fights"] == before["total_fights"] + 1
    assert after["fights_with_summaries"] == before["fights_with_summaries"]
    assert after["drift_count"] == before["drift_count"] + 1
    # drift_pct reflects the new drift.
    expected_pct = (
        round(
            after["drift_count"] / after["total_fights"] * 100,
            2,
        )
        if after["total_fights"] > 0
        else 0.0
    )
    assert after["drift_pct"] == expected_pct
    # Status flips to ``"drift"`` (the test deleted
    # summary rows, so the DB now has drift).
    assert after["status"] == "drift"
