from __future__ import annotations

import gzip

import pytest

from gw2analytics_api.routes.fights.blob_cache import _cached_get_events, clear_blob_caches


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_blob_caches()


def test_cache_dedupes_minio_get_per_blob_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        call_count["n"] += 1
        return gzip.compress(b"event")

    monkeypatch.setattr("gw2analytics_api.routes.fights.blob_cache.get_events", fake_get_events)
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    assert call_count["n"] == 1


def test_cache_invalidates_on_new_blob_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        call_count["n"] += 1
        return gzip.compress(b"event")

    monkeypatch.setattr("gw2analytics_api.routes.fights.blob_cache.get_events", fake_get_events)
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT123_v2.jsonl.gz")
    assert call_count["n"] == 2


def test_cache_maxsize_evicts_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.blob_cache.get_events",
        lambda uri: gzip.compress(b"event"),
    )
    for i in range(9):
        _cached_get_events(f"s3://bucket/events/FIGHT{i}.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT0.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT10.jsonl.gz")
