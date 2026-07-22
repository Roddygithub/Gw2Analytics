"""v0.10.2 hotfix followup #7: ``backfill._backfill_pre_phase7`` sanitizes overlong agent names.

Background
==========

The v0.10.2 hotfix followup #5 extended :func:`_sanitize_name` in
``services.py`` to truncate to ``MAX_NAME_LEN = 128`` (the
``String(128) NOT NULL`` column constraint) and applied it at
every ORM write boundary in ``services.py``. Followup #7 mirrors
the fix in ``backfill._backfill_pre_phase7`` for defensive depth:
even though the ``OrmFightAgent`` row is already NUL-stripped +
128-char-truncated by the ``_save_fight`` write path (so the
backfill reads from a sanitized source today), the backfill's
own ORM write boundary should also call ``_sanitize_name` to
catch any future regression that bypasses the write path's
sanitization (e.g. an operator manually UPDATEing the agent row
via raw SQL with a ``::text`` cast, then running the backfill).

The arcdps combo-string layout hard-bounds the agent ``name``
to 68 bytes, so the parser can never yield a > 128 char agent
name in practice. The defensive fix is future-proofing, not a
fix for a real bug. This test pins the defensive contract by
mutating the agent's in-memory ``name`` to 200 chars (bypassing
the ``VARCHAR(128)`` check by NOT flushing to the DB), then
calling :func:`_backfill_pre_phase7` directly and verifying the
resulting ``OrmFightPlayerSummary.name`` is <= 128 chars.

What this test pins
===================

A pre-Phase-7 fight (events_blob_uri=NULL) with an agent whose
in-memory ``name`` is 200 chars gets the agent's name
truncated to 128 chars in the ``OrmFightPlayerSummary`` row
written by :func:`_backfill_pre_phase7`.

- The test calls ``_backfill_pre_phase7`` directly (NOT
  ``run_backfill``) so the in-memory mutation is never flushed
  to the DB (a 200-char ``VARCHAR(128)`` value would fail the
  INSERT).
- The new summary objects are captured via
  ``session.new`` (SQLAlchemy's pending-objects list) and
  asserted to have ``len(name) <= 128``.
- The session is rolled back at the end so the mutation +
  the pending summary rows are discarded (the test is
  hermetic; no state leaks to subsequent tests).
"""

from __future__ import annotations

import uuid as _uuid

from _fixtures import make_cbtevent, post_minimal_fight
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerSummary,
)
from gw2analytics_api.scripts.backfill_player_summaries import _backfill_pre_phase7
from gw2analytics_api.services import MAX_NAME_LEN


def test_backfill_pre_phase7_truncates_overlong_agent_name() -> None:
    """v0.10.2 hotfix followup #7: ``_backfill_pre_phase7`` truncates > 128 char agent names to 128.

    Pre-v0.10.2 hotfix followup #7: the backfill wrote
    ``name=agent.name or ""`` directly. If the agent's in-memory
    ``name`` was > 128 chars (a scenario the current code
    cannot produce because the write path sanitizes, but a
    future regression or operator SQL could), the
    ``OrmFightPlayerSummary`` INSERT would fail with
    ``value too long for type character varying(128)`` and
    roll back the whole ``_backfill_pre_phase7`` transaction
    (the pre-Phase-7 branch is one of the per-fight
    transactions the outer ``run_backfill`` commits, so a
    failure would lose the 0-total summary rows for the
    pre-Phase-7 fight).

    Post-hotfix: the backfill routes the agent's ``name``
    through :func:`_sanitize_name` (which truncates to
    ``MAX_NAME_LEN = 128`` AFTER the NUL strip), so the
    summary row's ``name`` is always <= 128 chars regardless
    of the agent's in-memory state.
    """
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
        # B is the source of this heal so B also gets a summary
        # row in the pre-Phase-7 branch (one row per player
        # agent, not one row per account with events).
        make_cbtevent(
            time_ms=2_500,
            src=base_id_b,
            dst=base_id_a,
            value=400,
            skill_id=base_skill_a,
            is_nondamage=1,
        ),
    ]
    fight_id = post_minimal_fight(events, suffix=suffix)

    session = get_sessionmaker()()
    try:
        # Simulate the pre-Phase-7 wire-up: clear the
        # events_blob_uri + delete any existing summary rows
        # (the post-Phase-7 write path may have written some
        # already via ``_persist_player_summaries``). The
        # pre-Phase-7 branch is the one we're testing.
        session.execute(
            update(OrmFight).where(OrmFight.id == fight_id).values(events_blob_uri=None),
        )
        session.execute(
            delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id),
        )
        session.commit()

        # Re-query the fight + agents (loads into the session's
        # identity map so the in-memory mutation is visible to
        # the backfill's helper).
        fight = session.execute(
            select(OrmFight).where(OrmFight.id == fight_id).options(selectinload(OrmFight.agents)),
        ).scalar_one()
        assert fight.events_blob_uri is None
        player_agents: list[OrmFightAgent] = [
            a for a in fight.agents if a.is_player and a.account_name
        ]
        assert len(player_agents) == 2

        # Mutate the in-memory ``name`` of one agent to 200
        # chars. We do NOT flush the mutation (the DB would
        # reject the 200-char ``VARCHAR(128)`` value). The
        # backfill's helper reads from the in-memory object
        # (via the identity map), so the mutation is visible
        # to the helper.
        original_name = player_agents[0].name
        overlong_name = "X" * 200
        player_agents[0].name = overlong_name
        # Defensive sanity check: the in-memory value is
        # indeed 200 chars (the helper would see this).
        assert len(player_agents[0].name) == 200

        # Call the pre-Phase-7 helper directly. This is a
        # private helper (the public surface is
        # ``run_backfill``), but the test imports it
        # directly so the in-memory mutation is never
        # flushed to the DB (the outer ``run_backfill`` calls
        # ``db.commit()`` per fight, which would try to
        # flush the 200-char mutation and fail).
        _backfill_pre_phase7(session, fight, player_agents)

        # The new summary rows are in ``session.new``
        # (SQLAlchemy's pending-objects list) -- they have
        # NOT been flushed yet (no ``commit()`` was called).
        # Verify the names are <= 128 chars.
        new_summaries = [obj for obj in session.new if isinstance(obj, OrmFightPlayerSummary)]
        assert len(new_summaries) == 2
        for summary in new_summaries:
            assert len(summary.name) <= MAX_NAME_LEN, (
                f"summary.name length {len(summary.name)} > {MAX_NAME_LEN}; "
                f"the backfill's _sanitize_name truncation did not apply"
            )
            # The NUL-strip happens first; the name should
            # contain no NUL bytes.
            assert "\x00" not in summary.name
        # The summary for the mutated agent should be the
        # truncated 128-char version (the first 128 chars of
        # "X" * 200 are all "X").
        mutated_summary = next(
            s for s in new_summaries if s.account_name == player_agents[0].account_name
        )
        assert mutated_summary.name == "X" * MAX_NAME_LEN, (
            f"expected the first {MAX_NAME_LEN} chars of the overlong "
            f"name to be preserved, got {mutated_summary.name!r}"
        )

        # Rollback to discard the in-memory mutation + the
        # pending summary rows. This keeps the test
        # hermetic -- no state leaks to subsequent tests.
        session.rollback()

        # Defensive: restore the agent's name (in case the
        # rollback didn't revert the in-memory mutation --
        # the rollback SHOULD revert it, but this is a
        # belt-and-suspenders check).
        if player_agents[0].name == overlong_name:
            player_agents[0].name = original_name
            session.rollback()
    finally:
        session.close()
