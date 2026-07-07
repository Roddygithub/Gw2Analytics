"""``/api/v1/players`` endpoints.

GET list    : cross-fight player roll-up (one row per account_name).
GET detail  : full profile + per-fight breakdown for one account.

v0.7.0 ships the player-centric view of the dataset. The route
layer is the bridge between the per-fight events blobs (gzipped
JSONL in MinIO) and the cross-fight :class:`PlayerProfileAggregator`:

  1. Load all ``OrmFight`` rows (ordered by ``started_at`` DESC).
  2. For each fight, load the agents table to build
     ``agent_id -> (account_name, name, profession, elite_spec)``.
  3. For each fight, load + decompress the events blob.
  4. Walk the events; for each event, look up the source agent's
     account_name and accumulate the magnitude to the
     ``(account_name, fight_id)`` running total.
  5. Emit one :class:`FightContribution` per
     ``(account_name, fight_id)`` pair and feed the iterable to
     :class:`gw2_analytics.player_profile.PlayerProfileAggregator`.

The per-request cost is O(fights x events) which is acceptable for
v0.7.0 (handful of fights in the local-dev dataset). v0.8.0 will
materialise a ``fight_player_summaries`` table to avoid the
per-request re-computation; the route signature stays unchanged.
"""

from __future__ import annotations

import gzip
import logging
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio.error import S3Error
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.player_profile import (
    FightContribution,
    PlayerProfileAggregator,
)
from gw2_core import BuffRemovalEvent, DamageEvent, EliteSpec, Event, HealingEvent, Profession
from gw2analytics_api.database import get_session
from gw2analytics_api.models import OrmFight, OrmFightAgent
from gw2analytics_api.schemas import (
    PerFightBreakdownRowOut,
    PlayerListRowOut,
    PlayerProfileOut,
    PlayerTimelineOut,
    PlayerTimelinePointOut,
)
from gw2analytics_api.storage import get_events

logger = logging.getLogger(__name__)

# Module-level adapter: same pattern as
# :mod:`gw2analytics_api.routes.fights` -- a single ``TypeAdapter``
# instance for the heterogeneous JSONL line dispatch.
_EVENT_TYPE_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

router = APIRouter(prefix="/api/v1/players", tags=["players"])


# ---------------------------------------------------------------------------
# Per-fight per-account contribution computation
# ---------------------------------------------------------------------------


