"""Domain ⇄ ORM translation.

Maps a :class:`gw2_core.Fight` (Pydantic V2, stable internal model) to
the SQLAlchemy ORM rows persisted in Postgres. Errors here write to
``uploads.error_message`` rather than raised, so the API stays alive.

Phase 7 v1 also persists the parsed event stream: after :func:`_save_fight`
inserts the fight row + per-agent + per-skill rows, the same parser is
fed through :meth:`PythonEvtcParser.parse_events` to drain the cbtevent
block. Each :class:`DamageEvent` is serialised as JSONL, the stream is
gzip-compressed, the bytes are uploaded to MinIO at
``events/{fight_id}.jsonl.gz``, and the storage key is written back to
``OrmFight.events_blob_uri``. Zero-event fights keep ``events_blob_uri
= NULL`` -- the parser degrades to no-blob rather than persist an
empty file. The ``GET /fights/{id}/events`` route surfaces ``404 Not
Found`` for those rows rather than a misleading empty aggregation.
"""

from __future__ import annotations

import gzip
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from gw2_core import EliteSpec, Profession
from gw2_core import Fight as DomainFight
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser, read_zevtc_bytes
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    UPLOAD_STATUS_FAILED,
    OrmFight,
    OrmFightAgent,
    OrmFightSkill,
    Upload,
)
from gw2analytics_api.storage import put_events

logger = logging.getLogger(__name__)


def process_parse(db: Session, upload_id: uuid.UUID, raw_bytes: bytes) -> None:
    """Run the V0 parser on the uploaded blob and persist Fight+Agent rows.

    Dispatched by FastAPI ``BackgroundTasks`` from ``POST /api/v1/uploads``.
    The ``db`` Session is the request-scoped one; FastAPI runs background
    tasks *after* the response is sent and *before* the dependency
    generator's ``finally`` block closes the session, so the session is
    still usable here. When 5+ concurrent uploads is the norm, we move
    to a dedicated queue (Arq) with a **fresh, worker-scoped** session
    — never reuse the request session in the worker.
    """
    upload = db.get(Upload, upload_id)
    if upload is None:
        logger.error("upload %s disappeared between POST and parse", upload_id)
        return
    try:
        # ``.zevtc`` files are zip wrappers around the raw EVTC blob.
        # ``read_zevtc_bytes`` is the single source of truth for the
        # zip-discriminate-unwrap contract: it returns the inner EVTC for
        # valid zips and raises :class:`EvtcParseError` for anything else
        # (bogus zip, non-zip bytes, empty archive — all caught below).
        evtc_bytes = read_zevtc_bytes(raw_bytes)
        fights = list(PythonEvtcParser().parse(evtc_bytes))
    except EvtcParseError as exc:
        logger.warning("parse failed for upload %s: %s", upload_id, exc)
        upload.status = UPLOAD_STATUS_FAILED
        upload.error_message = f"EvtcParseError: {exc}"
        db.commit()
        return
    except (RuntimeError, ValueError) as exc:
        # Surface genuine Python bugs (e.g. ``_save_fight`` raises
        # ``ValueError`` defensively if a fight arrives without a header) and
        # unexpected parser misbehaviour (``RuntimeError``) rather than hide
        # them behind a generic "failed" status.
        logger.exception("parse exception for upload %s", upload_id)
        upload.status = UPLOAD_STATUS_FAILED
        upload.error_message = f"{type(exc).__name__}: {exc}"
        db.commit()
        return

    if not fights:
        upload.status = UPLOAD_STATUS_FAILED
        upload.error_message = "parser yielded no fights"
        db.commit()
        return

    core_fight = fights[0]
    if core_fight.header is None:
        upload.status = UPLOAD_STATUS_FAILED
        upload.error_message = "parser yielded fight without header"
        db.commit()
        return

    _save_fight(db, upload, core_fight)
    _persist_event_blob(db, upload, evtc_bytes, core_fight.id)
    upload.status = UPLOAD_STATUS_COMPLETED
    upload.error_message = None
    db.commit()


