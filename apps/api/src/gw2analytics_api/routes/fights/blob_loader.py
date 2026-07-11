"""Canonical blob-load + decompression + event-split primitive.

The shared helper that 5 endpoints on ``/fights/{id}/*`` (events,
squads, skills, timeline + per-player timeline) all use. The
helper enforces the canonical 404 / 502 contract:

- ``404 Not Found``: fight id is unknown OR
  ``events_blob_uri is None`` OR the blob is missing in MinIO
  (``S3Error``).
- ``404 Not Found``: the events list is empty after the
  ``jsonl.splitlines()`` pass (``list`` emptiness check).
- ``502 Bad Gateway``: the blob is present but
  ``gzip.decompress`` failed (corrupt blob).

Originally inlined in ``apps/api/src/gw2analytics_api/routes/fights/__init__.py``
pre-A2 god-module refactor. Extracted in PR 2 sub-commit 1.

Provenance
----------

The A2 god-module refactor (plan 021) decomposed
``routes/fights/__init__.py`` into a ``routes/fights/`` sub-pack:

- PR 1 (commits ``1565066`` + ``79bae42``) extracted the cache
  primitive to ``blob_cache.py`` + the conftest
  ``clear_blob_caches`` autouse wire-up.
- PR 2 sub-commit 1 (this commit) extracts the blob-load helper
  here. The helper sees no FastAPI dependency in the
  ``Session`` argument shape, but DOES raise ``HTTPException``
  directly (consistent with the original inline implementation);
  the route handlers stay thin on cloud-side state-translation
  responsibility.

Public surface
==============

- :func:`_load_fight_events` -- the shared DB + blob + decompress
  + parse helper.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from minio.error import S3Error
from sqlalchemy.orm import Session

from gw2_core import Event
from gw2analytics_api._event_dispatch import build_event_iterator
from gw2analytics_api.models import OrmFight
from gw2analytics_api.routes.fights.blob_cache import _cached_get_events

logger = logging.getLogger(__name__)


def _load_fight_events(
    db: Session,
    fight_id: str,
) -> list[Event]:
    """Load + decompress + parse the events blob for one fight.

    Centralises the blob-load + decompress + event-split pattern
    that :func:`get_fight_events`, :func:`get_fight_squads`,
    :func:`get_fight_skills`, :func:`get_fight_timeline`, and
    :func:`get_fight_player_timeline` all share. The helper
    enforces the canonical 404 / 502 contract:

    - ``404 Not Found``: fight id is unknown OR
      ``events_blob_uri is None`` OR the blob is missing in MinIO
      (``S3Error`` -- closes the loop if the upload succeeded but
      the MinIO write failed silently or was evicted).
    - ``404 Not Found``: the events list is empty after the
      ``jsonl.splitlines()`` pass. Defensive: the parser writes
      no empty blobs, but a 0-byte blob (manual PUT, replication
      drift) still honours the "no event data available" contract
      so the response never confuses "parser ran, nothing
      happened" with "data unavailable".
    - ``502 Bad Gateway``: the blob is present but
      ``gzip.decompress`` failed. A fight row with a corrupt blob
      is still a valid row; this is a blob-store consistency issue
      rather than a client error.

    Returns the parsed :class:`Event` list so the caller can split
    by ``isinstance`` at the call site and feed the per-kind
    streams to the aggregators (the v0.7.0 SquadRollup + SkillUsage
    aggregators accept paired single-typed streams; the per-target
    trio each accept one single-typed stream).
    """
    fight = db.get(OrmFight, fight_id)
    if fight is None or fight.events_blob_uri is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fight not found")

    try:
        gz_bytes = _cached_get_events(fight.events_blob_uri)
    except S3Error:
        logger.warning(
            "events blob %s missing in MinIO for fight %s",
            fight.events_blob_uri,
            fight_id,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable") from None

    try:
        events = list(build_event_iterator(gz_bytes=gz_bytes))
    except (OSError, EOFError) as exc:
        logger.exception("events blob %s not gzip-decodable", fight.events_blob_uri)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "events blob corrupt") from exc

    if not events:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable")
    return events


__all__ = ["_load_fight_events"]