def _compute_contributions(  # noqa: PLR0912 -- the function is intentionally
    db: Session,
    fights: Sequence[OrmFight],
) -> list[FightContribution]:
    """Walk every fight's events blob and emit one :class:`FightContribution` per
    ``(account_name, fight_id)`` pair.

    The route layer is the single source of truth for the
    source-agent-id -> account_name mapping (via
    :class:`OrmFightAgent`); the aggregator never sees raw event
    data, only the pre-computed per-fight per-account totals.
    """
    if not fights:
        return []

    # Pre-load all agents for the batch in one query so the inner
    # loop avoids the N+1 query problem. ``fight_id IN (...)`` is the
    # canonical batch-load pattern; the SQLAlchemy ``in_`` operator
    # expands the list into the IN clause.
    fight_ids = [f.id for f in fights]
    agents_rows = (
        db.execute(
            select(OrmFightAgent).where(OrmFightAgent.fight_id.in_(fight_ids)),
        )
        .scalars()
        .all()
    )
    # Per-fight agent map: ``fight_id -> {agent_id: (account_name, name, prof_id, elite_id)}``.
    agent_map: dict[str, dict[int, tuple[str, str, int, int]]] = defaultdict(dict)
    for a in agents_rows:
        # Only player agents have an account_name. NPC agents (no
        # account) are filtered out -- the cross-fight join is keyed
        # on account_name so NPCs cannot contribute to a profile.
        if not a.is_player or not a.account_name:
            continue
        agent_map[a.fight_id][a.agent_id] = (
            a.account_name,
            a.name or "",
            int(a.profession),
            int(a.elite_spec),
        )

    # Per-fight per-account accumulator: ``(fight_id, account_name) -> {damage, healing, strip}``.
    per_fight_account: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"damage": 0, "healing": 0, "strip": 0},
    )
    # Identity cache: ``(fight_id, account_name) -> (name, prof_id, elite_id)``.
    # Last-seen name wins (the aggregator applies the same rule);
    # first-seen profession/elite wins (also the aggregator's rule).
    identity_cache: dict[tuple[str, str], tuple[str, int, int]] = {}

    for fight in fights:
        # Local agent map for the inner loop; falls back to empty
        # dict if the fight has no agents (degenerate case).
        # Computed here (BEFORE the blob=None branch) so both
        # branches can iterate the agents: the blob=None branch
        # creates 0-total contributions, the blob-walk branch
        # looks up the source-agent identity per event.
        local_agents = agent_map.get(fight.id, {})
        blob_uri = fight.events_blob_uri
        if blob_uri is None:
            # Pre-Phase-7 fight OR the parser pass yielded zero events.
            # Create 0-total contributions for each player agent in
            # the fight so the cross-fight roll-up includes the
            # player (an analyst expects "I attended fight X" to be
            # visible even if the fight had no events). This aligns
            # the code with the module docstring contract.
            for _agent_id, (ac_name, ac_char_name, prof_id, elite_id) in local_agents.items():
                key = (fight.id, ac_name)
                per_fight_account.setdefault(
                    key,
                    {"damage": 0, "healing": 0, "strip": 0},
                )
                if key not in identity_cache:
                    identity_cache[key] = (ac_char_name, prof_id, elite_id)
            continue
        try:
            gz_bytes = get_events(blob_uri)
        except S3Error:
            logger.warning(
                "events blob %s missing in MinIO for fight %s; skipping",
                blob_uri,
                fight.id,
            )
            continue
        try:
            jsonl = gzip.decompress(gz_bytes)
        except OSError:
            logger.exception(
                "events blob %s not gzip-decodable for fight %s; skipping",
                blob_uri,
                fight.id,
            )
            continue
        for line in jsonl.splitlines():
            if not line:
                continue
            event = _EVENT_TYPE_ADAPTER.validate_json(line)
            # Source-side attribution: the event's source_agent_id
            # must map to a player with an account_name. NPC-only
            # fights (no player agents) silently yield no
            # contributions for this fight.
            identity = local_agents.get(event.source_agent_id)
            if identity is None:
                continue
            account_name, name, prof_id, elite_id = identity
            key = (fight.id, account_name)
            # First-seen profession/elite anchor; last-seen name.
            if key not in identity_cache:
                identity_cache[key] = (name, prof_id, elite_id)
            else:
                # Update the char-name; the profession/elite pair
                # stays anchored to the first-seen values.
                _, prev_prof, prev_elite = identity_cache[key]
                identity_cache[key] = (name, prev_prof, prev_elite)
            # Accumulate the per-kind magnitude.
            if isinstance(event, DamageEvent):
                per_fight_account[key]["damage"] += event.damage
            elif isinstance(event, HealingEvent):
                per_fight_account[key]["healing"] += event.healing
            elif isinstance(event, BuffRemovalEvent):
                per_fight_account[key]["strip"] += event.buff_removal

    # Materialise one :class:`FightContribution` per
    # ``(fight_id, account_name)`` pair. The aggregator expects
    # ``profession`` / ``elite`` as :class:`Profession` /
    # :class:`EliteSpec` enums (not raw ints); the route converts
    # via the IntEnum constructor (``Profession(1)`` is a valid
    # round-trip per the canonical IntEnum contract).
    contributions: list[FightContribution] = []
    for (fight_id, account_name), totals in per_fight_account.items():
        name, prof_id, elite_id = identity_cache[(fight_id, account_name)]
        contributions.append(
            FightContribution(
                fight_id=fight_id,
                account_name=account_name,
                name=name,
                profession=Profession(prof_id),
                elite=EliteSpec(elite_id),
                total_damage=totals["damage"],
                total_healing=totals["healing"],
                total_buff_removal=totals["strip"],
            ),
        )
    return contributions


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PlayerListRowOut])
def list_players(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),  # noqa: B008
) -> list[PlayerListRowOut]:
    """Return up to ``limit`` players (skipping the first ``offset``).

    The route computes the cross-fight roll-up over ALL fights
    (not just the paginated window -- the offset/limit apply to
    the final player list, not the underlying fight set), then
    applies the offset/limit to the sorted result. This keeps the
    response stable across page boundaries: a player who was
    page-1 row 5 last request is page-1 row 5 this request (the
    cross-fight roll-up is deterministic).
    """
    fights = (
        db.execute(
            select(OrmFight)
            .order_by(OrmFight.started_at.desc())
            .options(selectinload(OrmFight.agents)),
        )
        .scalars()
        .all()
    )
    contributions = _compute_contributions(db, fights)
    profiles = PlayerProfileAggregator().aggregate(contributions)
    page = profiles[offset : offset + limit]
    return [
        PlayerListRowOut(
            account_name=p.account_name,
            name=p.name,
            profession=_profession_label(p.profession),
            elite_spec=_elite_label(p.elite),
            fights_attended=p.fights_attended,
            total_damage=p.total_damage,
            total_healing=p.total_healing,
            total_buff_removal=p.total_buff_removal,
        )
        for p in page
    ]


