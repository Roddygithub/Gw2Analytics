"""v0.10.4 plan 120: regression test for ``EOFError`` in ``run_backfill``.

A truncated gzip blob raises ``EOFError`` (NOT a subclass of ``OSError``)
from ``gzip.decompress``. The backfill's exception tuple must catch it
so the fight is counted as ``failed`` and the loop continues, instead of
crashing the entire backfill run.
"""

from __future__ import annotations

import gzip
import uuid as _uuid

from sqlalchemy import delete
from tests._fixtures import make_cbtevent, post_minimal_fight

from gw2analytics_api import storage
from gw2analytics_api.database import get_sessionmaker
from gw2analytics_api.models import OrmFightPlayerSummary
from gw2analytics_api.scripts.backfill_player_summaries import run_backfill

# Module-level ``original_get_events`` is bound at PATCH time below
# (inside the test); the storage import at module scope avoids
# a PLC0415 inline import inside the function body.


def test_backfill_handles_eoferror_from_truncated_blob() -> None:
    """A truncated gzip blob raises ``EOFError``; the backfill must count
    the fight as ``failed`` and continue, NOT crash the entire loop."""
    suffix = _uuid.uuid4().hex[:8]
    base_id_a = 100_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)
    base_id_b = base_id_a + 1
    base_skill_a = 1_000_000 + (int(suffix[:4], 16) if len(suffix) >= 4 else 0)

    events = [
        make_cbtevent(
            time_ms=1_500, src=base_id_a, dst=base_id_b, value=1_234, skill_id=base_skill_a
        ),
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

    # Delete the summary rows so the fight is discoverable by the
    # backfill's NOT EXISTS query.
    session = get_sessionmaker()()
    try:
        session.execute(
            delete(OrmFightPlayerSummary).where(
                OrmFightPlayerSummary.fight_id == fight_id,
            )
        )
        session.commit()
    finally:
        session.close()

    # Monkeypatch ``storage.get_events`` (LIVE attribute lookup) with
    # a truncated gzip blob (remove the CRC + size trailer so
    # ``gzip.decompress`` raises ``EOFError``).
    #
    # We patch ``storage.get_events`` and NOT ``backfill.get_events``
    # because Python attribute lookup on ``backfill.get_events`` is
    # the LIVE ``storage.get_events`` reference (backfill.py does
    # ``from gw2analytics_api.storage import get_events``, then
    # calls ``get_events(...)`` via the module-local binding -- which
    # is what ``backfill._backfill_one_fight`` invokes in the loop).
    truncated_blob = gzip.compress(b"hello world")[:-4]
    original_get_events = storage.get_events
    storage.get_events = lambda key: truncated_blob
    try:
        session = get_sessionmaker()()
        try:
            backfilled, _skipped, failed = run_backfill(session, fight_id=fight_id)
            # The fight should be counted as ``failed`` (not crashed).
            assert failed == 1
            assert backfilled == 0
        finally:
            session.close()
    finally:
        storage.get_events = original_get_events
