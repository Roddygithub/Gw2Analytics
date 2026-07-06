"""/api/v1/uploads`` endpoints.

POST : accept a multipart ``.zevtc``, hash it, store it in MinIO,
parse it via :class:`PythonEvtcParser`, persist the parsed Fight
+ agents, return the upload id (and the resulting fight id through
``/fights/{id}``).

GET  : return current parse status.

Idempotency: re-uploading the same bytes returns the **same** upload
id (we never overwrite the row; we just re-run the parse if the prior
attempt failed).
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gw2analytics_api.database import get_session
from gw2analytics_api.models import Upload
from gw2analytics_api.schemas import UploadCreatedResponse, UploadOut
from gw2analytics_api.services import process_parse
from gw2analytics_api.storage import put_zevtc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


@router.post(
    "",
    response_model=UploadCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="A .zevtc combat log file"),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
) -> UploadCreatedResponse:
    """Accept a ``.zevtc`` upload."""
    raw = file.file.read()
    sha = hashlib.sha256(raw).hexdigest()

    # Idempotent: SELECT before INSERT so we never see an IntegrityError
    # for the common re-upload path. The unique index is still the
    # authoritative guarantee against races.
    existing = db.execute(
        select(Upload).where(Upload.sha256 == sha),
    ).scalar_one_or_none()
    if existing is not None:
        # If the previous attempt failed, retry it via background task;
        # otherwise return the existing record untouched.
        if existing.status == "failed":
            background_tasks.add_task(process_parse, db, existing.id, raw)
        return UploadCreatedResponse(
            id=existing.id,
            sha256=existing.sha256,
            status=existing.status,
        )

    upload = Upload(
        id=uuid.uuid4(),
        sha256=sha,
        original_filename=file.filename or "unknown.zevtc",
        size_bytes=len(raw),
        status="pending",
    )
    db.add(upload)
    try:
        db.commit()
    except IntegrityError:
        # Race lost — re-fetch and return existing.
        db.rollback()
        existing = db.execute(
            select(Upload).where(Upload.sha256 == sha),
        ).scalar_one()
        return UploadCreatedResponse(
            id=existing.id,
            sha256=existing.sha256,
            status=existing.status,
        )

    # Best-effort MinIO dump — narrow exception scope so unexpected
    # bugs in storage.py don't get swallowed silently. ``S3Error`` is
    # what the minio library raises; real bugs (e.g. TypeErrors) propagate up.
    try:
        put_zevtc(sha, raw)
    except (S3Error, OSError):
        logger.exception("MinIO put_zevtc failed; upload remains usable without blob")

    background_tasks.add_task(process_parse, db, upload.id, raw)
    return UploadCreatedResponse(
        id=upload.id,
        sha256=upload.sha256,
        status=upload.status,
    )


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(
    upload_id: uuid.UUID,
    db: Session = Depends(get_session),  # noqa: B008
) -> UploadOut:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
    return UploadOut(
        id=upload.id,
        sha256=upload.sha256,
        original_filename=upload.original_filename,
        size_bytes=upload.size_bytes,
        uploaded_at=upload.uploaded_at,
        status=upload.status,
        error_message=upload.error_message,
        parser_version=upload.parser_version,
        fight_id=upload.fight.id if upload.fight else None,
    )
