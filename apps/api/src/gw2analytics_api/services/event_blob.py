from __future__ import annotations

import gzip
import logging

from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from gw2_evtc_parser import EvtcParseError, PythonEvtcParser
from gw2analytics_api.models import OrmFight, Upload
from gw2analytics_api.services.player_summaries import _persist_player_summaries
from gw2analytics_api.storage import put_events

logger = logging.getLogger(__name__)


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
    # the summary write now happens UNCONDITIONALLY (including the
    # zero-events case), BUT the blob write happens only for
    # events != []. The two paths share the orm_fight fetch + the
    # _persist_player_summaries call; the ``events_blob_uri`` field
    # stays NULL for empty-events fights. The conditional pre-seed
    # INSIDE _persist_player_summaries (only when events == [])
    # produces one zero-totals row per attending agent.
    #
    # Note on the test_persist_event_blob_except.py contract: the
    # S3Error test exercises the non-empty ``events`` path and
    # expects put_events to fail BEFORE the orm_fight fetch. We
    # therefore ORDER the blob-write attempt BEFORE the fetch in
    # the non-empty branch, returning early on S3Error so the
    # orm_fight fetch is skipped (preserving the test's
    # dev-mock-``db=None`` invariant).
    if events:
        try:
            jsonl = "\n".join(event.model_dump_json() for event in events).encode("utf-8")
            gz_bytes = gzip.compress(jsonl)
            blob_uri = put_events(fight_id, gz_bytes)
        except (EvtcParseError, S3Error, OSError, gzip.BadGzipFile):
            logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
            return

        orm_fight = db.execute(
            select(OrmFight).where(OrmFight.id == fight_id).options(selectinload(OrmFight.agents)),
        ).scalar_one_or_none()
        if orm_fight is None:
            return

        orm_fight.events_blob_uri = blob_uri
        try:
            _persist_player_summaries(db, orm_fight, events)
        except SQLAlchemyError:
            logger.exception(
                "player summary materialization failed for fight %s; "
                "slow-path fallback will serve the player routes",
                fight_id,
            )
        return

    # Empty-events branch: only write the summary (no blob).
    logger.debug("upload %s yielded zero events; events_blob_uri stays NULL", upload.id)
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
