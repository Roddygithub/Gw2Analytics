"""Domain ⇄ ORM translation.

Maps a :class:`gw2_core.Fight` (Pydantic V2, stable internal model) to
the SQLAlchemy ORM rows persisted in Postgres. Errors here write to
``uploads.error_message`` rather than raised, so the API stays alive.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from gw2_core import EliteSpec, Profession
from gw2_core import Fight as DomainFight
from gw2_evtc_parser import EvtcParseError, PythonEvtcParser, read_zevtc_bytes
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    UPLOAD_STATUS_FAILED,
    OrmFight,
    OrmFightAgent,
    Upload,
)

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
    upload.status = UPLOAD_STATUS_COMPLETED
    upload.error_message = None
    db.commit()


def _save_fight(db: Session, upload: Upload, cf: DomainFight) -> None:
    """Translate ``core_fight`` to ORM rows in the current session."""
    if cf.header is None:
        msg = "_save_fight called without header"
        raise ValueError(msg)

    head = cf.header
    # Use upload's UTCnow — the EVTC blob does not carry a wall clock.
    started_at = cf.started_at if cf.started_at.tzinfo else datetime.now(UTC)

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
            ),
        )


def _prof_id(p: Profession) -> int:
    return int(p.value)


def _elite_id(e: EliteSpec) -> int:
    return int(e.value)