def _save_fight(db: Session, upload: Upload, cf: DomainFight) -> None:
    """Translate ``core_fight`` to ORM rows in the current session."""
    if cf.header is None:
        msg = "_save_fight called without header"
        raise ValueError(msg)

    head = cf.header
    # EVTC blobs do not carry a wall clock. ``cf.started_at`` defaults
    # to the Unix epoch sentinel (``datetime(1970, 1, 1, tzinfo=UTC)``
    # in :class:`gw2_core.Fight`), so we MUST override with the
    # server's wall clock at parse time. The previous
    # ``cf.started_at if cf.started_at.tzinfo else datetime.now(UTC)``
    # guard was a bug: the epoch sentinel HAS tzinfo (UTC), so the
    # guard fell through and every fight landed on 1970-01-01
    # midnight UTC, breaking the v0.8.0 timeline chart (all points
    # stack at the leftmost X-axis slot). v0.8.1 unconditionally
    # uses ``datetime.now(UTC)``; a future v0.9 could parse the
    # EVTC build field (``yyyymmdd``) to get a date anchor.
    started_at = datetime.now(UTC)

    orm_fight = OrmFight(
        id=cf.id,
        upload_id=upload.id,
        build_version=head.build_version,
        encounter_id=head.encounter_id,
        agent_count=head.agent_count,
        started_at=started_at,
        game_type=int(cf.game_type),
    )
    db.add(orm_fight)
    db.flush()

    for agent in cf.agents:
        db.add(
            OrmFightAgent(
                fight_id=cf.id,
                agent_id=int(agent.id),
                name=agent.name or "",
                profession=_prof_id(agent.profession),
                elite_spec=_elite_id(agent.elite),
                is_player=agent.is_player,
                account_name=agent.account_name,
                subgroup=agent.subgroup,
            ),
        )

    for skill in cf.skills:
        db.add(
            OrmFightSkill(
                fight_id=cf.id,
                skill_id=int(skill.id),
                name=skill.name or "",
            ),
        )


def _prof_id(p: Profession) -> int:
    return int(p.value)


def _elite_id(e: EliteSpec) -> int:
    return int(e.value)


def _persist_event_blob(
    db: Session,
    upload: Upload,
    evtc_bytes: bytes,
    fight_id: str,
) -> None:
    """Drain the cbtevent block into a MinIO blob and write the key back.

    Phase 7 v1 behaviour:

    - Empty streams (zero damage events after the ``is_statechange == 0`` /
      ``is_nondamage == 0`` / ``value > 0`` filter) leave
      ``events_blob_uri`` as ``NULL``. We deliberately do NOT persist an
      empty blob: an empty blob would round-trip through the route as
      ``200 OK`` with zero damage + zero events, misleading consumers
      into thinking the parser ran but nothing happened. ``NULL`` instead
      signals "no event data available", which the route surfaces as
      ``404 Not Found`` (consistent with pre-Phase 7 fights).
    - ANY exception raised by ``parse_events`` or ``put_events`` is
      logged and swallowed so the upload still flips to ``COMPLETED``
      with the fight-row + agents + skills persisted. The events blob
      is a deep-metrics concern; losing it must NOT lose the agents /
      skills already written. Operators can re-parse the upload to
      retry the blob upload without losing the agents/skills. The
      catch is intentionally broad because this call sits OUTSIDE
      the ``process_parse`` try/except -- the 3-tier classification
      previously here has been collapsed to one ``except Exception``
      (the outer ``process_parse`` cannot classify the re-raise, and
      the historical ``(RuntimeError, ValueError, OSError)`` tier was
      both drift-prone (mentioned ``S3Error`` in the docstring but
      did not catch it) and effectively dead under the broad
      ``except Exception`` below it).
    """

    parser = PythonEvtcParser()
    try:
        events = list(parser.parse_events(evtc_bytes))
        if not events:
            logger.debug("upload %s yielded zero events; events_blob_uri stays NULL", upload.id)
            return
        jsonl = "\n".join(event.model_dump_json() for event in events).encode("utf-8")
        gz_bytes = gzip.compress(jsonl)
        blob_uri = put_events(fight_id, gz_bytes)
    except Exception:
        # ``parse_events`` raises ``EvtcParseError`` on malformed
        # archives; ``put_events`` raises ``S3Error`` (and ``OSError``
        # variants) on MinIO failures; anything truly unexpected
        # lands here too. All three are treated identically: degrade
        # to ``events_blob_uri = NULL``, keep the fight-row contract
        # intact.
        logger.exception("event blob unavailable for fight %s; deep metrics degraded", fight_id)
        return

    orm_fight = db.execute(select(OrmFight).where(OrmFight.id == fight_id)).scalar_one_or_none()
    if orm_fight is not None:
        orm_fight.events_blob_uri = blob_uri
