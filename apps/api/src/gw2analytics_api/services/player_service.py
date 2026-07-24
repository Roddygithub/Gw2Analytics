"""Player service: per-fight per-account contribution computation.

Phase 2.3 extraction from :mod:`gw2analytics_api.routes.players`.
Contains all player business logic: merged contribution loading,
slow-path blob walking, and day-bucketing helpers. Routes call
these functions instead of duplicating the logic.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo

from minio.error import S3Error
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from gw2_analytics.condi_power_split import KNOWN_CONDI_NAMES
from gw2_analytics.player_profile import FightContribution
from gw2_analytics.role_detection import detect_role_lite
from gw2_core import BuffRemovalEvent, DamageEvent, EliteSpec, HealingEvent, Profession
from gw2analytics_api._event_dispatch import build_event_iterator
from gw2analytics_api.models import OrmFight
from gw2analytics_api.services.player_profiles import (
    find_account_fights_without_summary,
    get_account_contributions_from_sql,
)
from gw2analytics_api.storage import get_events

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal accumulation dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ContributionBucket:
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
class DayTotals:
    """Mutable per-day accumulator for timeline day-bucketing."""

    damage: int = 0
    healing: int = 0
    strip: int = 0


# ---------------------------------------------------------------------------
# Contribution loading (SQL fast-path + slow-path fallback)
# ---------------------------------------------------------------------------


def load_merged_contributions(
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
        limit=10**6,
        offset=0,
    )
    own_contributions = [c for c, _ in pairs]
    fight_id_to_started: dict[str, datetime] = {c.fight_id: started_at for c, started_at in pairs}

    slow_contributions, slow_started_at = load_slow_path_contributions(
        db,
        account_name=account_name,
    )
    own_contributions.extend(slow_contributions)
    fight_id_to_started.update(slow_started_at)

    own_contributions.sort(
        key=lambda c: (fight_id_to_started[c.fight_id], c.fight_id),
        reverse=True,
    )
    return own_contributions, fight_id_to_started


def load_slow_path_contributions(
    db: Session,
    *,
    account_name: str,
) -> tuple[list[FightContribution], dict[str, datetime]]:
    """Load pre-v0.8.4 contributions for ``account_name`` (slow-path fallback).

    Returns ``(contributions, started_at_map)``:

    - ``contributions``: one :class:`FightContribution` per
      ``(account_name, fight_id)`` pair, filtered to the
      requested account.
    - ``started_at_map``: ``fight_id -> started_at`` so the
      caller can sort the merged (SQL + slow-path) set by
      recency-first.

    At 100% materialised-view coverage (post-v0.8.4 deployments),
    both return values are empty and the blob-walk is dormant.
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
        for c in contributions_from_blob_walk(slow_fight):
            if c.account_name != account_name:
                continue
            contributions.append(c)
            started_at_map[c.fight_id] = slow_fight.started_at
    return contributions, started_at_map


def contributions_from_blob_walk(  # noqa: PLR0912
    fight: OrmFight,
) -> list[FightContribution]:
    """Walk one fight's gzipped events blob and emit one
    :class:`FightContribution` per ``(account_name, fight_id)`` pair.

    Slow-path fallback: preserved for fights without an
    :class:`OrmFightPlayerSummary` row (pre-migration fights, or fights
    whose re-parse has not yet landed).

    The function intentionally preserves the original behaviour
    so the fallback path produces the same output as the
    fast-path: last-seen name, first-seen profession/elite,
    per-kind magnitudes summed across the events stream.
    """
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

    skill_name_for_event: dict[int, str | None] = {int(s.skill_id): s.name for s in fight.skills}

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

    per_account: dict[str, ContributionBucket] = {}
    agent_map_get = agent_map.get
    skill_name_get = skill_name_for_event.get
    for event in events:
        identity = agent_map_get(event.source_agent_id)
        if identity is None:
            continue
        account_name, name, prof_id, elite_id = identity
        if account_name not in per_account:
            per_account[account_name] = ContributionBucket(
                name=name,
                prof=prof_id,
                elite=elite_id,
            )
        bucket = per_account[account_name]
        bucket.name = name
        if isinstance(event, DamageEvent):
            bucket.damage += event.damage
            skill_name = skill_name_get(event.skill_id)
            if skill_name in KNOWN_CONDI_NAMES:
                bucket.condi += event.damage
            else:
                bucket.power += event.damage
        elif isinstance(event, HealingEvent):
            bucket.healing += event.healing
        elif isinstance(event, BuffRemovalEvent):
            bucket.strip += event.buff_removal

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
# Day-bucketing helper
# ---------------------------------------------------------------------------


def combine_day_midnight(started_at: datetime, tz: tzinfo) -> datetime:
    """Return the day-midnight in the requested TZ, serialised as UTC for wire compat.

    The day key is the ``started_at.astimezone(tz).date()``; we round to
    ``time.min`` in the requested TZ and then convert back to
    UTC so the wire surface stays UTC-stable (the JSON
    serialises as ``\"2024-01-15T00:00:00Z\"`` regardless of the
    analyst's TZ).

    The naive ``started_at`` is effectively UTC per the v0.8.1 contract,
    so we mark it as UTC before converting.
    """
    aware_utc = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
    local_midnight = aware_utc.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


__all__ = [
    "ContributionBucket",
    "DayTotals",
    "combine_day_midnight",
    "contributions_from_blob_walk",
    "load_merged_contributions",
    "load_slow_path_contributions",
]
