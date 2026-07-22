from __future__ import annotations

import time

from gw2analytics_api.storage import get_events

_cache: dict[str, tuple[float, bytes]] = {}
_MAXSIZE = 8
_TTL = 300


def _cached_get_events(blob_uri: str) -> bytes:
    now = time.monotonic()
    existing = _cache.get(blob_uri)
    if existing is not None:
        ts, val = existing
        if now - ts < _TTL:
            return val
        del _cache[blob_uri]

    if len(_cache) >= _MAXSIZE:
        k = next(iter(_cache))
        del _cache[k]

    result = get_events(blob_uri)
    _cache[blob_uri] = (now, result)
    return result


def clear_blob_caches() -> None:
    _cache.clear()
