from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

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

        _save_fight(db, upload, core_fight)
        _persist_event_blob(db, upload, evtc_bytes, core_fight.id)
        upload.status = UPLOAD_STATUS_COMPLETED
        upload.error_message = None
        upload.parser_version = PARSER_VERSION
        db.commit()
