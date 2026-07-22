"""
Optional integration test for MinIO connectivity.

Skipped by default (``RUN_INTEGRATION_TESTS`` is not set). When
enabled with ``RUN_INTEGRATION_TESTS=1``, this test verifies that
a real MinIO server is reachable at the configured endpoint with
the configured credentials.

Usage::

    RUN_INTEGRATION_TESTS=1 uv run pytest apps/api/tests/test_integration_minio.py -v

Requires docker-compose MinIO (or equivalent) running on the
configured ``S3_ENDPOINT`` with matching ``S3_ACCESS_KEY`` /
``S3_SECRET_KEY``.
"""

from __future__ import annotations

import contextlib
import os

import pytest

from gw2analytics_api.config import get_settings
from gw2analytics_api.storage import get_minio

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION_TESTS") != "1",
        reason="integration tests disabled; set RUN_INTEGRATION_TESTS=1 to enable",
    ),
]


def test_minio_connectivity() -> None:
    """Verify the real MinIO server responds to list_buckets.

    A ``SignatureDoesNotMatch`` / ``InvalidAccessKeyId`` /
    ``AccessDenied`` error indicates misconfigured credentials.
    A ``ConnectionError`` / ``OSError`` / timeout indicates
    the server is unreachable.
    """
    s = get_settings()
    client = get_minio()
    buckets = client.list_buckets()
    bucket_names = [b.name for b in buckets]
    assert s.minio_bucket in bucket_names, (
        f"Expected bucket {s.minio_bucket!r} to exist on "
        f"{s.minio_endpoint}. Found buckets: {bucket_names}"
    )


def test_minio_bucket_read_write() -> None:
    """Round-trip a small blob through the real MinIO.

    Creates a test object, reads it back, and verifies the
    content matches. Cleans up the object on success.
    """
    from minio.error import S3Error

    s = get_settings()
    client = get_minio()
    bucket = s.minio_bucket
    key = "_integration_test_write_ok_.txt"
    payload = b"integration-test-payload-ok"

    # Write
    client.put_object(
        bucket,
        key,
        __import__("io").BytesIO(payload),
        len(payload),
        content_type="text/plain",
    )

    try:
        # Read back
        response = client.get_object(bucket, key)
        try:
            data = response.read()
            assert data == payload, f"Read-back mismatch: expected {payload!r}, got {data!r}"
        finally:
            response.close()
            response.release_conn()
    finally:
        # Cleanup
        with contextlib.suppress(S3Error):
            client.remove_object(bucket, key)
