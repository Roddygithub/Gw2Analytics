"""v0.9.4 plan 014: cross-request cache for events blob bytes."""

from __future__ import annotations

import gzip

import pytest

from gw2analytics_api.routes.fights import _cached_get_events


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cached_get_events.cache_clear()
    yield
    _cached_get_events.cache_clear()


def test_cache_dedupes_minio_get_per_blob_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two calls on the same URI invoke the underlying get_events once."""
    call_count = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        call_count["n"] += 1
        return gzip.compress(b"event")

    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        fake_get_events,
    )
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    assert call_count["n"] == 1


def test_cache_invalidates_on_new_blob_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """A re-uploaded fight with a new blob_uri gets a fresh fetch."""
    call_count = {"n": 0}

    def fake_get_events(uri: str) -> bytes:
        call_count["n"] += 1
        return gzip.compress(b"event")

    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        fake_get_events,
    )
    _cached_get_events("s3://bucket/events/FIGHT123.jsonl.gz")
    _cached_get_events("s3://bucket/events/FIGHT123_v2.jsonl.gz")
    assert call_count["n"] == 2


def test_cache_maxsize_evicts_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    """9 calls with 9 distinct URIs trigger at least 1 eviction."""
    monkeypatch.setattr(
        "gw2analytics_api.routes.fights.get_events",
        lambda uri: gzip.compress(b"event"),
    )
    for i in range(9):
        _cached_get_events(f"s3://bucket/events/FIGHT{i}.jsonl.gz")
    info = _cached_get_events.cache_info()
    # ``functools.lru_cache.CacheInfo`` does not expose an
    # ``evictions`` attribute (it tracks hits, misses, maxsize,
    # currsize). The post-condition we CAN pin is that the
    # cache is at maxsize after 9 distinct URIs were requested
    # (the oldest entry was evicted to make room for the 9th).
    assert info.currsize == 8
    assert info.maxsize == 8
