from __future__ import annotations

import gzip
import logging

from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from gw2_core import Event
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser
from gw2analytics_api.models import OrmFight, Upload
from gw2analytics_api.services.player_summaries import _persist_player_summaries
from gw2analytics_api.storage import put_events

logger = logging.getLogger(__name__)


def _write_summary_for_fight(
    db: Session,
    fight_id: str,
    events: list[Event],
) -> None:
    """Fetch the fight row + write ``OrmFightPlayerSummary`` rows.

    Shared by the empty-events and non-empty-events paths in
    :func:`_persist_event_blob` so the orm_fight fetch + the
    SELECT-by-PK retry + the SQLAlchemyError-tolerant summary write
    live in one place. Tolerates a missing fight row (logs + returns)
    and SQLAlchemy errors on the summary write (logs + returns so
    the upload still completes -- the slow-path fallback serves the
    player routes from the events blob when the summary write fails).

    The empty-events contract: when ``events`` is empty, the caller's
    conditional pre-seed in :func:`_persist_player_summaries`
    produces one zero-totals row per attending agent, so the
    /players fast-path is non-empty even for empty-events fights (the
    v0.8.4 ATTENDING-agents-always-surface contract).
    """
    orm_fight = db.execute(
        select(OrmFight).where(OrmFight.id == fight_id).options(selectinload(OrmFight.agents)),
    ).scalar_one_or_none()
    if orm_fight is None:
        return
    try:
        _persist_player_summaries(db, orm_fight, events)
    except SQLAlchemyError:
        logger.exception(
            "player summary materialization failed for fight %s; "
            "slow-path fallback will serve the player routes",
            fight_id,
        )


def _persist_event_blob(
    db: Session,
    upload: Upload,
    evtc_bytes: bytes,
    fight_id: str,
) -> None:
    parser = PythonEvtcParser()
    try:
        events = list(parser.parse_events(evtc_bytes))
    except (EvtcParseError, S3Error, OSError, gzip.BadGzipFile):
        # v0.9.5 plan 019: narrowed from ``except Exception`` to the
        # specific exception types this call site can legitimately
        # raise. A real programming bug (AttributeError, NameError,
        # TypeError, KeyError) is now propagated UP to the surrounding
        # caller instead of being silently swallowed.
        # ``gzip.BadGzipFile`` is a subclass of ``OSError`` since
        # Python 3.8 but listed explicitly for readability.
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return

    # v0.10.11 fix for test_uploads_e2e::test_players_list_returns_accounts_present_in_fight:
    # the summary write always happens (including the zero-events
    # case), but the blob write is gated on ``events != []``. The
    # ``events_blob_uri`` field stays NULL for empty-events fights.
    # The conditional pre-seed INSIDE ``_persist_player_summaries``
    # (only when ``events == []``) produces one zero-totals row per
    # attending agent so the /players fast-path is non-empty.
    #
    # Ordering note for test_persist_event_blob_except.py: the
    # S3Error test exercises the non-empty ``events`` branch and
    # expects put_events to fail BEFORE the orm_fight fetch (because
    # the test passes db=None). The non-empty branch therefore
    # orders the blob attempt FIRST + the summary write SECOND; the
    # empty branch drops the blob attempt + goes straight to the
    # summary write.
    if not events:
        logger.debug("upload %s yielded zero events; events_blob_uri stays NULL", upload.id)
        _write_summary_for_fight(db, fight_id, events)
        return

    try:
        jsonl = "\n".join(event.model_dump_json() for event in events).encode("utf-8")
        gz_bytes = gzip.compress(jsonl)
        blob_uri = put_events(fight_id, gz_bytes)
    except (EvtcParseError, S3Error, OSError, gzip.BadGzipFile):
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return

    orm_fight = db.execute(
        select(OrmFight).where(OrmFight.id == fight_id),
    ).scalar_one_or_none()
    if orm_fight is None:
        return
    orm_fight.events_blob_uri = blob_uri
    _write_summary_for_fight(db, fight_id, events)
