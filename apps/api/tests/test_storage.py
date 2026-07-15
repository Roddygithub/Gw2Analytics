"""Tests for ``gw2analytics_api.storage``.

v0.10.22 followup: lock the ``S3_ENDPOINT`` URL parsing that extracts
``host:port`` for the MinIO client and derives ``secure`` from the
scheme. The MinIO constructor rejects full URLs such as
``http://localhost:9000`` with ``ValueError: path in endpoint is not
allowed``.
"""

from __future__ import annotations

from gw2analytics_api.storage import _parse_minio_endpoint


def test_parse_minio_endpoint_http() -> None:
    endpoint, secure = _parse_minio_endpoint("http://localhost:9000", default_secure=True)
    assert endpoint == "localhost:9000"
    assert secure is False


def test_parse_minio_endpoint_https() -> None:
    endpoint, secure = _parse_minio_endpoint("https://minio.example.com", default_secure=False)
    assert endpoint == "minio.example.com"
    assert secure is True


def test_parse_minio_endpoint_host_port() -> None:
    endpoint, secure = _parse_minio_endpoint("localhost:9000", default_secure=False)
    assert endpoint == "localhost:9000"
    assert secure is False


def test_parse_minio_endpoint_https_with_port() -> None:
    endpoint, secure = _parse_minio_endpoint("https://localhost:9000", default_secure=False)
    assert endpoint == "localhost:9000"
    assert secure is True


def test_parse_minio_endpoint_ignores_path() -> None:
    endpoint, secure = _parse_minio_endpoint("http://localhost:9000/minio", default_secure=True)
    assert endpoint == "localhost:9000"
    assert secure is False


def test_parse_minio_endpoint_preserves_default_secure() -> None:
    endpoint, secure = _parse_minio_endpoint("localhost:9000", default_secure=True)
    assert endpoint == "localhost:9000"
    assert secure is True
