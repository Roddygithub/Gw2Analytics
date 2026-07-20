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

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.condi_power_split import KNOWN_CONDI_NAMES
from gw2_analytics.player_profile import (
    FightContribution,
    PlayerProfile,
)
from gw2_analytics.role_detection import detect_role_lite
from gw2_core import BuffRemovalEvent, DamageEvent, EliteSpec, HealingEvent, Profession
from gw2analytics_api._event_dispatch import build_event_iterator
from gw2analytics_api.database import get_session
from gw2analytics_api.models import OrmFight
from gw2analytics_api.route_helpers import format_elite_spec, format_profession
from gw2analytics_api.schemas import (
    PerFightBreakdownRowOut,
    PlayerListRowOut,
    PlayerProfileOut,
    PlayerTimelineOut,
    PlayerTimelinePointOut,
)
from gw2analytics_api.services.player_profiles import (
    aggregate_player_profiles_from_sql,
    find_account_fights_without_summary,
    get_account_contributions_from_sql,
)
from gw2analytics_api.storage import get_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/players", tags=["players"])


# ---------------------------------------------------------------------------
# Per-fight per-account contribution computation
# ---------------------------------------------------------------------------


def _load_merged_contributions(
    db: Session,
    *,
    account_name: str,
) -> tuple[list[FightContribution], dict[str, datetime]]:
    """Load per-account contributions from SQL and merge with the slow-path fallback.

    The SQL fast-path covers post-v0.8.4 fights with pre-materialised
    :class:`OrmFightPlayerSummary` rows. The slow-path covers pre-v0.8.4
    fights via blob-walking. Both paths converge on the same
    ``(FightContribution, started_at)`` tuple shape; the merge step
    sorts the combined result by ``(started_at DESC, fight_id ASC)`` to
    match the routes' recency-first contract.

    At 100% materialised-view coverage, the slow-path is dormant and
    this helper is a single indexed query + a no-op merge.
    """
    pairs = get_account_contributions_from_sql(
        db,
        account_name=account_name,
        limit=10**6,  # unbounded; bounded by account's fight count
        offset=0,
    )
    own_contributions = [c for c, _ in pairs]
    fight_id_to_started: dict[str, datetime] = {c.fight_id: started_at for c, started_at in pairs}

    slow_contributions, slow_started_at = _load_slow_path_contributions(
        db, account_name=account_name
    )
    own_contributions.extend(slow_contributions)
    fight_id_to_started.update(slow_started_at)

    # Re-sort the combined (SQL + slow-path) contributions recency-first.
    # The SQL path is already sorted, but the slow-path rows are appended
    # in their natural order, so a re-sort is required whenever the
    # slow-path is non-empty. Sorting unconditionally is cheap and keeps
    # the contract explicit.
    own_contributions.sort(
        key=lambda c: (fight_id_to_started[c.fight_id], c.fight_id),
        reverse=True,
    )
    return own_contributions, fight_id_to_started


def _load_slow_path_contributions(
    db: Session,
    *,
    account_name: str,
) -> tuple[list[FightContribution], dict[str, datetime]]:
    """Load pre-v0.8.4 contributions for ``account_name`` (slow-path fallback).

    Returns ``(contributions, started_at_map)``:

    - ``contributions``: one :class:`FightContribution` per
      ``(account_name, fight_id)`` pair, filtered to the
      requested account (the blob-walk emits one per account
      that attended the fight, so the filter is required).
    - ``started_at_map``: ``fight_id -> started_at`` so the
      caller can sort the merged (SQL + slow-path) set by
      recency-first.

    At 100% materialised-view coverage (post-v0.8.4 deployments),
    both return values are empty and the helper is a single
    ``NOT EXISTS`` query (O(account_fights) on the
    ``(account_name)`` index of ``fight_agents``) + an empty
    result short-circuit. The blob-walk is dormant.

    When fights ARE missing, the dispatch is one
    ``selectinload(OrmFight.agents + skills)`` round-trip (all
    missing fights in a single query) + one blob-walk per
    missing fight. ``selectinload`` avoids N+1 queries during
    the blob-walk's per-fight agent/skill access.

    Extracted from :func:`get_player_timeline` + :func:`get_player`
    in plan 028 round 2 to remove the ~12 LoC of duplicated
    dispatch code that was identical between the 2 endpoints.
    """
    missing_fight_ids = find_account_fights_without_summary(db, account_name=account_name)
    if not missing_fight_ids:
        return [], {}
    slow_fights: Sequence[OrmFight] = (
        db.execute(
            select(OrmFight)
            .where(OrmFight.id.in_(missing_fight_ids))
            .options(
                selectinload(OrmFight.agents),
                selectinload(OrmFight.skills),
            ),
        )
        .scalars()
        .all()
    )
    contributions: list[FightContribution] = []
    started_at_map: dict[str, datetime] = {}
    for slow_fight in slow_fights:
        for c in _contributions_from_blob_walk(slow_fight):
            if c.account_name != account_name:
                continue
            contributions.append(c)
            started_at_map[c.fight_id] = slow_fight.started_at
    return contributions, started_at_map


