"""/api/v1/fights`` endpoints.

GET list : paginated metadata list of all fights the API has parsed.
GET detail: a single fight with its embedded agents.
GET events: aggregated damage + time-bucketed roll-ups for one fight.
"""

from __future__ import annotations

import gzip
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio.error import S3Error
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.event_window import EventWindowAggregator
from gw2_analytics.target_buff_removal import TargetBuffRemovalAggregator
from gw2_analytics.target_dps import TargetDpsAggregator
from gw2_analytics.target_healing import TargetHealingAggregator
from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent
from gw2analytics_api.database import get_session
from gw2analytics_api.models import OrmFight
from gw2analytics_api.schemas import (
    AgentOut,
    EventBucketOut,
    FightEventsSummaryOut,
    FightOut,
    SkillOut,
    TargetBuffRemovalRowOut,
    TargetDpsRowOut,
    TargetHealingRowOut,
)
from gw2analytics_api.storage import get_events

logger = logging.getLogger(__name__)

# Module-level adapter: ``Event`` is a Pydantic discriminated union
# over ``DamageEvent`` + ``HealingEvent`` (see gw2_core.models). The
# TypeAdapter instance is the canonical entry-point for round-tripping
# a heterogeneous JSONL line; instantiating it at module-load time
# (rather than per-request) is the recommended Pydantic v2 pattern.
_EVENT_TYPE_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

router = APIRouter(prefix="/api/v1/fights", tags=["fights"])


@router.get("", response_model=list[FightOut])
def list_fights(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),  # noqa: B008
) -> list[FightOut]:
    """Return up to ``limit`` fights (skipping the first ``offset``)."""
    rows = (
        db.execute(
            select(OrmFight).order_by(OrmFight.started_at.desc()).limit(limit).offset(offset),
        )
        .scalars()
        .all()
    )
    return [_to_fight_out(f) for f in rows]


