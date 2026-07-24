"""Event blob persistence and player summary materialization.

Phase 2.2: uses :class:`FightRepository` for fight lookups instead
of raw ``db.execute(select(...))`` calls.
"""

from __future__ import annotations

import gzip
import io
import logging

from minio.error import S3Error
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gw2_core import Event
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser
from gw2analytics_api.models import OrmFight, Upload
from gw2analytics_api.repositories import FightRepository
from gw2analytics_api.services.player_summaries import _persist_player_summaries
from gw2analytics_api.storage import put_events

# Module-level singleton: PythonEvtcParser is stateless and safe to reuse.
_parser = PythonEvtcParser()

logger = logging.getLogger(__name__)


def _write_summary_for_fight(
    db: Session,
    orm_fight: OrmFight,
    events: list[Event],
) -> None:
    """Write ``OrmFightPlayerSummary`` rows for a pre-fetched fight."""
    try:
        _persist_player_summaries(db, orm_fight, events)
    except SQLAlchemyError:
        logger.exception(
            "player summary materialization failed for fight %s; "
            "slow-path fallback will serve the player routes",
            orm_fight.id,
        )


def _persist_event_blob(
    db: Session,
    upload: Upload,
    evtc_bytes: bytes,
    fight_id: str,
) -> None:
    """Persist events blob and materialize player summaries.

    Uses :class:`FightRepository` for ORM entity lookups.
    Phase 4.3: streams JSONL lines through ``gzip.GzipFile``
    instead of building the full JSONL string in memory.
    """
    try:
        events = list(_parser.parse_events(evtc_bytes))
    except (EvtcParseError, S3Error, OSError, gzip.BadGzipFile):
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return

    repo = FightRepository(db)

    if not events:
        logger.debug("upload %s yielded zero events; events_blob_uri stays NULL", upload.id)
        orm_fight = repo.get_by_id_with_agents_and_skills(fight_id)
        if orm_fight is None:
            return
        _write_summary_for_fight(db, orm_fight, events)
        return

    try:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="w") as gz:
            for event in events:
                gz.write(event.model_dump_json().encode("utf-8") + b"\n")
        blob_uri = put_events(fight_id, buf.getvalue())
    except (EvtcParseError, S3Error, OSError, gzip.BadGzipFile):
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return

    orm_fight = repo.get_by_id_with_agents_and_skills(fight_id)
    if orm_fight is None:
        return
    orm_fight.events_blob_uri = blob_uri
    _write_summary_for_fight(db, orm_fight, events)
