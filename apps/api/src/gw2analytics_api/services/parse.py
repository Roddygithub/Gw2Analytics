from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gw2_core import Fight as DomainFight
from gw2_evtc_parser import (
    EvtcParseError,
    PythonEvtcParser,
    read_zevtc_bytes,
)
from gw2_evtc_parser import (
    __version__ as PARSER_VERSION,  # noqa: N812
)
from gw2analytics_api.models import (
    UPLOAD_STATUS_COMPLETED,
    UPLOAD_STATUS_FAILED,
    Upload,
)
from gw2analytics_api.services.event_blob import _persist_event_blob
from gw2analytics_api.services.fight_persistence import _save_fight

logger = logging.getLogger(__name__)

# Module-level singleton: PythonEvtcParser is stateless and safe to reuse.
_parser = PythonEvtcParser()


def _commit_fight_and_blob(
    db: Session,
    upload: Upload,
    core_fight: DomainFight,
    evtc_bytes: bytes,
) -> bool:
    """Persist fight + event blob, handling collision errors (Phase 5.1).

    Returns ``True`` on success. Returns ``False`` if either the
    ``_save_fight`` or ``_persist_event_blob`` call raises an
    :class:`IntegrityError` (collision: a previous parse already
    created this fight_id or its event blob). The caller MUST
    check the return value and skip the completion step when
    ``False`` is returned.

    On collision the function rolls back the session, re-fetches
    the upload row (SQLAlchemy detaches ORM objects after rollback),
    marks it as ``failed`` with a descriptive message, and commits
    the status update.
    """
    # v0.10.28 plan 160: fight_id collision (2 distinct uploads
    # with the same parsed fight content). The Postgres unique
    # constraint on ``OrmFight.id`` fires here on the second
    # parse; we rollback + mark the upload as failed with the
    # existing fight_id surfaced so an operator can pivot to
    # the prior successful parse via ``/fights/{existing_id}``.
    # The audit row is preserved (no DELETE) so the duplicate
    # upload is still inspectable.
    #
    # Critical gotcha: SQLAlchemy expires ALL session objects
    # after ``rollback()`` -- the original ``upload`` is detached
    # and mutating it raises ``DetachedInstanceError``. We must
    # re-fetch via ``db.get(Upload, upload.id)`` BEFORE updating.
    try:
        _save_fight(db, upload, core_fight)
    except IntegrityError:
        logger.warning(
            "fight_id collision for upload %s; existing fight_id=%s",
            upload.id,
            core_fight.id,
        )
        db.rollback()
        re_fetched = db.get(Upload, upload.id)
        if re_fetched is not None:
            re_fetched.status = UPLOAD_STATUS_FAILED
            re_fetched.error_message = f"The content is already analyzed as fight {core_fight.id}"
            db.commit()
        return False

    # v0.10.28 plan 160 reviewer NICE-to-HAVE: distinct error
    # message for the event-blob collision so operators can
    # diagnose which layer fired (NOT the fight_id collision
    # branch). Defense-in-depth preserved -- a future OrmEvent
    # unique constraint surfaces as status='failed' instead
    # of an unhandled 500.
    try:
        _persist_event_blob(db, upload, evtc_bytes, core_fight.id)
    except IntegrityError:
        logger.warning(
            "event_blob collision for upload %s; fight_id=%s",
            upload.id,
            core_fight.id,
        )
        db.rollback()
        re_fetched = db.get(Upload, upload.id)
        if re_fetched is not None:
            re_fetched.status = UPLOAD_STATUS_FAILED
            re_fetched.error_message = f"Event blob persistence collision for fight {core_fight.id}"
            db.commit()
        return False

    return True


def process_parse(
    session_factory: Callable[[], Session],
    upload_id: uuid.UUID,
    raw_bytes: bytes,
) -> None:
    with session_factory() as db:
        upload = db.get(Upload, upload_id)
        if upload is None:
            logger.error("upload %s disappeared between POST and parse", upload_id)
            return
        try:
            evtc_bytes = read_zevtc_bytes(raw_bytes)
            fights = _parser.parse(evtc_bytes)
            core_fight = next(fights, None)
        except EvtcParseError as exc:
            logger.warning("parse failed for upload %s: %s", upload_id, exc)
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = f"EvtcParseError: {exc}"
            db.commit()
            return
        except (RuntimeError, ValueError) as exc:
            logger.exception("parse exception for upload %s", upload_id)
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = f"{type(exc).__name__}: {exc}"
            db.commit()
            return

        if core_fight is None:
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = "parser yielded no fights"
            db.commit()
            return

        # Phase 4.2: log a warning for any extra fights beyond the first.
        for extra_fight in fights:
            logger.warning(
                "upload %s: extra fight %s ignored (only the first fight is stored)",
                upload_id,
                extra_fight.id,
            )

        if core_fight.header is None:
            upload.status = UPLOAD_STATUS_FAILED
            upload.error_message = "parser yielded fight without header"
            db.commit()
            return

        if not _commit_fight_and_blob(db, upload, core_fight, evtc_bytes):
            return

        upload.status = UPLOAD_STATUS_COMPLETED
        upload.error_message = None
        upload.parser_version = PARSER_VERSION
        db.commit()
