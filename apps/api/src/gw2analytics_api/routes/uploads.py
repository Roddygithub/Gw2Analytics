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

import asyncio
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gw2analytics_api import config as _config
from gw2analytics_api.database import get_session, get_sessionmaker
from gw2analytics_api.limiter import limiter
from gw2analytics_api.models import Upload
from gw2analytics_api.schemas import UploadCreatedResponse, UploadOut
from gw2analytics_api.services import process_parse
from gw2analytics_api.storage import put_zevtc
from gw2analytics_api.workers.webhook_dispatch import dispatch_for_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


async def _enqueue_parse(
    request: Request,
    upload_id: uuid.UUID,
    raw: bytes,
) -> None:
    """Enqueue the parse + dispatch chain via Arq (with sync-in-request fallback).

    v0.10.1 plan 010: the primary path is the Arq pool (``request.app.state.arq_pool``).
    The Arq worker runs ``parse_job`` in a dedicated process with its
    own GIL, so 8 parallel uploads no longer block each other (closes
    bug #2 found by real-payload testing).

    The **sync-in-request fallback** runs the parse + dispatch in
    ``asyncio.to_thread`` if the Arq pool is unavailable (test env
    without Redis; production with a misconfigured broker should
    crash at lifespan startup, not fall through here). The fallback
    is awaited in the request handler, so the 201 response is
    delayed by ``parse_duration + dispatch_duration`` -- this is
    intentional graceful-degradation, not a performance optimisation.
    The GIL bottleneck is NOT solved by this path.

    Why not a true ``BackgroundTasks`` (pre-v0.10.1 behavior)?
    ``BackgroundTasks`` fires AFTER the response is sent and
    would detach the parse from the request lifecycle, but it
    also re-introduces the pre-v0.10.1 race where the chained
    ``dispatch_for_upload`` ran before ``process_parse``
    committed (zero deliveries on every successful upload).
    The chained ``asyncio.to_thread`` path closes that race
    at the cost of response latency.
    """
    pool = getattr(request.app.state, "arq_pool", None)
    if pool is not None and not _config.get_settings().allow_inrequest_parse_fallback:
        await pool.enqueue_job("parse_job", str(upload_id), raw)
        return
    # Arq pool is None (Redis unreachable at lifespan startup)
    # OR the operator has explicitly opted in to the in-request
    # fallback via ``ALLOW_INREQUEST_PARSE_FALLBACK=1``. The latter
    # case is the common dev workflow: docker-compose spins up Redis
    # + the API, but no arq worker is running (the user opted out
    # to avoid yet another process to manage). Without this bypass,
    # the dev path enqueues the job to Redis, no worker consumes it,
    # and the upload sits in ``status='pending'`` forever (the UI's
    # ``attempt 7/15`` counter is just the frontend polling, not
    # real arq retries). v0.10.2 hotfix followup #11.
    #
    # In production (env var unset) the 503 below fires when Redis
    # is unreachable, which is the correct loud signal: a
    # misconfigured broker is an operational concern that deserves
    # a 5xx, not a silent latency increase.
    if not _config.get_settings().allow_inrequest_parse_fallback:
        logger.error(
            "arq pool unavailable; refusing upload %s to surface "
            "the misconfiguration (set ALLOW_INREQUEST_PARSE_FALLBACK=1 "
            "to opt-in to the in-request fallback)",
            upload_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Parser worker unavailable. Check Redis is up. Set"
                " ALLOW_INREQUEST_PARSE_FALLBACK=1 to opt-in to"
                " in-request parsing."
            ),
        )
    # Fallback: parse + dispatch in a thread pool (awaited in
    # the request handler). GIL contention is NOT solved; the
    # fallback is graceful-degradation only.
    logger.warning(
        "arq pool unavailable; running parse + dispatch in-request "
        "for upload %s (response delayed by parse duration)",
        upload_id,
    )
    sf = get_sessionmaker()
    await asyncio.to_thread(process_parse, sf, upload_id, raw)
    await dispatch_for_upload(sf, upload_id)