@router.get("/{account_name:path}/timeline", response_model=PlayerTimelineOut)
def get_player_timeline(
    account_name: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),  # noqa: B008
) -> PlayerTimelineOut:
    """Return the per-fight historical timeline for one account.

    v0.8.0 of the API: the analyst-facing timeline chart on the
    profile page. Reuses :func:`_compute_contributions` (the same
    inner loop the list + detail endpoints use) so the route
    joins + decompresses the events blobs once per request and
    paginates in-memory.

    Sort order is **recency-first** (``started_at DESC``, with
    ``fight_id ASC`` as the tiebreaker for fights that share a
    timestamp) -- the analyst scans a per-account trend, so the
    most recent fight lands in the top-left slot of the chart.
    The tiebreaker is the canonical deterministic-ordering
    contract from the cross-fight roll-up.

    ``limit`` is clamped to ``[1, 100]``; ``offset`` is clamped
    to ``[0, inf)``. Out-of-range values raise ``422`` via
    FastAPI's ``Query`` validation (BEFORE the handler runs,
    so the route never sees a bad value).

    The route raises ``404 Not Found`` when no agent in any
    fight carries the requested ``account_name`` -- mirrors the
    detail endpoint's contract.

    Declaration order matters
    -------------------------
    This route MUST be declared BEFORE
    ``get_player`` (the catch-all ``{account_name:path}`` route).
    FastAPI matches routes in declaration order; if the catch-all
    is declared first, ``/{account_name:path}`` would greedily
    match ``/TestAccount.1234/timeline`` with
    ``account_name="TestAccount.1234/timeline"`` and return 404
    before the timeline route ever fires. The current declaration
    order (list + timeline + detail) is the canonical
    "more-specific-first" pattern.

    Performance note
    ----------------
    v0.8.0 of the route does the per-fight roll-up in-memory on
    every request (consistent with the v0.7.0 list + detail
    routes). v0.8.0+ will materialise a ``fight_player_summaries``
    table to avoid the per-request re-computation; the route
    signature stays unchanged.
    """
    fights = (
        db.execute(
            select(OrmFight)
            .order_by(OrmFight.started_at.desc())
            .options(selectinload(OrmFight.agents)),
        )
        .scalars()
        .all()
    )
    contributions = _compute_contributions(db, fights)
    own_contributions = [c for c in contributions if c.account_name == account_name]
    if not own_contributions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    fight_id_to_started: dict[str, Any] = {f.id: f.started_at for f in fights}
    # Recency-first: started_at DESC (datetime direct compare
    # preserves microsecond precision; ``.timestamp()`` would
    # coerce to float), with ``fight_id ASC`` as the canonical
    # deterministic-ordering tiebreaker for fights that share
    # a started_at. The ``.get(fight_id, fight_id)`` fallback
    # is a defensive guard: ``own_contributions`` is computed
    # from the same fights list, so the lookup SHOULD always
    # hit, but the fallback mirrors the detail route's style
    # and prevents a KeyError on any future schema drift.
    sorted_contributions = sorted(
        own_contributions,
        key=lambda c: (
            fight_id_to_started.get(c.fight_id, c.fight_id),
            c.fight_id,
        ),
        reverse=True,
    )
    page = sorted_contributions[offset : offset + limit]
    return PlayerTimelineOut(
        account_name=account_name,
        total=len(own_contributions),
        limit=limit,
        offset=offset,
        points=[
            PlayerTimelinePointOut(
                fight_id=c.fight_id,
                started_at=fight_id_to_started[c.fight_id],
                total_damage=c.total_damage,
                total_healing=c.total_healing,
                total_buff_removal=c.total_buff_removal,
            )
            for c in page
        ],
    )