@dataclass(slots=True)
class _ContributionBucket:
    """Mutable per-account accumulator for the slow-path blob walk."""

    name: str
    prof: int
    elite: int
    damage: int = 0
    healing: int = 0
    strip: int = 0
    power: int = 0
    condi: int = 0


@dataclass(slots=True)
class _DayTotals:
    """Mutable per-day accumulator for timeline day-bucketing."""

    damage: int = 0
    healing: int = 0
    strip: int = 0


def _contributions_from_blob_walk(  # noqa: PLR0912
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

    # v0.10.5 plan 135: per-fight skill-name map for the
    # condi/power split (skill-name lookup against KNOWN_CONDI_NAMES).
    # The route's ``selectinload(OrmFight.skills)`` pre-loads
    # ``fight.skills`` in the same query as ``fight.agents`` so
    # the dict-comprehension is in-memory (no extra round-trip).
    # Pre-20240501 arcdps has no buff_dmg field; the split is
    # silently 100% power for post-20240501 fights that the
    # v0.10.4 parser cannot surface buff_dmg on. See
    # ``advisor-plans/006a`` for the parser-side fix path.
    skill_name_for_event: dict[int, str | None] = {int(s.skill_id): s.name for s in fight.skills}

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
                # v0.10.3 plan 083: the 0/0/0 bucket (no events
                # blob) maps to UNKNOWN + zero_output tag. The
                # fast-path would also return ``NULL`` for these
                # rows (pre-migration), but the slow-path
                # explicitly tags them so the wire contract is
                # identical between paths.
                detected_role="UNKNOWN",
                detected_tags=["zero_output"],
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
        events = list(build_event_iterator(gz_bytes=gz_bytes))
    except (OSError, EOFError):
        logger.exception(
            "events blob %s not gzip-decodable for fight %s; skipping",
            blob_uri,
            fight.id,
        )
        return []

    # Per-account accumulator: ``account_name -> _ContributionBucket``.
    per_account: dict[str, _ContributionBucket] = {}
    # Local bindings avoid repeated attribute lookups in the hot loop.
    agent_map_get = agent_map.get
    skill_name_get = skill_name_for_event.get
    for event in events:
        identity = agent_map_get(event.source_agent_id)
        if identity is None:
            continue
        account_name, name, prof_id, elite_id = identity
        # First-event / subsequent-event split (clean mirror of
        # services.py::_persist_player_summaries). The explicit
        # ``if account_name in per_account:`` guard is one-line
        # and matches the services-side pattern. ``bucket.name = name``
        # runs on every event so the value is last-seen (the
        # pre-v0.10.5 wire contract).
        if account_name not in per_account:
            per_account[account_name] = _ContributionBucket(
                name=name,
                prof=prof_id,
                elite=elite_id,
            )
        bucket = per_account[account_name]
        bucket.name = name
        # Inline event application to avoid function-call overhead
        # in the hot loop.
        if isinstance(event, DamageEvent):
            bucket.damage += event.damage
            # v0.10.5 plan 135: inline condi/power split per
            # DamageEvent (skill-name lookup). NEW-build fights
            # (buff_dmg not on v2 DamageEvent) default to power;
            # see advisor-plans/006a for parser-side fix.
            skill_name = skill_name_get(event.skill_id)
            if skill_name in KNOWN_CONDI_NAMES:
                bucket.condi += event.damage
            else:
                bucket.power += event.damage
        elif isinstance(event, HealingEvent):
            bucket.healing += event.healing
        elif isinstance(event, BuffRemovalEvent):
            bucket.strip += event.buff_removal

    # v0.10.3 plan 083: the per-account loop also invokes
    # :func:`detect_role_lite` so the slow-path blob walk
    # produces the same role output as the fast-path summary
    # query. The fast-path projects the pre-computed
    # ``detected_role`` / ``detected_tags`` from
    # ``OrmFightPlayerSummary``; the slow-path computes them on
    # the fly here. The 2 paths converge on byte-identical
    # output (the heuristic is deterministic -- same inputs
    # always produce the same output). Pre-migration fights
    # take the slow-path (no summary row exists) so this is
    # also the v0.10.3 backfill path for the ``detected_role``
    # / ``detected_tags`` columns.
    contributions: list[FightContribution] = []
    for account_name, bucket in per_account.items():
        detected_role, detected_tags = detect_role_lite(
            total_damage=bucket.damage,
            total_healing=bucket.healing,
            total_buff_removal=bucket.strip,
            profession_int=bucket.prof,
            elite_spec_int=bucket.elite,
        )
        contributions.append(
            FightContribution(
                fight_id=fight.id,
                account_name=account_name,
                name=bucket.name,
                profession=Profession(bucket.prof),
                elite=EliteSpec(bucket.elite),
                total_damage=bucket.damage,
                total_healing=bucket.healing,
                total_buff_removal=bucket.strip,
                detected_role=detected_role,
                detected_tags=detected_tags,
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
    # v0.9.0: ``?profession=`` query param filters the response
    # to only players whose modal profession matches. The
    # :class:`Profession` enum is an :class:`IntEnum` (the
    # wire format is the integer value), but the URL surface
    # is the enum NAME (e.g. ``?profession=MESMER``) for
    # URL-readability. We accept a raw ``str`` + parse it
    # manually so both the name (case-insensitive) and the
    # integer value are accepted; an unrecognised value
    # surfaces as 422 with a clear error message (matches
    # the existing :func:`get_player_timeline` ``?tz=``
    # custom-422 pattern). The default empty string is
    # treated as "no filter" -- preserves the pre-v0.9.0
    # wire contract (no ``?profession=`` -> all players).
    # The filter is applied AFTER the cross-fight roll-up
    # (so it sees the aggregated modal profession, not the
    # per-fight value) and BEFORE the offset/limit (so
    # pagination is consistent on the filtered set).
    profession: str = Query(
        "",
        description=(
            "Filter to players whose modal profession matches the enum name "
            "(e.g. ?profession=MESMER) or integer value (e.g. ?profession=7). "
            "Default (empty / no param) returns all players."
        ),
    ),
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

    v0.9.0: the optional ``?profession=`` filter is applied
    between the cross-fight roll-up + the offset/limit. An
    invalid name (or integer) surfaces as 422 via the
    :func:`_parse_profession_filter` helper.
    """
    parsed_profession = _parse_profession_filter(profession)
    # v0.10.10 plan 028: SQL-only cross-fight roll-up. Replaces
    # the legacy ``select(OrmFight).all() + _compute_contributions
    # + PlayerProfileAggregator.aggregate()`` path that loaded the
    # entire ``OrmFight`` table + 2 selectinloads per request.
    # At 10k WvW fights with ~50 agents each, the legacy path
    # loaded ~500k ORM objects per request; the SQL path stays
    # bounded by the response size (LIMIT/OFFSET) and the PK
    # index. The post-filter on modal profession is client-side
    # (O(results)) to keep the SQL simple; the filter is on the
    # MODAL profession (per-account aggregate), not on the
    # per-fight profession.
    profiles = aggregate_player_profiles_from_sql(
        db,
        limit=limit,
        offset=offset,
        profession_filter=parsed_profession,
    )
    page = profiles
    # Phase 3 (AI-CONTINUATION-PLAN): derive a cross-fight
    # detected role from the aggregated totals. The same
    # ``detect_role_lite`` weights apply to summed magnitudes,
    # giving a stable per-account primary role for the UI.
    return [
        _profile_to_list_row(p)
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
    # v0.10.10 plan 028: hybrid SQL + slow-path view via
    # ``get_account_contributions_from_sql`` (post-v0.8.4
    # fights) + ``find_account_fights_without_summary`` +
    # ``_contributions_from_blob_walk`` (pre-v0.8.4 fights).
    # The two paths converge on the same ``(FightContribution,
    # started_at)`` tuple shape; the merge step sorts the
    # combined result by ``(started_at DESC, fight_id ASC)`` to
    # match the route's recency-first contract. At 100%
    # materialised-view coverage (post-v0.8.4 deployments), the
    # slow-path is dormant and the SQL path is the full
    # contribution set.
    bare_account_name = account_name.lstrip(":")
    own_contributions, fight_id_to_started = _load_merged_contributions(
        db, account_name=bare_account_name
    )

    if not own_contributions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    # The response echoes the canonical bare account_name, not
    # any colon-prefixed form the caller may have supplied.
    account_name = bare_account_name
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
    # Recency-first: the SQL path is sorted by
    # ``(started_at DESC, fight_id ASC)``; the slow-path merge
    # step above re-sorts the combined set on the same key. The
    # ``fight_id_to_started`` dict is built once + reused for
    # the day-bucketing + breakdown views below.
    sorted_contributions = own_contributions

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
        day_totals: dict[str, _DayTotals] = defaultdict(_DayTotals)
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
            totals = day_totals[day_key]
            totals.damage += c.total_damage
            totals.healing += c.total_healing
            totals.strip += c.total_buff_removal
        all_points = [
            PlayerTimelinePointOut(
                fight_id=day_first_fight[day_key],
                started_at=_combine_day_midnight(day_first_started[day_key], parsed_tz),
                total_damage=day_totals[day_key].damage,
                total_healing=day_totals[day_key].healing,
                total_buff_removal=day_totals[day_key].strip,
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

    ``account_name`` is the URL-decoded canonical account name (e.g.
    ``account.1234``). The ``:path`` converter lets the value
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
    # v0.10.10 plan 028: hybrid SQL + slow-path per-account
    # per-fight contributions. The SQL path returns
    # post-v0.8.4 fights; the slow-path (one ``NOT EXISTS``
    # query + a selectinload of the missing ``OrmFight`` rows
    # + ``_contributions_from_blob_walk`` per fight) covers
    # pre-v0.8.4 fights. Both paths converge on the same
    # ``(FightContribution, started_at)`` tuple shape; the
    # merge step builds the ``fight_id_to_started`` dict from
    # both sources.
    bare_account_name = account_name.lstrip(":")
    own_contributions, fight_id_to_started = _load_merged_contributions(
        db, account_name=bare_account_name
    )

    if not own_contributions:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "player not found")
    # The response echoes the canonical bare account_name, not
    # any colon-prefixed form the caller may have supplied.
    account_name = bare_account_name
    # The cross-fight profile: first contribution's identity.
    # ``_load_merged_contributions`` already returns the
    # contributions sorted recency-first, so the first row is
    # the most recent. The magnitudes + fights_attended are
    # summed from ALL contributions to match the
    # ``PlayerProfileAggregator`` contract.
    first = own_contributions[0]
    profile = PlayerProfile(
        account_name=account_name,
        name=first.name,
        profession=first.profession,
        elite=first.elite,
        fights_attended=len(own_contributions),
        total_damage=sum(c.total_damage for c in own_contributions),
        total_healing=sum(c.total_healing for c in own_contributions),
        total_buff_removal=sum(c.total_buff_removal for c in own_contributions),
        attended_fight_ids=sorted(c.fight_id for c in own_contributions),
    )
    # Phase 3 (AI-CONTINUATION-PLAN): cross-fight detected role
    # from the aggregated per-account totals.
    detected_role, detected_tags = detect_role_lite(
        total_damage=profile.total_damage,
        total_healing=profile.total_healing,
        total_buff_removal=profile.total_buff_removal,
        profession_int=int(profile.profession),
        elite_spec_int=int(profile.elite),
    )

    # Per-fight breakdown: recency-first. The
    # ``own_contributions`` list is already sorted by the merge
    # step above; pass it through unchanged.
    breakdown = own_contributions
    return PlayerProfileOut(
        account_name=profile.account_name,
        name=profile.name,
        profession=_profession_label(profile.profession),
        elite_spec=_elite_label(profile.elite),
        fights_attended=profile.fights_attended,
        total_damage=profile.total_damage,
        total_healing=profile.total_healing,
        total_buff_removal=profile.total_buff_removal,
        detected_role=detected_role,
        detected_tags=detected_tags,
        attended_fight_ids=profile.attended_fight_ids,
        per_fight_breakdown=[
            PerFightBreakdownRowOut(
                fight_id=c.fight_id,
                started_at=fight_id_to_started[c.fight_id],
                total_damage=c.total_damage,
                total_healing=c.total_healing,
                total_buff_removal=c.total_buff_removal,
                # v0.10.3 plan 083: project the per-fight role
                # detection from the ``FightContribution`` (which
                # itself is populated either from the materialised
                # ``OrmFightPlayerSummary`` row in the fast-path
                # or from the on-the-fly ``detect_role_lite`` call
                # in the slow-path). ``None`` is theoretically
                # unreachable (the slow-path always produces a
                # value) but the type is ``Optional`` for
                # forward-compat with pre-migration rows.
                detected_role=c.detected_role,
                detected_tags=c.detected_tags,
            )
            for c in breakdown
        ],
    )


# ---------------------------------------------------------------------------
# Stringification helpers
# ---------------------------------------------------------------------------


def _parse_profession_filter(value: str) -> Profession | None:
    """Parse the ``?profession=`` query param into a :class:`Profession` enum.

    The :class:`Profession` enum is an :class:`IntEnum` (the wire
    format is the integer value), but the URL surface accepts
    BOTH the enum NAME (e.g. ``"MESMER"``, case-insensitive for
    URL-tolerance) AND the integer value (e.g. ``"7"``) for
    canonical-wire-compat. An empty string is the "no filter"
    sentinel (the query param default). An unrecognised value
    surfaces as 422 with a clear error message -- matches the
    existing :func:`get_player_timeline` ``?tz=`` custom-422
    pattern (the canonical FastAPI query-param validation
    contract).

    Lookup order
    ------------
    1. Name lookup (``Profession["MESMER"]``) -- the URL
       surface is the enum name for readability.
    2. Integer parse (``int(value)`` -> ``Profession(int)``) --
       the wire format is the integer value.
    3. Both fail -> 422 with the rejected value in the detail.

    The name lookup is tried FIRST so the URL surface is the
    canonical "human-readable" form; the integer fallback is
    the wire-compat shim. ``Profession.UNKNOWN`` (value 0) is
    NOT in the cross-fight roll-up (the aggregator's contract
    silently drops players with no profession), so the name
    ``"UNKNOWN"`` would match zero rows -- that's expected and
    is NOT treated as a 422.
    """
    if not value:
        return None
    # Name lookup (case-insensitive). ``Profession["MESMER"]``
    # works because IntEnum preserves its member names as
    # attributes; the bracketed access is the canonical
    # name -> member lookup. ``KeyError`` signals an unknown
    # name -> fall through to the integer parse.
    try:
        return Profession[value.upper()]
    except KeyError:
        pass
    # Integer value lookup (wire-compat). ``int(value)`` raises
    # ``ValueError`` for non-numeric strings; the exception
    # message includes the rejected value so the 422 detail
    # names the bad value.
    try:
        return Profession(int(value))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown profession: {value!r} (expected name like 'MESMER' or integer 0-9)",
        ) from exc


def _profile_to_list_row(p: PlayerProfile) -> PlayerListRowOut:
    """Build a :class:`PlayerListRowOut` with cross-fight role detection."""
    detected_role, detected_tags = detect_role_lite(
        total_damage=p.total_damage,
        total_healing=p.total_healing,
        total_buff_removal=p.total_buff_removal,
        profession_int=int(p.profession),
        elite_spec_int=int(p.elite),
    )
    return PlayerListRowOut(
        account_name=p.account_name,
        name=p.name,
        profession=_profession_label(p.profession),
        elite_spec=_elite_label(p.elite),
        fights_attended=p.fights_attended,
        total_damage=p.total_damage,
        total_healing=p.total_healing,
        total_buff_removal=p.total_buff_removal,
        detected_role=detected_role,
        detected_tags=detected_tags,
    )


def _profession_label(profession: Profession) -> str:
    """Wire-format label. Delegates to :func:`format_profession`."""
    return format_profession(profession)


def _elite_label(elite: EliteSpec) -> str:
    """Wire-format label. Delegates to :func:`format_elite_spec`."""
    return format_elite_spec(elite)
