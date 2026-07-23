from __future__ import annotations

import threading
import time

from gw2analytics_api.storage import get_events

_cache: dict[str, tuple[float, bytes]] = {}
_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()
_MAXSIZE = 8
_TTL = 300


def _get_cache_lock(blob_uri: str) -> threading.Lock:
    """Atomically fetch (or create) a per-URI lock for blob cache deduplication."""
    lock = _locks.get(blob_uri)
    if lock is not None:
        return lock
    with _locks_meta:
        lock = _locks.get(blob_uri)
        if lock is None:
            lock = threading.Lock()
            _locks[blob_uri] = lock
    return lock


def _cached_get_events(blob_uri: str) -> bytes:
    now = time.monotonic()
    existing = _cache.get(blob_uri)
    if existing is not None:
        ts, val = existing
        if now - ts < _TTL:
            return val
        del _cache[blob_uri]

    # Per-URI double-checked locking: different URIs contend on
    # separate locks (parallel fetches for distinct fights stay
    # concurrent); concurrent calls for the SAME URI coalesce.
    with _get_cache_lock(blob_uri):
        existing = _cache.get(blob_uri)
        if existing is not None:
            ts, val = existing
            if now - ts < _TTL:
                return val

        if len(_cache) >= _MAXSIZE:
            k = next(iter(_cache))
            del _cache[k]

        result = get_events(blob_uri)
        _cache[blob_uri] = (now, result)
        return result


def clear_blob_caches() -> None:
    _cache.clear()
