"""MinIO client wrapper for V0.5.

Provides a content-addressed blob store keyed by SHA-256. We do not
treat this as the source of truth for fights — Postgres is. The MinIO
blob exists for re-parsing when the parser learns to read more events.
"""

from __future__ import annotations

import io

from minio import Minio
from minio.error import S3Error

from gw2analytics_api.config import get_settings

_client: Minio | None = None


def get_minio() -> Minio:
    """Return the process-wide MinIO client."""
    global _client  # noqa: PLW0603
    if _client is None:
        s = get_settings()
        _client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
    return _client


def put_zevtc(sha256: str, data: bytes) -> str:
    """Upload a ``.zevtc`` blob content-addressed by SHA-256.

    Returns the object key used. Auto-creates the bucket on first use.
    Raises :class:`S3Error` if the upload fails for non-trivial reasons.
    """
    settings = get_settings()
    client = get_minio()
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        try:
            client.make_bucket(bucket)
        except S3Error:
            # Tolerate concurrent workers both racing the create — MinIO returns
            # BucketAlreadyOwnedByYou or BucketAlreadyExists which we treat as OK.
            if not client.bucket_exists(bucket):
                raise
    key = f"{sha256}.zevtc"
    client.put_object(
        bucket,
        key,
        io.BytesIO(data),
        len(data),
        content_type="application/octet-stream",
    )
    return key