@router.get("/{account_name:path}", response_model=PlayerProfileOut)
def get_player(
    account_name: str,
    db: Session = Depends(get_session),  # noqa: B008
) -> PlayerProfileOut:
    """Return the full profile + per-fight breakdown for one account.

    ``account_name`` is the URL-decoded arcdps account name (e.g.
    ``:account.1234``). The ``:path`` converter lets the value
    contain ``/`` characters that would otherwise terminate the
    path match; FastAPI decodes the URL-encoded form before
    handing the string to the handler. The route raises
    ``404 Not Found`` when no agent in any fight carries the
    requested ``account_name``.

    The per-fight breakdown is built by filtering the
    cross-fight roll-up to ``account_name`` and emitting one
    :class:`PerFightBreakdownRowOut` per attended fight, sorted
    by ``started_at`` DESC.
    """
    fights = (
        db.execute(
            select(OrmFight)
            .order_by(OrmFight.started_at.desc())
            .options(selectinload(OrmFight.agents)),
        )
        .scalars()
        .all()
    )
    contributions = _compute_contributions(db, fights)
    # Filter to the requested account BEFORE feeding to the
    # aggregator so the per-fight breakdown is scoped to the
    # single account.
    own_contributions = [c for c in contributions if c.account_name == account_name]
    if not own_contributions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    profiles = PlayerProfileAggregator().aggregate(own_contributions)
    profile = profiles[0]

    # Build the per-fight breakdown: one row per attended fight,
    # ordered by started_at DESC. The route does its own ordering
    # because the aggregator emits ``attended_fight_ids`` sorted
    # ascending by fight_id (the deterministic-ordering contract),
    # but the API surface prefers recency-first (analyst UX).
    fight_id_to_started: dict[str, Any] = {f.id: f.started_at for f in fights}
    breakdown = sorted(
        own_contributions,
        key=lambda c: fight_id_to_started.get(c.fight_id, c.fight_id),
        reverse=True,
    )
    return PlayerProfileOut(
        account_name=profile.account_name,
        name=profile.name,
        profession=_profession_label(profile.profession),
        elite_spec=_elite_label(profile.elite),
        fights_attended=profile.fights_attended,
        total_damage=profile.total_damage,
        total_healing=profile.total_healing,
        total_buff_removal=profile.total_buff_removal,
        attended_fight_ids=profile.attended_fight_ids,
        per_fight_breakdown=[
            PerFightBreakdownRowOut(
                fight_id=c.fight_id,
                started_at=fight_id_to_started[c.fight_id],
                total_damage=c.total_damage,
                total_healing=c.total_healing,
                total_buff_removal=c.total_buff_removal,
            )
            for c in breakdown
        ],
    )


# ---------------------------------------------------------------------------
# Stringification helpers
# ---------------------------------------------------------------------------


def _profession_label(profession: Profession) -> str:
    """Map the :class:`Profession` enum to its wire-format string label.

    Mirrors the :func:`gw2analytics_api.routes.fights._to_fight_out`
    contract exactly: ``UNKNOWN`` for the sentinel zero value,
    ``PROF(<id>)`` for everything else. The ``profession.value``
    access is the canonical IntEnum -> int round-trip.
    """
    v = profession.value if isinstance(profession, Profession) else int(profession)
    return "UNKNOWN" if v == 0 else f"PROF({v})"


def _elite_label(elite: EliteSpec) -> str:
    """Map the :class:`EliteSpec` enum to its wire-format string label.

    Mirrors :func:`_profession_label`: ``BASE`` for the sentinel
    zero value, ``ELITE(<id>)`` for everything else.
    """
    v = elite.value if isinstance(elite, EliteSpec) else int(elite)
    return "BASE" if v == 0 else f"ELITE({v})"