@router.post(
    "",
    response_model=UploadCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": (
                "Parser worker unavailable. The Arq broker (Redis) was"
                " unreachable at lifespan startup, so the upload"
                " pipeline cannot be enqueued. Set"
                " ALLOW_INREQUEST_PARSE_FALLBACK=1 to opt-in to the"
                " synchronous in-request fallback (degrades response"
                " latency; closes the GIL bottleneck mitigation)."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Parser worker unavailable. Check Redis is up."
                            " Set ALLOW_INREQUEST_PARSE_FALLBACK=1 to opt-in"
                            " to in-request parsing."
                        ),
                    },
                },
            },
        },
    },
)
@limiter.limit("5/minute")  # type: ignore[untyped-decorator]
async def create_upload(
    request: Request,
    file: UploadFile = File(..., description="A .zevtc combat log file"),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
) -> UploadCreatedResponse:
    """Accept a ``.zevtc`` upload."""
    max_size = _config.get_settings().max_upload_size_bytes

    # Defense-in-depth #1: reject oversized bodies before reading
    # them into memory. ``Content-Length`` is optional (chunked
    # encoding) but when present this short-circuits the OOM risk.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_size:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=(f"Request body too large. Maximum allowed is {max_size} bytes."),
                )
        except ValueError:
            # Malformed Content-Length; fall through and let the
            # read-time check below handle it.
            pass

    # Defense-in-depth #2: Starlette's UploadFile may already know
    # the file size from the multipart metadata. Reject before read.
    # Use ``getattr`` so an older Starlette pin (< 0.30 did not yet
    # expose the ``size`` attribute) does NOT raise ``AttributeError``;
    # the contract falls through to the read-time check below in that
    # case. Code-reviewer flagged for pre-0.30 deploys.
    file_size = getattr(file, "size", None)
    if file_size is not None and file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"File too large ({file_size} bytes). Maximum allowed is {max_size} bytes."),
        )

    raw = file.file.read()
    if len(raw) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"File too large ({len(raw)} bytes). Maximum allowed is {max_size} bytes."),
        )
    sha = hashlib.sha256(raw).hexdigest()

    # Idempotent: SELECT before INSERT so we never see an IntegrityError
    # for the common re-upload path. The unique index is still the
    # authoritative guarantee against races.
    existing = db.execute(
        select(Upload).where(Upload.sha256 == sha),
    ).scalar_one_or_none()
    if existing is not None:
        # If the previous attempt failed, retry it via the Arq job
        # and surface "pending" so clients know a parse is in flight
        # (the old "failed" status confused upload-batch.sh).
        if existing.status == "failed":
            existing.status = "pending"
            db.flush()
            await _enqueue_parse(request, existing.id, raw)
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
        db.flush()
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

    # Persist the raw .zevtc blob BEFORE accepting the upload. A
    # missing blob makes re-parsing / replay impossible and creates
    # an orphaned DB record, so storage failures are treated as
    # hard errors (503) rather than best-effort warnings.
    try:
        put_zevtc(sha, raw)
    except (S3Error, OSError) as exc:
        logger.exception("MinIO put_zevtc failed; upload %s rejected", upload.id)
        db.rollback()
        # v0.10.26-pre: distinguish credential errors from availability
        # errors so the operator sees an actionable message.
        s3_code = getattr(exc, "code", None)
        if s3_code in ("SignatureDoesNotMatch", "InvalidAccessKeyId", "AccessDenied"):
            detail = (
                "S3 credential mismatch: the configured MinIO access key or "
                "secret key does not match the server. Check S3_ACCESS_KEY "
                "and S3_SECRET_KEY in the environment."
            )
        else:
            detail = (
                "Object storage unavailable; the upload could not be "
                "persisted. Retry once storage is healthy."
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc

    db.commit()
    await _enqueue_parse(request, upload.id, raw)
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
