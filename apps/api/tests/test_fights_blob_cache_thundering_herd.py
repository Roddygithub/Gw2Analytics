from __future__ import annotations

import gzip
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from minio.error import S3Error

from gw2analytics_api.routes.fights.blob_cache import _cached_get_events, clear_blob_caches


class _FakeS3Error(S3Error):
    def __init__(self) -> None:
        Exception.__init__(self)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_blob_caches()


def test_cache_dedupes_concurrent_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        call_count["n"] += 1
        time.sleep(0.05)
        return gzip.compress(b"event")

    monkeypatch.setattr("gw2analytics_api.routes.fights.blob_cache.get_events", fake_get_events)

    barrier = threading.Barrier(4)

    def call() -> bytes:
        barrier.wait(timeout=2.0)
        return _cached_get_events("s3://bucket/events/SAME.jsonl.gz")

    with threading.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: call(), range(4)))

    assert call_count["n"] == 1
    assert all(r == results[0] for r in results)


def test_concurrent_calls_to_distinct_uris(monkeypatch: pytest.MonkeyPatch) -> None:
    per_call_latency_s = 0.05

    def fake_get_events(uri: str) -> bytes:
        time.sleep(per_call_latency_s)
        return gzip.compress(b"event")

    monkeypatch.setattr("gw2analytics_api.routes.fights.blob_cache.get_events", fake_get_events)

    barrier = threading.Barrier(4)
    uris = [f"s3://bucket/events/FIGHT{i}.jsonl.gz" for i in range(4)]

    def call(uri: str) -> bytes:
        barrier.wait(timeout=2.0)
        return _cached_get_events(uri)

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(call, uris))
    elapsed = time.monotonic() - start

    assert elapsed < per_call_latency_s * 2.0


def test_exception_does_not_poison_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        attempt["n"] += 1
        if attempt["n"] == 1:
            raise _FakeS3Error()
        return gzip.compress(b"event")

    monkeypatch.setattr("gw2analytics_api.routes.fights.blob_cache.get_events", fake_get_events)

    with pytest.raises(S3Error):
        _cached_get_events("s3://bucket/events/transient.jsonl.gz")
    result = _cached_get_events("s3://bucket/events/transient.jsonl.gz")
    assert gzip.decompress(result) == b"event"
    assert attempt["n"] == 2
