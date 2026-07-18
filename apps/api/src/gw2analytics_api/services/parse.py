from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


def process_parse(  # noqa: PLR0915, PLR0911
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
            fights = list(_parser.parse(evtc_bytes))
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

        try:
            _save_fight(db, upload, core_fight)
        except IntegrityError:
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
            # re-fetch via ``db.get(Upload, upload_id)`` BEFORE updating.
            logger.warning(
                "fight_id collision for upload %s; existing fight_id=%s",
                upload_id,
                core_fight.id,
            )
            db.rollback()
            upload = db.get(Upload, upload_id)
            if upload is not None:
                upload.status = UPLOAD_STATUS_FAILED
                upload.error_message = f"The content is already analyzed as fight {core_fight.id}"
                db.commit()
            return
        try:
            _persist_event_blob(db, upload, evtc_bytes, core_fight.id)
        except IntegrityError:
            # v0.10.28 plan 160 reviewer NICE-to-HAVE: distinct error
            # message for the event-blob collision so operators can
            # diagnose which layer fired (NOT the fight_id collision
            # branch). Defense-in-depth preserved -- a future OrmEvent
            # unique constraint surfaces as status='failed' instead
            # of an unhandled 500.
            logger.warning(
                "event_blob collision for upload %s; fight_id=%s",
                upload_id,
                core_fight.id,
            )
            db.rollback()
            upload = db.get(Upload, upload_id)
            if upload is not None:
                upload.status = UPLOAD_STATUS_FAILED
                upload.error_message = f"Event blob persistence collision for fight {core_fight.id}"
                db.commit()
            return
        upload.status = UPLOAD_STATUS_COMPLETED
        upload.error_message = None
        upload.parser_version = PARSER_VERSION
        db.commit()
