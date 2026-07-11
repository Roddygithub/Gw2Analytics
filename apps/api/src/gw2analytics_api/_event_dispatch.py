"""Canonical ``Event`` dispatch hub for the apps/api surface.

Single ``TypeAdapter[Event]`` instance + the blob-load +
decompress + event-split + adapter-validation round-trip
reused across :mod:`backfill`, :mod:`routes.fights`, and
:mod:`routes.players`.

Why a dedicated module
----------------------
The previous design instantiated ``TypeAdapter(Event)`` at
module-load time in THREE places (``backfill.py``,
``routes/fights.py``, ``routes/players.py``). The construction
is non-free + caches a discriminator-validation scope, so
each duplicate is real overhead. More importantly, a future
``Event`` subclass (Phase 9 condition-damage, Phase 10
``BuffApplicationEvent``) propagates to the dispatch
automatically when all three call the same instance; three
independent instances risk ONE going stale.

``backfill.py`` historically documented the duplication
("we duplicate the adapter here rather than importing the
route's private constant so the backfill module has no
dependency on the route module"); the rationalisation was
valid at the time but the module-dependency concern is now
addressed by co-locating ``TypeAdapter(Event)`` in a primitive
(no route module deps) hub.
"""

from __future__ import annotations

import gzip
import io
from collections.abc import Iterator

from pydantic import TypeAdapter

from gw2_core import Event

# Canonical adapter: ONE module-level instance for the whole
# apps/api process lifetime. See the docstring above for why
# this is the single source-of-truth.
EVENT_TYPE_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def build_event_iterator(*, gz_bytes: bytes) -> Iterator[Event]:
    """Decompress + split + adapter-validate a gzipped JSONL blob, streaming.

    Centralises the gzip-decompress -> splitlines -> TypeAdapter.validate_json
    round-trip that 3 surfaces (:func:`backfill._backfill_one_fight`,
    :func:`routes.fights._load_fight_events`, and
    :func:`routes.players._contributions_from_blob_walk`) previously
    hand-rolled.

    v0.10.10 plan 027: switched from ``gzip.decompress + splitlines``
    (which materialised the FULL decompressed JSONL string + a
    complete list of strings BEFORE yielding) to a streaming
    ``gzip.GzipFile(fileobj=io.BytesIO(gz_bytes))`` wrapper. The new
    path keeps memory peak at the zlib-chunk buffer (~32-64 KB)
    regardless of the input size -- a 30 MB gzipped WvW log no longer
    spikes to 200 MB of strings + a 60k line list. The frontend's
    ``Promise.allSettled`` fires 4 parallel ``/fights/{id}/*``
    requests; pre-fix, 4 parallel calls to this helper on the same
    blob would each peak at ~200 MB, totaling ~800 MB for one page
    load. Post-fix, total peak is bounded by the zlib-chunk buffer
    + the Pydantic model objects yielded so far.

    ``TypeAdapter.validate_json`` accepts ``bytes`` directly (Pydantic
    v2 parses the JSON line in place); no ``.decode("utf-8")``
    round-trip is needed.

    Empty / whitespace-only lines are dropped: ``bytes.strip()``
    strips both embedded whitespace and the trailing ``\\n``, so
    ``if not line.strip()`` accepts only non-empty trimmed lines.
    """
    with gzip.GzipFile(fileobj=io.BytesIO(gz_bytes)) as gz:
        for line in gz:
            if not line.strip():
                continue
            yield EVENT_TYPE_ADAPTER.validate_json(line)


__all__ = [
    "EVENT_TYPE_ADAPTER",
    "build_event_iterator",
]
