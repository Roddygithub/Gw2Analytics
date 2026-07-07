"""``/api/v1/players`` endpoints.

GET list    : cross-fight player roll-up (one row per account_name).
GET detail  : full profile + per-fight breakdown for one account.

v0.7.0 ships the player-centric view of the dataset. The route
layer is the bridge between the per-fight events blobs (gzipped
JSONL in MinIO) and the cross-fight :class:`PlayerProfileAggregator`:

  1. Load all ``OrmFight`` rows (ordered by ``started_at`` DESC).
  2. For each fight, either:
     a. (v0.8.4 fast-path) Read the pre-materialised
        :class:`OrmFightPlayerSummary` rows directly.
     b. (v0.8.4 slow-path, pre-migration fallback) Load the
        agents table to build ``agent_id -> (account_name, name,
        profession, elite_spec)``, load + decompress the events
        blob, walk the events, accumulate the per-(fight, account)
        totals.
  3. Emit one :class:`FightContribution` per
     ``(account_name, fight_id)`` pair and feed the iterable to
     :class:`gw2_analytics.player_profile.PlayerProfileAggregator`.

The v0.8.4 fast-path turns the per-request cost from
O(fights x events) to O(rows) for fights with summary rows. The
slow-path preserves the v0.7.0 behaviour for fights without a
summary row (pre-migration fights, or fights whose re-parse has
not yet landed). Both paths converge on the same output shape so
the downstream aggregator + day-bucketing logic stays unchanged.
"""

from __future__ import annotations

import gzip
import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from gw2analytics_api.models import OrmFight, OrmFightPlayerSummary
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


def _compute_contributions(
    db: Session,
    fights: Sequence[OrmFight],
) -> list[FightContribution]:
    """Emit one :class:`FightContribution` per ``(account_name, fight_id)`` pair.

    v0.8.4: this is now a **hybrid** fast-path / slow-path helper.
    Fast-path (the new default for fights uploaded after the
    v0.8.4 migration): read the pre-materialised
    :class:`OrmFightPlayerSummary` rows directly. Slow-path (the
    fallback for fights without a summary row -- pre-migration
    fights, or fights whose re-parse has not yet landed): walk
    the gzipped events blob, build the per-(fight, account)
    accumulator, and emit the same :class:`FightContribution`
    list. Both paths converge on the same output shape so the
    downstream aggregator + day-bucketing logic stays unchanged.

    Performance: the fast-path is O(rows) per fight (one indexed
    PK lookup per fight_id), the slow-path is O(events) per
    fight. For users with 100+ fights, the fast-path drops the
    5-30s latency to a few milliseconds.

    Re-parse safety: a re-upload of the same SHA replaces the
    fight's events blob AND replaces the per-fight summary rows
    (the services.py helper does a DELETE+INSERT). The
    fast-path therefore sees the new totals on the next request.
    """
    if not fights:
        return []

    fight_ids = [f.id for f in fights]
    fast_path_ids = _fast_path_fight_ids(db, fight_ids)
    contributions: list[FightContribution] = []
    for fight in fights:
        if fight.id in fast_path_ids:
            contributions.extend(_contributions_from_summary(db, fight.id))
        else:
            contributions.extend(_contributions_from_blob_walk(fight))
    return contributions


def _fast_path_fight_ids(db: Session, fight_ids: list[str]) -> set[str]:
    """Return the subset of ``fight_ids`` that have at least one
    :class:`OrmFightPlayerSummary` row.

    One ``EXISTS`` query: ``SELECT DISTINCT fight_id FROM
    fight_player_summaries WHERE fight_id IN (...)``. The query
    is O(N log N) on the PK index, returning at most
    ``len(fight_ids)`` rows. The result set is the fast-path
    input. ``DISTINCT`` is the canonical SQL for a unique set
    over a single PK column (``GROUP BY`` on a PK produces the
    same plan but is non-idiomatic and confuses readers
    expecting aggregate semantics).
    """
    if not fight_ids:
        return set()
    rows = (
        db.execute(
            select(OrmFightPlayerSummary.fight_id)
            .where(OrmFightPlayerSummary.fight_id.in_(fight_ids))
            .distinct(),
        )
        .scalars()
        .all()
    )
    return set(rows)