@router.get("/{fight_id}", response_model=FightOut)
def get_fight(
    fight_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> FightOut:
    """Return a fight by id (the upload's sha256)."""
    fight = db.execute(
        select(OrmFight)
        .where(OrmFight.id == fight_id)
        .options(selectinload(OrmFight.agents), selectinload(OrmFight.skills)),
    ).scalar_one_or_none()
    if fight is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fight not found")
    return _to_fight_out(fight)


# Default ``window_s`` of 5 seconds matches the standard GW2 toolchain
# bucketing convention (1 s is noisy for DPS graphs; 10 s hides burst
# variance). ``Query(..., ge=1, le=600)`` enforces a 1 second minimum
# (the ``EventWindowAggregator`` invariant) and a 10 minute ceiling
# (sanity bound so a misconfigured client cannot ask for 24h buckets).
_EVENTS_DEFAULT_WINDOW_S: int = 5
_EVENTS_MAX_WINDOW_S: int = 600


@router.get(
    "/{fight_id}/events",
    response_model=FightEventsSummaryOut,
)
def get_fight_events(
    fight_id: str,
    window_s: int = Query(
        _EVENTS_DEFAULT_WINDOW_S,
        ge=1,
        le=_EVENTS_MAX_WINDOW_S,
        description=(
            "Time-bucket size for the roll-up window. Defaults to 5 seconds; "
            "bounded 1 <= window_s <= 600 (10 minutes)."
        ),
    ),
    db: Session = Depends(get_session),  # noqa: B008
) -> FightEventsSummaryOut:
    """Return the aggregated event stream for one fight.

    Phase 7 v1: drained by :meth:`PythonEvtcParser.parse_events`,
    persisted to MinIO at ``events/{fight_id}.jsonl.gz``, and surfaced
    here as a combined ``FightEventsSummaryOut`` so the frontend
    renders the timeline + per-target DPS without two extra round-trips.

    Phase 7 v1 of the API (apps/api 0.3.0): the per-target healing
    roll-up is added as a sibling field of ``target_dps``, completing
    the v2 ``Event`` discriminated union consumption on the HTTP
    surface. The route filters the heterogeneous JSONL stream
    by ``isinstance`` at the call site and invokes
    :class:`gw2_analytics.target_healing.TargetHealingAggregator`
    on the same ``duration_s`` used for the damage roll-up.

    Response codes:

    - ``404 Not Found``: fight id is unknown OR the events blob is
      missing (pre-Phase 7 row OR the parser pass yielded zero events
      after filtering). ``NULL`` ``events_blob_uri`` is the
      ground-truth signal for "no event data available"; we
      deliberately do NOT return ``200 OK`` with empty arrays because
      that would conflate "parser ran, nothing happened" with "data
      unavailable". Re-uploading + reparsing the source ``.zevtc``
      re-populates the blob.
    - ``422 Unprocessable Entity``: ``window_s`` is outside ``[1, 600]``.
      Handled by FastAPI before this handler runs.
    - ``502 Bad Gateway``: events blob is present but corrupt (gzip
      decompression failure or non-JSON payload). The fight row is
      still valid; this is a blob-store consistency issue, not a
      client error.
    """
    fight = db.get(OrmFight, fight_id)
    if fight is None or fight.events_blob_uri is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fight not found")

    try:
        gz_bytes = get_events(fight.events_blob_uri)
    except S3Error:
        logger.warning(
            "events blob %s missing in MinIO for fight %s",
            fight.events_blob_uri,
            fight_id,
        )
        # Treat a missing blob the same as a non-existent blob: 404.
        # This closes the loop if the upload succeeded but the
        # MinIO write ''failed'' silently or was evicted.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable") from None

    try:
        jsonl = gzip.decompress(gz_bytes)
    except OSError as exc:
        logger.exception("events blob %s not gzip-decodable", fight.events_blob_uri)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "events blob corrupt") from exc

    # Phase 7 v2: the JSONL is a heterogeneous stream of damage +
    # healing records. ``TypeAdapter(Event).validate_json(line)`` is
    # the canonical Pydantic v2 entry point for discriminated-union
    # round-trip; it materialises the matching subclass via the
    # ``event_type`` literal carried on every line. ``Event`` is
    # annotated with ``Annotated[..., Field(discriminator="event_type")]``
    # so the dispatch is structural, not a manual ``isinstance``
    # ladder. The adapter instance is module-level so the
    # discriminator validation table is built once at import time.
    events: list[Event] = [
        _EVENT_TYPE_ADAPTER.validate_json(line) for line in jsonl.splitlines() if line
    ]

    if not events:
        # Defensive: the parser writes no empty blobs, but if a 0-byte
        # blob sneaks through (manual PUT, replication drift) we still
        # honour the contract: 404, NOT 200-empty.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "events unavailable")

    duration_s = max(e.time_ms for e in events) / 1000.0
    # ``TargetDpsAggregator`` consumes DamageEvent specifically
    # (its invariant validates sum-of-row-damage == sum-of-event-damage).
    # Filter the heterogeneous stream at the call site so the
    # aggregator signature stays narrow on ``DamageEvent``. Healing-only
    # fights correctly yield an empty target_dps list.
    target_dps = TargetDpsAggregator().aggregate(
        [e for e in events if isinstance(e, DamageEvent)],
        duration_s,
    )
    # ``TargetHealingAggregator`` is the strict parallel of
    # ``TargetDpsAggregator`` (same schema shape with
    # total_healing + hps, same ordering, same invariants). It
    # consumes HealingEvent specifically (sum-of-row-healing ==
    # sum-of-event-healing invariant). Filter at the call site so
    # the aggregator signature stays narrow on ``HealingEvent``;
    # damage-only fights correctly yield an empty target_healing
    # list. Mixed damage + healing fights produce one row per
    # target across both aggregators (independent roll-ups on the
    # same ``duration_s``).
    target_healing = TargetHealingAggregator().aggregate(
        [e for e in events if isinstance(e, HealingEvent)],
        duration_s,
    )
    # Phase 8: third sibling roll-up, strict parallel of the DPS +
    # Healing aggregators. ``TargetBuffRemovalAggregator`` consumes
    # ``BuffRemovalEvent`` specifically (sum-of-row-buff-removal ==
    # sum-of-event-buff-removal invariant). The heterogeneous
    # stream passes through ``isinstance`` at the call site; a
    # single cbtevent that dual-emits a ``HealingEvent`` AND a
    # ``BuffRemovalEvent`` lands in BOTH target_healing AND
    # target_buff_removal -- independent roll-ups on the same
    # ``duration_s``. The pure-strip case (no heal, just a strip)
    # lands in target_buff_removal only.
    target_buff_removal = TargetBuffRemovalAggregator().aggregate(
        [e for e in events if isinstance(e, BuffRemovalEvent)],
        duration_s,
    )
    # ``EventWindowAggregator`` accepts ``Iterable[Event]`` directly and
    # discriminates by isinstance internally (damage_total += damage,
    # healing_total += healing), so the heterogeneous stream passes
    # through unchanged. Phase 8 deliberately does NOT extend
    # ``EventBucketOut`` with a ``buff_removal_total`` field -- the
    # per-bucket window contract is locked.
    event_windows = EventWindowAggregator().aggregate(events, window_s=window_s)

    return FightEventsSummaryOut(
        fight_id=fight_id,
        duration_s=duration_s,
        target_dps=[TargetDpsRowOut.model_validate(r.model_dump()) for r in target_dps],
        target_healing=[TargetHealingRowOut.model_validate(r.model_dump()) for r in target_healing],
        target_buff_removal=[
            TargetBuffRemovalRowOut.model_validate(r.model_dump()) for r in target_buff_removal
        ],
        event_windows=[EventBucketOut.model_validate(b.model_dump()) for b in event_windows],
    )


def _to_fight_out(fight: OrmFight) -> FightOut:
    return FightOut(
        id=fight.id,
        build_version=fight.build_version,
        encounter_id=fight.encounter_id,
        agent_count=fight.agent_count,
        started_at=fight.started_at,
        game_type=fight.game_type,
        agents=[
            AgentOut(
                agent_id=a.agent_id,
                name=a.name,
                profession=("UNKNOWN" if a.profession == 0 else f"PROF({a.profession})"),
                elite_spec=("BASE" if a.elite_spec == 0 else f"ELITE({a.elite_spec})"),
                is_player=a.is_player,
                account_name=a.account_name,
                subgroup=a.subgroup,
            )
            for a in fight.agents
        ],
        skills=[SkillOut(id=s.skill_id, name=s.name) for s in fight.skills],
    )
