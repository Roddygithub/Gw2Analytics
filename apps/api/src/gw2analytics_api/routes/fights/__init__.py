"""``/api/v1/fights`` sub-pack: FastAPI router + extracted cache primitive.

The package's main entry-point is the FastAPI :data:`router`
(registered via ``app.include_router(router)`` in
:mod:`gw2analytics_api.main`); the 7 endpoint handlers listed below
hang off it. The :mod:`.blob_cache` submodule is the canvas for the
A2 god-module refactor: PR 1 extracted the singleflight + per-URI
latch + LRU cache primitive out of this module into a dedicated
submodule so its contract can be tested hermetically (without the
TestClient stack).

Submodules
==========

- :mod:`gw2analytics_api.routes.fights.blob_cache` -- the canonical
  per-URI blob-cache primitive (``lru_cache(maxsize=8)`` + per-URI
  ``threading.Lock`` + ``concurrent.futures.Future`` singleflight).
  Independent of FastAPI; the only consumer in this package is
  :func:`_load_fight_events`. Direct submodule imports are
  encouraged for consumers (the apps/api tests +
  ``apps/api/tests/conftest.py`` autouse fixture chain) -- the
  underscore-prefix names there are deliberately internal to the
  cache primitive and are NOT re-exported via this package's
  namespace (per PEP 8 underscore-prefix = module-private).

Endpoints (registered via ``app.include_router(router)`` in main)
=================================================================

- :func:`list_fights` -- paginated metadata list of all fights the
  API has parsed.
- :func:`get_fight` -- a single fight with its embedded agents.
- :func:`get_fight_events` -- aggregated damage + healing + time-bucketed
  roll-ups for one fight.
- :func:`get_fight_squads` -- per-subgroup roll-up for one fight.
- :func:`get_fight_skills` -- per-skill hit count + damage / heal /
  strip totals.
- :func:`get_fight_timeline` -- per-fight temporal view (3-series
  ``M:SS`` relative time).
- :func:`get_fight_player_timeline` -- per-player timeline overlay.
"""

from __future__ import annotations

