"""Player summary materialization per fight.

Phase 2.2: uses :class:`PlayerRepository` for the DELETE + INSERT
of ``OrmFightPlayerSummary`` rows instead of raw ``db.execute(delete(...))``
and ``db.add(...)`` calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from gw2_analytics.buff_state import TRACKED_BUFFS, BuffStateTracker
from gw2_analytics.condi_power_split import KNOWN_CONDI_NAMES
from gw2_analytics.role_detection import detect_role_lite
from gw2_core import (
    BoonApplyEvent,
    BuffApplyEvent,
    BuffRemovalEvent,
    CCEvent,
    DamageEvent,
    Event,
    HealingEvent,
)
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerBoon,
)
from gw2analytics_api.repositories import PlayerRepository
from gw2analytics_api.services.fight_persistence import _sanitize_name

# Skill IDs that correspond to the tracked positive boons. Any
# BoonApplyEvent remove event whose skill_id is NOT in this set is
# treated as a condition cleanse (this is a heuristic: non-boon
# remove events can also be other untracked status effects).
_TRACKED_BOON_IDS: frozenset[int] = frozenset(TRACKED_BUFFS.values())

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SummaryBucket:
    """Mutable per-account summary totals."""

    damage: int = 0
    healing: int = 0
    strip: int = 0
    power: int = 0
    condi: int = 0
    boon_strips: int = 0
    condition_cleanses: int = 0
    cc_applied: int = 0
    name: str = ""
    prof: int = 0
    elite: int = 0
    agent_id: int = 0


def _make_bucket(agent: OrmFightAgent) -> _SummaryBucket:
    """Return a fresh zero-totals summary bucket for ``agent``."""
    return _SummaryBucket(
        name=_sanitize_name(agent.name),
        prof=int(agent.profession),
        elite=int(agent.elite_spec),
        agent_id=int(agent.agent_id),
    )


def _build_account_agent_ids(
    agents: list[OrmFightAgent],
) -> dict[str, list[int]]:
    """Return a mapping from account_name to the list of agent_ids observed."""
    account_to_ids: dict[str, list[int]] = {}
    for agent in agents:
        if agent.is_player and agent.account_name:
            account_to_ids.setdefault(agent.account_name, []).append(int(agent.agent_id))
    return account_to_ids


def _boon_fields_for_account(
    account_name: str,
    bucket: _SummaryBucket,
    account_to_agent_ids: dict[str, list[int]],
    uptimes_by_agent: dict[int, dict[str, float]],
    outgoing_by_agent: dict[int, dict[str, int]],
) -> dict[str, float | int | None]:
    """Aggregate boon uptimes and outgoing generation for one account."""
    agent_ids = account_to_agent_ids.get(account_name, [bucket.agent_id])
    merged_uptime: dict[str, float] = {}
    merged_outgoing: dict[str, int] = {}
    for aid in agent_ids:
        for name, pct in uptimes_by_agent.get(aid, {}).items():
            merged_uptime[name] = merged_uptime.get(name, 0.0) + pct
        for name, total in outgoing_by_agent.get(aid, {}).items():
            merged_outgoing[name] = merged_outgoing.get(name, 0) + total
    if len(agent_ids) > 1:
        for name in merged_uptime:
            merged_uptime[name] /= len(agent_ids)
    return {
        "might_uptime": merged_uptime.get("might"),
        "fury_uptime": merged_uptime.get("fury"),
        "quickness_uptime": merged_uptime.get("quickness"),
        "alacrity_uptime": merged_uptime.get("alacrity"),
        "protection_uptime": merged_uptime.get("protection"),
        "regeneration_uptime": merged_uptime.get("regeneration"),
        "vigor_uptime": merged_uptime.get("vigor"),
        "aegis_uptime": merged_uptime.get("aegis"),
        "stability_uptime": merged_uptime.get("stability"),
        "swiftness_uptime": merged_uptime.get("swiftness"),
        "resistance_uptime": merged_uptime.get("resistance"),
        "resolution_uptime": merged_uptime.get("resolution"),
        "superspeed_uptime": merged_uptime.get("superspeed"),
        "stealth_uptime": merged_uptime.get("stealth"),
        "outgoing_might": merged_outgoing.get("might"),
        "outgoing_fury": merged_outgoing.get("fury"),
        "outgoing_quickness": merged_outgoing.get("quickness"),
        "outgoing_alacrity": merged_outgoing.get("alacrity"),
        "outgoing_protection": merged_outgoing.get("protection"),
        "outgoing_regeneration": merged_outgoing.get("regeneration"),
        "outgoing_vigor": merged_outgoing.get("vigor"),
        "outgoing_aegis": merged_outgoing.get("aegis"),
        "outgoing_stability": merged_outgoing.get("stability"),
        "outgoing_swiftness": merged_outgoing.get("swiftness"),
        "outgoing_resistance": merged_outgoing.get("resistance"),
        "outgoing_resolution": merged_outgoing.get("resolution"),
        "outgoing_superspeed": merged_outgoing.get("superspeed"),
        "outgoing_stealth": merged_outgoing.get("stealth"),
    }


def _compute_account_roles(
    *,
    healing: int,
    total_squad_healing: int,
    boons_out_rate: float,
    strips: int,
    cleanses: int,
    cc_applied: int,
) -> list[str]:
    """Determine role badges for a single account."""
    roles_out: list[str] = []
    if total_squad_healing > 0 and (healing / total_squad_healing) > 0.10:
        roles_out.append("Heal")
    if boons_out_rate > 1.0:
        roles_out.append("Support")
    if strips > 5:
        roles_out.append("Strip")
    if cleanses > 10:
        roles_out.append("Cleanser")
    if cc_applied > 3:
        roles_out.append("CC")
    if not roles_out:
        roles_out.append("DPS")
    return roles_out


def _process_events_to_buckets(  # noqa: PLR0912
    events: list[Event],
    source_map: dict[int, OrmFightAgent],
    skill_name_map: dict[int, str | None],
    buff_tracker: BuffStateTracker,
) -> dict[str, _SummaryBucket]:
    """Walk the event list and accumulate per-account summary buckets.

    Returns a mapping from ``account_name`` to
    :class:`_SummaryBucket` with damage/healing/strip/CC
    totals aggregated over every event in the fight.
    """
    per_account: dict[str, _SummaryBucket] = {}
    _known_condi_names = KNOWN_CONDI_NAMES
    _skill_name_map_get = skill_name_map.get

    if not events:
        for agent in source_map.values():
            account = agent.account_name
            assert account is not None  # noqa: S101
            if account not in per_account:
                per_account[account] = _make_bucket(agent)
        return per_account

    for event in events:
        if isinstance(event, (BoonApplyEvent, BuffApplyEvent)):
            buff_tracker.process(event)
            for _agent_id in (event.source_agent_id, event.target_agent_id):
                evt_agent = source_map.get(_agent_id)
                if evt_agent is not None:
                    account = evt_agent.account_name
                    assert account is not None  # noqa: S101
                    if account not in per_account:
                        per_account[account] = _make_bucket(evt_agent)
            if isinstance(event, BoonApplyEvent) and event.kind != "apply":
                source = source_map.get(event.source_agent_id)
                if source is not None:
                    account = source.account_name
                    assert account is not None  # noqa: S101
                    bucket = per_account.setdefault(account, _make_bucket(source))
                    if event.skill_id in _TRACKED_BOON_IDS:
                        bucket.boon_strips += event.stacks
                    else:
                        bucket.condition_cleanses += event.stacks
            continue
        evt_agent = source_map.get(event.source_agent_id)
        if evt_agent is None:
            continue
        assert evt_agent.account_name is not None  # noqa: S101
        account = evt_agent.account_name
        if account not in per_account:
            per_account[account] = _make_bucket(evt_agent)
        bucket = per_account[account]

        if isinstance(event, DamageEvent):
            bucket.damage += event.damage
            skill_name = _skill_name_map_get(event.skill_id)
            if skill_name in _known_condi_names:
                bucket.condi += event.damage
            else:
                bucket.power += event.damage
        elif isinstance(event, HealingEvent):
            bucket.healing += event.healing
        elif isinstance(event, BuffRemovalEvent):
            bucket.strip += event.buff_removal
            bucket.boon_strips += event.buff_removal
        elif isinstance(event, CCEvent):
            bucket.cc_applied += 1

    return per_account


def _write_summary_and_boon_rows(
    db: Session,
    orm_fight: OrmFight,
    per_account: dict[str, _SummaryBucket],
    account_to_agent_ids: dict[str, list[int]],
    buff_tracker: BuffStateTracker,
    duration_s: float,
    source_map: dict[int, OrmFightAgent],
) -> None:
    """Delete old summary/boon rows and write new ones from the buckets.

    Phase 3.1: dual-write boons to the normalized
    :class:`OrmFightPlayerBoon` table in addition to the
    28 inline boon columns on :class:`OrmFightPlayerSummary`.
    """
    uptimes_by_agent = buff_tracker.compute_all_uptimes(duration_s)
    outgoing_by_agent = buff_tracker.compute_all_outgoing(duration_s)

    boons_out_by_account: dict[str, float] = {}
    for account, agent_ids in account_to_agent_ids.items():
        total_stacks = 0
        for aid in agent_ids:
            agent_out = outgoing_by_agent.get(aid, {})
            total_stacks += sum(agent_out.values())
        dur = max(duration_s, 1.0)
        boons_out_by_account[account] = total_stacks / dur

    total_squad_healing = sum(b.healing for b in per_account.values())

    if not per_account and source_map:
        logger.warning(
            "fight %s: %d player agent(s) with account_name but 0 summary "
            "rows; events likely have wrong source_agent_id (parser skill "
            "table misreading cascade -- see v0.10.3 parser fix)",
            orm_fight.id,
            len(source_map),
        )

    repo = PlayerRepository(db)
    repo.delete_boons_for_fight(orm_fight.id)

    summary_rows: list[dict[str, object]] = []

    for account_name, bucket in per_account.items():
        sanitized_account = _sanitize_name(account_name)
        if not sanitized_account:
            logger.info(
                "fight %s: skipping summary row for account_name=%r "
                "(sanitized to empty string after NUL strip; "
                "degenerate input -- see v0.10.3 parser fix for "
                "all-NUL account_name detection)",
                orm_fight.id,
                account_name,
            )
            continue
        detected_role, detected_tags = detect_role_lite(
            total_damage=bucket.damage,
            total_healing=bucket.healing,
            total_buff_removal=bucket.strip,
            profession_int=bucket.prof,
            elite_spec_int=bucket.elite,
        )
        boon_kwargs = _boon_fields_for_account(
            account_name,
            bucket,
            account_to_agent_ids,
            uptimes_by_agent,
            outgoing_by_agent,
        )
        summary_rows.append(
            {
                "fight_id": orm_fight.id,
                "account_name": sanitized_account,
                "name": bucket.name,
                "profession": bucket.prof,
                "elite_spec": bucket.elite,
                "total_damage": bucket.damage,
                "total_healing": bucket.healing,
                "total_buff_removal": bucket.strip,
                "detected_role": detected_role,
                "detected_tags": detected_tags,
                "power_damage": bucket.power,
                "condi_damage": bucket.condi,
                "boon_strips": bucket.boon_strips,
                "condition_cleanses": bucket.condition_cleanses,
                "roles": _compute_account_roles(
                    healing=bucket.healing,
                    total_squad_healing=total_squad_healing,
                    boons_out_rate=boons_out_by_account.get(account_name, 0.0),
                    strips=bucket.boon_strips,
                    cleanses=bucket.condition_cleanses,
                    cc_applied=bucket.cc_applied,
                ),
                **boon_kwargs,
            },
        )
        # Phase 3.1: dual-write boons to the normalized table.
        for boon_name in (
            "might",
            "fury",
            "quickness",
            "alacrity",
            "protection",
            "regeneration",
            "vigor",
            "aegis",
            "stability",
            "swiftness",
            "resistance",
            "resolution",
            "superspeed",
            "stealth",
        ):
            uptime = boon_kwargs.get(f"{boon_name}_uptime")
            outgoing = boon_kwargs.get(f"outgoing_{boon_name}")
            if uptime is not None or outgoing is not None:
                repo.add_boon(
                    OrmFightPlayerBoon(
                        fight_id=orm_fight.id,
                        account_name=sanitized_account,
                        boon_name=boon_name,
                        uptime=uptime,
                        outgoing=outgoing,
                    ),
                )

    repo.upsert_summaries(summary_rows)


def _persist_player_summaries(
    db: Session,
    orm_fight: OrmFight,
    events: list[Event],
) -> None:
    """Materialize per-account player summaries for a fight.

    Phase 2.2: uses :class:`PlayerRepository` for the DELETE + INSERT
    cycle instead of raw ``db.execute(delete(...))`` and ``db.add(...)``.
    Phase 5.1: event accumulation extracted into
    :func:`_process_events_to_buckets` and row writing into
    :func:`_write_summary_and_boon_rows`.
    """
    source_map: dict[int, OrmFightAgent] = {
        a.agent_id: a for a in orm_fight.agents if a.is_player and a.account_name
    }
    if not source_map:
        return

    account_to_agent_ids = _build_account_agent_ids(
        [a for a in orm_fight.agents if a.is_player and a.account_name],
    )
    skill_name_map: dict[int, str | None] = {int(s.skill_id): s.name for s in orm_fight.skills}
    buff_tracker = BuffStateTracker()

    per_account = _process_events_to_buckets(
        events,
        source_map,
        skill_name_map,
        buff_tracker,
    )

    if events:
        last_time_ms = max((e.time_ms for e in events), default=0)
        duration_s = last_time_ms / 1000.0
    else:
        duration_s = 0.0

    _write_summary_and_boon_rows(
        db,
        orm_fight,
        per_account,
        account_to_agent_ids,
        buff_tracker,
        duration_s,
        source_map,
    )
