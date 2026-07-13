"""MinIO client wrapper for V0.5.

Provides a content-addressed blob store keyed by SHA-256. We do not
treat this as the source of truth for fights — Postgres is. The MinIO
blob exists for re-parsing when the parser learns to read more events.
"""

from __future__ import annotations

import io
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from gw2analytics_api.config import get_settings


@lru_cache(maxsize=1)
def get_minio() -> Minio:
    """Return the process-wide MinIO client."""
    s = get_settings()
    return Minio(
        s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=s.minio_secure,
    )


def _ensure_bucket(client: Minio, bucket: str) -> None:
    """Auto-create ``bucket`` on first use; tolerate concurrent workers."""
    if not client.bucket_exists(bucket):
        try:
            client.make_bucket(bucket)
        except S3Error:
            # Tolerate concurrent workers both racing the create — MinIO returns
            # BucketAlreadyOwnedByYou or BucketAlreadyExists which we treat as OK.
            if not client.bucket_exists(bucket):
                raise


def put_zevtc(sha256: str, data: bytes) -> str:
    """Upload a ``.zevtc`` blob content-addressed by SHA-256.

    Returns the object key used. Auto-creates the bucket on first use.
    Raises :class:`S3Error` if the upload fails for non-trivial reasons.
    """
    settings = get_settings()
    client = get_minio()
    bucket = settings.minio_bucket
    _ensure_bucket(client, bucket)
    key = f"{sha256}.zevtc"
    client.put_object(
        bucket,
        key,
        io.BytesIO(data),
        len(data),
        content_type="application/octet-stream",
    )
    return key


def put_events(fight_id: str, gz_data: bytes) -> str:
    """Upload a per-fight gzipped JSONL event blob under ``events/{fight_id}.jsonl.gz``.

    Phase 7 v1 storage contract: ``gz_data`` is the gzip-compressed
    JSONL output of :func:`PythonEvtcParser.parse_events` ``->``
    ``damage_event.model_dump_json()`` per line. ``content_type`` is
    ``application/gzip`` so HTTP fetches can decompress transparently
    via ``Content-Encoding`` if a downstream proxy ever needs to.

    Returns the object key (``events/{fight_id}.jsonl.gz``). The caller
    is responsible for persisting this key on
    :attr:`OrmFight.events_blob_uri`.
    """
    settings = get_settings()
    client = get_minio()
    bucket = settings.minio_bucket
    _ensure_bucket(client, bucket)
    key = f"events/{fight_id}.jsonl.gz"
    client.put_object(
        bucket,
        key,
        io.BytesIO(gz_data),
        len(gz_data),
        content_type="application/gzip",
    )
    return key


def get_events(key: str) -> bytes:
    """Fetch a previously-uploaded events blob.

    Returns the raw (still gzipped) bytes so the caller can decompress
    with :func:`gzip.decompress`. Raises :class:`S3Error` if the key is
    missing so the route can map ``NoSuchKey`` to ``404 Not Found``.
    """
    client = get_minio()
    bucket = get_settings().minio_bucket
    response = client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