import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.event_window import EventWindowAggregator
from gw2_analytics.per_fight_timeline import PerFightTimelineAggregator
from gw2_analytics.per_player_timeline import PerPlayerTimelineAggregator
from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent
from gw2analytics_api._event_dispatch import build_event_iterator
from gw2analytics_api.database import get_session
from gw2analytics_api.models import OrmFight, OrmFightAgent
from gw2analytics_api.route_helpers import format_elite_spec, format_profession
from gw2analytics_api.routes.fights.aggregators import (
    _aggregate_per_target_rollup,
    aggregate_skill_usage,
    aggregate_squad_rollup,
)
from gw2analytics_api.routes.fights.blob_cache import _cached_get_events
from gw2analytics_api.routes.fights.blob_loader import _load_fight_events
from gw2analytics_api.routes.fights.mappers import (
    agent_id_to_name,
    agent_id_to_subgroup,
    skill_id_to_name,
)
from gw2analytics_api.schemas import (
    AgentOut,
    EventBucketOut,
    FightEventsSummaryOut,
    FightOut,
    FightSkillsOut,
    FightSquadsOut,
    PerFightTimelineOut,
    PerFightTimelinePointOut,
    PerPlayerTimelineOut,
    PerPlayerTimelineSeriesOut,
    SkillOut,
    SkillUsageRowOut,
    SquadRollupRowOut,
    TargetBuffRemovalRowOut,
    TargetDpsRowOut,
    TargetHealingRowOut,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/fights", tags=["fights"])


# Module-level single-source-of-truth for window-S bounds.
# The per-fight timeline (``GET /fights/{id}/timeline``) + the
# per-bucketed events roll-up (``GET /fights/{id}/events``) share the
# same default (5 seconds -- the standard GW2 toolchain bucketing
# convention) and the same bounds (1 second minimum -- the
# ``EventWindowAggregator`` + ``PerFightTimelineAggregator`` invariant;
# 600 seconds ceiling -- sanity bound so a misconfigured client
# cannot ask for 24h buckets). The pre-v0.9.38 design declared
# the constants twice with identical values
# (``_TIMELINE_DEFAULT_WINDOW_S`` + ``_EVENTS_DEFAULT_WINDOW_S``);
# this is the canonical single-source. Plan 117 closes the DRY
# gap so a future maintainer who changes the default / bounds
# only edits one site.
_PER_FIGHT_DEFAULT_WINDOW_S: int = 5
_PER_FIGHT_MAX_WINDOW_S: int = 600


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


# ---------------------------------------------------------------------------
# v0.8.9: per-fight timeline (damage + healing + buff-removal over time)
#
# Declaration order matters: this route is declared BEFORE the
# ``/{fight_id}`` catch-all ``get_fight`` below as a defensive guard
# against any future refactor that widens the catch-all to
# ``/{fight_id:path}``. With the path-style converter, FastAPI would
# match ``/api/v1/fights/{id}/timeline`` against the catch-all with
# ``fight_id="{id}/timeline"`` and return 404 before this route ever
# fires. The current per-segment ``{fight_id}`` matching means the
# order does not matter in practice, but the defensive ordering
# pins the contract so a future refactor doesn't silently break
# the timeline endpoint. Same pattern as the v0.8.0 player
# timeline route's documentation.
# ---------------------------------------------------------------------------


# Default ``window_s`` of 5 seconds matches the per-fight events
# endpoint's contract (1 s is noisy for DPS graphs; 10 s hides
# burst variance). ``Query(..., ge=1, le=600)`` enforces a 1
# second minimum (the ``PerFightTimelineAggregator`` invariant)
# and a 10 minute ceiling (sanity bound so a misconfigured client
# cannot ask for 24h buckets). The bounds are defined at module
# level (``_PER_FIGHT_DEFAULT_WINDOW_S`` +
# ``_PER_FIGHT_MAX_WINDOW_S``) so the per-fight timeline + the
# per-bucketed events roll-up share a single source of truth.


@router.get(
    "/{fight_id}/timeline",
    response_model=PerFightTimelineOut,
)
def get_fight_timeline(
    fight_id: str,
    window_s: int = Query(
        _PER_FIGHT_DEFAULT_WINDOW_S,
        ge=1,
        le=_PER_FIGHT_MAX_WINDOW_S,
        description=(
            "Time-bucket size for the per-fight timeline roll-up. "
            "Defaults to 5 seconds; bounded 1 <= window_s <= 600 "
            "(10 minutes)."
        ),
    ),
    db: Session = Depends(get_session),  # noqa: B008
) -> PerFightTimelineOut:
    """Return the per-fight timeline (damage + healing + buff-removal over time) for one fight.

    v0.8.9 ships this as a SEPARATE endpoint (not folded into
    :func:`get_fight_events`) so the per-fight drill-down page
    can fetch it in parallel with the per-target trio + squads +
    skills via ``Promise.allSettled``; folding it into the
    existing ``FightEventsSummaryOut`` would force the page to
    refetch the full event blob even when only the per-fight
    timeline is requested. The route reuses
    :func:`_load_fight_events` (the same shared helper the
    per-target trio + squads + skills endpoints use) and invokes
    :class:`gw2_analytics.per_fight_timeline.PerFightTimelineAggregator`
    on the parsed events.

    The aggregator's ``agents`` + ``duration_s`` parameters are
    accepted for signature parity with the per-target trio +
    squads + skills aggregators but NOT consumed by the
    per-bucket aggregation (the per-bucket skeleton is
    target-agnostic + duration-agnostic). The route passes
    ``agents=[]`` + the computed ``duration_s`` (derived from
    ``max(event.time_ms) / 1000.0`` to match the contract on
    :func:`get_fight_events`).

    Response codes match :func:`get_fight_events` exactly:

    - ``404 Not Found``: fight id is unknown OR the events
      blob is missing (pre-Phase 7 row OR the parser pass
      yielded zero events after filtering). ``NULL``
      ``events_blob_uri`` is the ground-truth signal for "no
      event data available"; we deliberately do NOT return
      ``200 OK`` with empty arrays because that would
      conflate "parser ran, nothing happened" with "data
      unavailable".
    - ``422 Unprocessable Entity``: ``window_s`` is outside
      ``[1, 600]``. Handled by FastAPI before this handler
      runs.
    - ``502 Bad Gateway``: events blob is present but
      corrupt (gzip decompression failure or non-JSON
      payload). The fight row is still valid; this is a
      blob-store consistency issue, not a client error.
    """
    # Shared helper handles the blob load + decompress + event
    # split + 404 / 502 error contract (the per-target trio +
    # squads + skills endpoints share the same pattern).
    events = _load_fight_events(db, fight_id)

    # ``duration_s`` is computed natively from
    # ``max(event.time_ms) / 1000.0`` to match the contract on
    # :func:`get_fight_events` (the V1.3 EVTC header does not
    # carry a wall-clock duration scalar). The aggregator
    # accepts it for signature parity but does not consume
    # it -- the per-bucket bucket count is derived from the
    # events stream directly.
    duration_s = max(e.time_ms for e in events) / 1000.0
    rows = PerFightTimelineAggregator().aggregate(
        events,
        [],
        duration_s,
        window_s=window_s,
    )

    return PerFightTimelineOut(
        fight_id=fight_id,
        window_s=window_s,
        duration_s=duration_s,
        points=[PerFightTimelinePointOut.model_validate(r.model_dump()) for r in rows],
    )


# ---------------------------------------------------------------------------
# v0.10.3 plan 083 Feature 3A: per-player timeline (source-side
# attribution, 1 series per player agent).
#
# Declaration order matters: same defensive guard as
# :func:`get_fight_timeline` -- declared BEFORE the
# ``/{fight_id}`` catch-all ``get_fight`` below so a future
# refactor that widens the catch-all to ``/{fight_id:path}`` does
# not silently break the per-player timeline endpoint.
# -----------------------------------------------------------------------------


@router.get(
    "/{fight_id}/timeline/players",
    response_model=PerPlayerTimelineOut,
)
def get_fight_player_timeline(
    fight_id: str,
    window_s: int = Query(
        _PER_FIGHT_DEFAULT_WINDOW_S,
        ge=1,
        le=_PER_FIGHT_MAX_WINDOW_S,
        description=(
            "Time-bucket size for the per-player timeline roll-up. "
            "Defaults to 5 seconds; bounded 1 <= window_s <= 600 "
            "(10 minutes). Same contract as the aggregated "
            "``/timeline`` endpoint."
        ),
    ),
    db: Session = Depends(get_session),  # noqa: B008
) -> PerPlayerTimelineOut:
    """Return the per-player timeline (1 series per player, damage + healing + strip over time).

    v0.10.3 plan 083 Feature 3A ships this as a SEPARATE endpoint
    (not folded into :class:`PerFightTimelineOut`) for the same
    reason the squads + skills endpoints are separate: a single
    bound response would force the page to refetch the full
    event blob even when only the per-player view is requested.
    The route reuses :func:`_load_fight_events` (the same shared
    helper the per-target trio + squads + skills + aggregated
    timeline endpoints use), loads the fight's ``OrmFightAgent``
    rows to build the source-side attribution map, and invokes
    :class:`gw2_analytics.per_player_timeline.PerPlayerTimelineAggregator`
    on the parsed events + the agent iterable.

    The aggregator applies the second-layer
    ``account_name``-non-empty filter (the per-source-side
    contract in :func:`apps.api.services._persist_player_summaries`).
    NPC agents are silently dropped (they have no
    ``account_name`` registered in the arcdps account-name
    stream); events whose ``source_agent_id`` maps to an NPC
    are silently dropped at the aggregator's source-side
    attribution step.

    Response codes match :func:`get_fight_timeline` exactly:

    - ``404 Not Found``: fight id is unknown OR the events
      blob is missing (pre-Phase 7 row OR the parser pass
      yielded zero events after filtering).
    - ``422 Unprocessable Entity``: ``window_s`` is outside
      ``[1, 600]``. Handled by FastAPI before this handler
      runs.
    - ``502 Bad Gateway``: events blob is present but
      corrupt (gzip decompression failure or non-JSON
      payload).

    A fight with zero player agents (a 0-player NPC-only
    fight) returns ``200 OK`` with ``series: []`` -- NOT
    ``404 Not Found``. The ``/timeline`` endpoint raises
    ``404`` on a 0-event fight (the blob is present but the
    parser yielded no events); a 0-player fight is a different
    state (the blob is present, the parser yielded events,
    but every event is NPC-sourced so the source-side
    attribution has nothing to attribute to). The 2 endpoints'
    empty-state contracts diverge by design.
    """
    # Shared helper handles the blob load + decompress + event
    # split + 404 / 502 error contract (the per-target trio +
    # squads + skills + aggregated timeline endpoints share
    # the same pattern). The aggregator accepts the events
    # list as an ``Iterable[Event]`` (we re-iterate twice
    # internally -- once for the bucket attribution + once
    # for the invariant check -- so the list materialisation
    # here is a one-time cost).
    events = _load_fight_events(db, fight_id)

    # Build the per-fight agent iterable (passed to the
    # aggregator which applies the is_player + account_name
    # filters). The aggregator reads 4 attributes via
    # ``getattr`` (agent_id / account_name / is_player /
    # name) so the SQLAlchemy ORM instances are a drop-in
    # match. A single small query on the fight's agent
    # table (typically 5-50 rows); a small N+1 guard is
    # not warranted at this row count.
    agents: list[OrmFightAgent] = list(
        db.execute(
            select(OrmFightAgent).where(OrmFightAgent.fight_id == fight_id),
        )
        .scalars()
        .all()
    )

    duration_s = max(e.time_ms for e in events) / 1000.0
    series = PerPlayerTimelineAggregator().aggregate(
        events,
        agents,
        window_s=window_s,
    )

    return PerPlayerTimelineOut(
        fight_id=fight_id,
        window_s=window_s,
        duration_s=duration_s,
        # ``model_validate`` + ``model_dump`` mirrors the
        # per-target trio + squads + skills + aggregated
        # timeline endpoints' wire-validation pattern (see
        # :func:`get_fight_events` + :func:`get_fight_skills`).
        # The aggregator's field names match the wire
        # schema's field names 1:1, so the round-trip is
        # mechanical -- no manual field mapping.
        series=[PerPlayerTimelineSeriesOut.model_validate(s.model_dump()) for s in series],
    )


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


@router.get(
    "/{fight_id}/events",
    response_model=FightEventsSummaryOut,
)
def get_fight_events(
    fight_id: str,
    window_s: int = Query(
        _PER_FIGHT_DEFAULT_WINDOW_S,
        ge=1,
        le=_PER_FIGHT_MAX_WINDOW_S,
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
    # Phase 7 v2: the JSONL is a heterogeneous stream of damage +
    # healing + buff-removal records. ``_load_fight_events`` is the
    # shared helper that handles the blob load + decompress + event
    # split + 404 / 502 error contract; the per-target trio (DPS +
    # Healing + BuffRemoval) and the per-bucket ``EventWindowAggregator``
    # all consume the returned events list. The TypeAdapter
    # validation is structural (``Annotated[..., Field(
    # discriminator="event_type")]``) so the dispatch is automatic.
    events = _load_fight_events(db, fight_id)

    # v0.8.3 of the API: build the agent_id -> name map for
    # player-name denormalisation. A single small query on the
    # fight's agent table (typically 5-50 rows); the shared
    # ``_load_fight_events`` helper only loads the fight row, so
    # this IS a dedicated fetch (a single small one). The map is
    # passed to all three per-target aggregators below so a target
    # that appears in the damage roll-up AND the healing roll-up
    # resolves to the SAME name on both rows (consistency
    # invariant: same agent_id == same name across all three
    # roll-ups). ``OrmFightAgent.name`` is a non-null string in
    # practice but the schema permits ``None``; the type uses
    # ``str | None`` so the aggregator's ``.get(target)`` returns
    # ``None`` for NPCs without a registered arcdps char-name
    # (the explicit-``None`` and missing-key cases collapse to the
    # same sentinel on the row, which the frontend falls back to
    # the raw ``target_agent_id`` for).
    agent_id_to_name_map = agent_id_to_name(db, fight_id)

    duration_s = max(e.time_ms for e in events) / 1000.0
    # Plan 117: the 3 per-target roll-ups (DPS + Healing + BuffRemoval)
    # share an isomorphic ``(isinstance filter, aggregator call,
    # name_map=...)`` shape. The single ``_aggregate_per_target_rollup``
    # helper centralises that shape and dispatches to the right
    # aggregator + output-row-type via ``event_cls``. The schema
    # validation step (per-rollup ``TargetXRowOut.model_validate``) +
    # the 100-row cap (v0.10.2 hotfix followup #12) stay in the
    # route handler because the right ``RowOut`` subclass + the
    # cap policy are wire-format / payload-bound concerns, not
    # aggregation concerns.
    target_dps_rows = _aggregate_per_target_rollup(
        events,
        agent_id_to_name_map,
        duration_s,
        DamageEvent,
    )
    target_healing_rows = _aggregate_per_target_rollup(
        events,
        agent_id_to_name_map,
        duration_s,
        HealingEvent,
    )
    target_buff_removal_rows = _aggregate_per_target_rollup(
        events,
        agent_id_to_name_map,
        duration_s,
        BuffRemovalEvent,
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
        # v0.10.2 hotfix followup #12: cap the per-target roll-up lists
        # at 100 rows to bound JSON serialization. The v0.10.3 parser
        # fix (source_agent_id misread) can produce hundreds of thousands
        # of unique garbage agent IDs, which the per-target aggregators
        # happily group by, exploding the response size and causing
        # the connection to drop (HTTP 000 / Next.js "fetch failed"
        # timeout). The 100-row cap preserves the top-N analyst signal
        # (the per-target roll-ups are ordered by damage / healing /
        # strip descending) while keeping the payload bounded.
        # ``event_windows`` is NOT capped -- it groups by time bucket,
        # which is bounded by the fight duration, so the data volume
        # is naturally bounded.
        target_dps=[TargetDpsRowOut.model_validate(r.model_dump()) for r in target_dps_rows[:100]],
        target_healing=[
            TargetHealingRowOut.model_validate(r.model_dump()) for r in target_healing_rows[:100]
        ],
        target_buff_removal=[
            TargetBuffRemovalRowOut.model_validate(r.model_dump())
            for r in target_buff_removal_rows[:100]
        ],
        event_windows=[EventBucketOut.model_validate(b.model_dump()) for b in event_windows],
    )


# ---------------------------------------------------------------------------
# v0.7.0: per-subgroup (squad) and per-skill roll-ups
# ---------------------------------------------------------------------------


@router.get(
    "/{fight_id}/squads",
    response_model=FightSquadsOut,
)
def get_fight_squads(
    fight_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> FightSquadsOut:
    """Return the per-subgroup (squad) roll-up for one fight.

    v0.7.0 ships this as a SEPARATE endpoint (not folded into
    :func:`get_fight_events`) so the per-fight drill-down page can
    fetch it in parallel with the per-target roll-ups via
    ``Promise.all``; folding it into the existing payload would
    force the page to refetch the full event blob even when only
    the squad view is requested.

    The route decompresses the same events blob the per-target
    trio uses, splits by ``isinstance`` at the call site, loads
    the per-fight agents to build the ``agent_id -> subgroup``
    map, and invokes
    :class:`gw2_analytics.squad_rollup.SquadRollupAggregator` on
    the same ``duration_s``.

    Response codes match :func:`get_fight_events` exactly
    (``404`` for missing fight / blob / corrupt blob).
    """
    # Shared helper handles the blob load + decompress + event
    # split + 404 / 502 error contract (the per-target trio +
    # EventWindowAggregator share the same pattern in
    # :func:`get_fight_events`).
    events = _load_fight_events(db, fight_id)

    # Build the agent_id -> subgroup map. ``OrmFightAgent`` is
    # pre-loaded by the route caller (not in this function) to
    # avoid the N+1 query problem -- but a single fight's agent
    # table is small (typically 5-50 rows), so the lazy load here
    # is acceptable. An empty subgroup is a valid value that
    # surfaces in the empty-string bucket.
    agent_id_to_subgroup_map = agent_id_to_subgroup(db, fight_id)

    duration_s = max(e.time_ms for e in events) / 1000.0
    squad_rows = aggregate_squad_rollup(events, agent_id_to_subgroup_map, duration_s)

    return FightSquadsOut(
        fight_id=fight_id,
        duration_s=duration_s,
        squads=[
            SquadRollupRowOut.model_validate(
                {
                    "subgroup": r.subgroup,
                    "total_damage": r.total_damage,
                    "total_healing": r.total_healing,
                    "total_buff_removal": r.total_buff_removal,
                    "dps": r.dps,
                    "hps": r.hps,
                    "bps": r.bps,
                },
            )
            for r in squad_rows
        ],
    )


@router.get(
    "/{fight_id}/skills",
    response_model=FightSkillsOut,
)
def get_fight_skills(
    fight_id: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> FightSkillsOut:
    """Return the per-skill roll-up for one fight.

    v0.7.0 ships this as a SEPARATE endpoint (not folded into
    :func:`get_fight_events`); same rationale as
    :func:`get_fight_squads`. The route loads the per-fight
    ``OrmFightSkill`` rows to build the ``skill_id -> skill_name``
    map and invokes
    :class:`gw2_analytics.skill_usage.SkillUsageAggregator` on the
    split event streams. No ``duration_s`` is passed (the
    skill-usage aggregator does not compute per-second rates; see
    the module docstring for the rationale).
    """
    # Shared helper handles the blob load + decompress + event
    # split + 404 / 502 error contract (same pattern as the
    # per-target trio + EventWindowAggregator in
    # :func:`get_fight_events`).
    events = _load_fight_events(db, fight_id)

    # Build the skill_id -> skill_name map. An empty skill name
    # is a valid value (the parser surfaces it for unknown
    # skills); the aggregator renders it as ``skill_name=""``.
    skill_id_to_name_map = skill_id_to_name(db, fight_id)

    skill_rows = aggregate_skill_usage(events, skill_id_to_name_map)

    return FightSkillsOut(
        fight_id=fight_id,
        # v0.10.2 hotfix followup #12: see get_fight_events for the
        # rationale. The per-skill roll-up groups by skill_id, which
        # the v0.10.3 parser bug can also produce garbage values for,
        # leading to the same response explosion. The 100-row cap
        # preserves the top-N signal (ordered by total_damage
        # descending) while bounding the payload.
        skills=[SkillUsageRowOut.model_validate(r.model_dump()) for r in skill_rows[:100]],
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
                profession=format_profession(a.profession),
                elite_spec=format_elite_spec(a.elite_spec),
                is_player=a.is_player,
                account_name=a.account_name,
                subgroup=a.subgroup,
            )
            for a in fight.agents
        ],
        skills=[SkillOut(id=s.skill_id, name=s.name) for s in fight.skills],
    )