def _contributions_from_summary(
    db: Session,
    fight_id: str,
) -> list[FightContribution]:
    """Read the pre-materialised :class:`OrmFightPlayerSummary` rows
    for one fight and emit one :class:`FightContribution` per row.

    The summary table denormalises the identity columns (name /
    profession / elite_spec) so the route does NOT need to JOIN
    ``OrmFightAgent`` here -- the same query that reads the
    magnitudes returns the identity. Strict parallel of
    :func:`_contributions_from_blob_walk` so both paths
    produce byte-identical output for the same input.
    """
    rows = (
        db.execute(
            select(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == fight_id),
        )
        .scalars()
        .all()
    )
    return [
        FightContribution(
            fight_id=fight_id,
            account_name=row.account_name,
            name=row.name,
            profession=Profession(row.profession),
            elite=EliteSpec(row.elite_spec),
            total_damage=row.total_damage,
            total_healing=row.total_healing,
            total_buff_removal=row.total_buff_removal,
        )
        for row in rows
    ]


def _contributions_from_blob_walk(  # noqa: PLR0912 -- the function is intentionally branchy (S3 + gzip + per-event dispatch) and the ``fight`` arg is the only state it needs (the pre-loaded agents live on the relationship)
    fight: OrmFight,
) -> list[FightContribution]:
    """Walk one fight's gzipped events blob and emit one
    :class:`FightContribution` per ``(account_name, fight_id)`` pair.

    Slow-path fallback: this is the original v0.7.0 implementation,
    preserved for fights without an :class:`OrmFightPlayerSummary`
    row (pre-migration fights, or fights whose re-parse has not
    yet landed). New code should NOT call this directly -- use
    :func:`_compute_contributions` which dispatches to the
    fast-path when the summary row exists.

    The function intentionally preserves the original behaviour
    so the fallback path produces the same output as the
    fast-path: last-seen name, first-seen profession/elite,
    per-kind magnitudes summed across the events stream. The
    two paths are locked against drift by the e2e tests in
    ``apps/api/tests/test_uploads_e2e.py``.
    """
    # Reuse the route's ``selectinload(OrmFight.agents)`` pre-load
    # instead of re-querying. The fast-path covers the common case
    # (post-migration fights), so the slow-path is only paid for
    # pre-migration fights -- but those still benefit from
    # reusing the in-memory agents list. The v0.7.0 helper did a
    # single batch-load for all fights in the request; the
    # v0.8.4 helper falls back one fight at a time (and now
    # reads the pre-loaded relationship, so the per-fight cost
    # is just the in-memory iteration).
    # Per-fight agent map: ``{agent_id: (account_name, name, prof_id, elite_id)}``.
    agent_map: dict[int, tuple[str, str, int, int]] = {}
    for a in fight.agents:
        if not a.is_player or not a.account_name:
            continue
        agent_map[a.agent_id] = (
            a.account_name,
            a.name or "",
            int(a.profession),
            int(a.elite_spec),
        )

    # 0-total contributions for the blob=None branch (pre-Phase-7
    # fight OR the parser pass yielded zero events). Matches the
    # original v0.7.0 contract: an analyst expects "I attended
    # fight X" to be visible even if the fight had no events.
    # The ``fight.agents`` relationship is pre-loaded by the
    # route's ``selectinload`` so the empty-bucket path is just
    # the in-memory iteration below.
    blob_uri = fight.events_blob_uri
    if blob_uri is None:
        return [
            FightContribution(
                fight_id=fight.id,
                account_name=ac_name,
                name=ac_char_name,
                profession=Profession(prof_id),
                elite=EliteSpec(elite_id),
                total_damage=0,
                total_healing=0,
                total_buff_removal=0,
            )
            for _agent_id, (ac_name, ac_char_name, prof_id, elite_id) in agent_map.items()
        ]
    try:
        gz_bytes = get_events(blob_uri)
    except S3Error:
        logger.warning(
            "events blob %s missing in MinIO for fight %s; skipping",
            blob_uri,
            fight.id,
        )
        return []
    try:
        jsonl = gzip.decompress(gz_bytes)
    except OSError:
        logger.exception(
            "events blob %s not gzip-decodable for fight %s; skipping",
            blob_uri,
            fight.id,
        )
        return []

    # Per-account accumulator: ``account_name -> {damage, healing, strip, name, prof, elite}``.
    per_account: dict[str, dict[str, int | str]] = {}
    for line in jsonl.splitlines():
        if not line:
            continue
        event = _EVENT_TYPE_ADAPTER.validate_json(line)
        identity = agent_map.get(event.source_agent_id)
        if identity is None:
            continue
        account_name, name, prof_id, elite_id = identity
        bucket = per_account.setdefault(
            account_name,
            {
                "damage": 0,
                "healing": 0,
                "strip": 0,
                "name": name,
                "prof": prof_id,
                "elite": elite_id,
                "set": 0,
            },
        )
        if not bucket["set"]:
            bucket["set"] = 1
        else:
            # Last-seen name overwrites the first-seen value.
            bucket["name"] = name
        if isinstance(event, DamageEvent):
            bucket["damage"] = int(bucket["damage"]) + event.damage
        elif isinstance(event, HealingEvent):
            bucket["healing"] = int(bucket["healing"]) + event.healing
        elif isinstance(event, BuffRemovalEvent):
            bucket["strip"] = int(bucket["strip"]) + event.buff_removal

    return [
        FightContribution(
            fight_id=fight.id,
            account_name=account_name,
            name=str(bucket["name"]),
            profession=Profession(int(bucket["prof"])),
            elite=EliteSpec(int(bucket["elite"])),
            total_damage=int(bucket["damage"]),
            total_healing=int(bucket["healing"]),
            total_buff_removal=int(bucket["strip"]),
        )
        for account_name, bucket in per_account.items()
    ]


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
    bucket: Literal["fight", "day"] = Query("fight"),
    # v0.8.9 of the API: ``?tz=Continent/City`` query param
    # selects the TZ for the day-bucketed ``started_at``.
    # Default ``"UTC"`` preserves the v0.8.1 wire contract
    # (backward compat for pre-v0.8.9 consumers). An invalid
    # TZ string raises 422 via the try/except below (the
    # ``zoneinfo.ZoneInfo`` constructor raises
    # ``ZoneInfoNotFoundError`` on an unknown IANA name).
    # The ``bucket=fight`` mode is unaffected -- the TZ only
    # matters for the day-bucketed grouping.
    tz: str = Query("UTC"),
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

    v0.8.4 perf note
    ----------------
    v0.8.0 of the route did the per-fight roll-up in-memory on
    every request. v0.8.4 materialises the per-(fight, account)
    totals in ``OrmFightPlayerSummary`` (populated by the
    background parser) so the fast-path serves the timeline
    from a single indexed PK lookup per fight. The slow-path
    fallback (the original v0.7.0 blob walk) covers pre-migration
    fights transparently. Per-request latency drops from 5-30s
    to a few milliseconds for users with 100+ fights.
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
    # v0.8.9: parse the ``?tz=`` string into a :class:`ZoneInfo`
    # AFTER the 404 check so an unknown account still returns
    # 404 (not 422). ``ZoneInfoNotFoundError`` is the canonical
    # exception for an unknown IANA name; we surface it as 422
    # to match FastAPI's Query-validation convention (invalid
    # query params are 422, not 400). The parsed ``ZoneInfo``
    # threads into both the day-bucketing branch below AND the
    # ``_combine_day_midnight`` helper so the response's
    # ``started_at`` is at midnight in the requested TZ.
    try:
        parsed_tz: ZoneInfo = ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown IANA timezone: {tz!r}",
        ) from exc
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

    # v0.8.1 of the API: ``?bucket=day`` collapses all fights
    # sharing a calendar day into one point whose totals are
    # the SUM of the day's fights. The ``started_at`` of the
    # day-bucketed point is the day's UTC midnight so the chart's
    # X-axis can detect the day-aligned timestamps and render
    # ``MM/DD`` instead of ``MM/DD HH:MM`` (zero extra props).
    # The ``fight_id`` of the day-bucketed point is the
    # most-recent fight_id of the day (the deterministic
    # tiebreaker: the recency-first sort ensures the FIRST
    # encounter in the loop is the most recent, so we capture
    # it via ``setdefault``). The chart's React key is on
    # ``fight_id`` so the day-bucketed points are uniquely
    # keyed.
    #
    # **Timezone assumption.** ``OrmFight.started_at`` is stored
    # as a naive datetime (the parser writes ``datetime.now(UTC)``
    # when the EVTC blob carries no wall clock, so the value is
    # effectively UTC). ``.date()`` on a naive datetime returns
    # the SERVER's local date, NOT UTC -- which means a fight
    # recorded at 23:30 UTC on day N and parsed on a UTC+2 server
    # would land in day N+1's bucket under the v0.8.1 contract.
    # v0.8.9 closes this gap: the ``?tz=`` query param selects
    # the analyst's TZ, the day-bucketed point's ``started_at``
    # is the day-midnight in the requested TZ (serialised as
    # UTC for wire compat -- the JSON still shows
    # ``"2024-01-15T00:00:00Z"``), and the day grouping follows
    # the analyst's TZ rather than the server's local TZ.
    # ``bucket=fight`` is unaffected -- the TZ only matters for
    # the day-bucketed grouping.
    if bucket == "day":
        day_totals: dict[str, dict[str, int]] = defaultdict(
            lambda: {"damage": 0, "healing": 0, "strip": 0},
        )
        day_first_fight: dict[str, str] = {}
        day_first_started: dict[str, Any] = {}
        for c in sorted_contributions:
            started_at = fight_id_to_started[c.fight_id]
            # Mark the naive ``started_at`` as UTC before
            # converting (the v0.8.1 contract: naive = effectively
            # UTC). ``astimezone`` on a naive datetime assumes
            # the SERVER's local TZ, which would silently
            # double-convert and break the TZ contract.
            aware_utc = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
            day_key = aware_utc.astimezone(parsed_tz).date().isoformat()
            day_first_fight.setdefault(day_key, c.fight_id)
            day_first_started.setdefault(day_key, started_at)
            day_totals[day_key]["damage"] += c.total_damage
            day_totals[day_key]["healing"] += c.total_healing
            day_totals[day_key]["strip"] += c.total_buff_removal
        all_points = [
            PlayerTimelinePointOut(
                fight_id=day_first_fight[day_key],
                started_at=_combine_day_midnight(day_first_started[day_key], parsed_tz),
                total_damage=day_totals[day_key]["damage"],
                total_healing=day_totals[day_key]["healing"],
                total_buff_removal=day_totals[day_key]["strip"],
            )
            for day_key in day_totals  # preserves insertion order (most recent first)
        ]
    else:
        all_points = [
            PlayerTimelinePointOut(
                fight_id=c.fight_id,
                started_at=fight_id_to_started[c.fight_id],
                total_damage=c.total_damage,
                total_healing=c.total_healing,
                total_buff_removal=c.total_buff_removal,
            )
            for c in sorted_contributions
        ]

    page = all_points[offset : offset + limit]
    return PlayerTimelineOut(
        account_name=account_name,
        total=len(all_points),
        limit=limit,
        offset=offset,
        bucket=bucket,
        # v0.8.9: echo the parsed TZ on the response so the
        # consumer can see which TZ was applied to the
        # day-bucketed ``started_at``. The original ``tz``
        # string is forwarded (not the ``ZoneInfo``) so the
        # field is serialisable on the JSON wire.
        tz=tz,
        points=page,
    )


def _combine_day_midnight(started_at: Any, tz: ZoneInfo) -> Any:
    """Return the day-midnight in the requested TZ, serialised as UTC for wire compat.

    Pure helper extracted from :func:`get_player_timeline` so the
    day-bucketing branch stays one short loop. The day key is
    the ``started_at.astimezone(tz).date()``; we round to
    ``time.min`` in the requested TZ and then convert back to
    UTC so the wire surface stays UTC-stable (the JSON
    serialises as ``"2024-01-15T00:00:00Z"`` regardless of the
    analyst's TZ). The chart's X-axis can then auto-detect the
    day-aligned UTC timestamps and render ``MM/DD`` without
    needing to know the analyst's TZ.

    v0.8.9: the ``tz`` param is the ``ZoneInfo`` parsed from
    the ``?tz=`` query param (default UTC for backward compat
    with pre-v0.8.9 consumers). The naive ``started_at`` is
    effectively UTC per the v0.8.1 contract (the parser writes
    ``datetime.now(UTC)`` when the EVTC blob carries no wall
    clock), so we mark it as UTC before converting.
    """
    aware_utc = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
    local_midnight = aware_utc.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


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
