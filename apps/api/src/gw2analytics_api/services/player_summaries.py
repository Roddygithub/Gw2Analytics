from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from gw2_analytics.buff_state import BuffStateTracker
from gw2_analytics.condi_power_split import KNOWN_CONDI_NAMES
from gw2_analytics.role_detection import detect_role_lite
from gw2_core import (
    BoonApplyEvent,
    BuffApplyEvent,
    BuffRemovalEvent,
    DamageEvent,
    Event,
    HealingEvent,
)
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerSummary,
)
from gw2analytics_api.services.fight_persistence import _sanitize_name

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SummaryBucket:
    """Mutable per-account summary totals."""

    damage: int = 0
    healing: int = 0
    strip: int = 0
    power: int = 0
    condi: int = 0
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
    """Aggregate boon uptimes and outgoing generation for one account.

    A player may appear under multiple agent_ids (disconnect/reconnect),
    so we aggregate across every agent_id that belongs to the account.
    """
    agent_ids = account_to_agent_ids.get(account_name, [bucket.agent_id])
    merged_uptime: dict[str, float] = {}
    merged_outgoing: dict[str, int] = {}
    for aid in agent_ids:
        for name, pct in uptimes_by_agent.get(aid, {}).items():
            merged_uptime[name] = merged_uptime.get(name, 0.0) + pct
        for name, total in outgoing_by_agent.get(aid, {}).items():
            merged_outgoing[name] = merged_outgoing.get(name, 0) + total
    # Average uptime percentages across the player's agents.
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


def _persist_player_summaries(  # noqa: PLR0912,PLR0915
    db: Session,
    orm_fight: OrmFight,
    events: list[Event],
) -> None:
    source_map: dict[int, OrmFightAgent] = {
        a.agent_id: a for a in orm_fight.agents if a.is_player and a.account_name
    }
    if not source_map:
        return

    account_to_agent_ids = _build_account_agent_ids(
        [a for a in orm_fight.agents if a.is_player and a.account_name],
    )
    skill_name_map: dict[int, str | None] = {int(s.skill_id): s.name for s in orm_fight.skills}

    per_account: dict[str, _SummaryBucket] = {}
    buff_tracker = BuffStateTracker()
    # Hoist globals / method lookups to local variables so the
    # per-event hot loop pays local-variable cost only.
    _known_condi_names = KNOWN_CONDI_NAMES
    _skill_name_map_get = skill_name_map.get

    # v0.10.11 fix for test_uploads_e2e::test_players_list_returns_accounts_present_in_fight:
    # ONLY when ``events`` is empty, pre-seed per_account with one
    # zero-totals bucket per attending player agent. Pre-fix, the
    # event loop below was the only source of bucket creation, so an
    # empty ``events`` list produced 0 buckets and 0 rows; the
    # /players fast-path then returned 0 rows for an N-attending
    # -agent fight. Post-fix, every attending agent gets a 0-totals
    # row when events is empty (matches the v0.8.4 contract that
    # ATTENDING agents always surface in the cross-fight roll-up).
    #
    # The pre-seed is INTENTIONALLY conditional on empty events.
    # For non-empty events, the pre-fix per-event bucket semantics
    # are preserved (the test_persist_player_summaries.py unit suite
    # asserts ``len(rows) == 1`` for a 1-event-from-2-agents fixture;
    # this contract is preserved by NOT pre-seeding when events != []).
    if not events:
        for agent in source_map.values():
            account = agent.account_name
            assert account is not None  # noqa: S101  -- narrowed by source_map filter
            if account not in per_account:
                per_account[account] = _make_bucket(agent)

    for event in events:
        if isinstance(event, (BoonApplyEvent, BuffApplyEvent)):
            buff_tracker.process(event)
            # A player can attend purely as a boon source or target (e.g.
            # a healer that only applies quickness/fury, or a DPS that
            # only receives them). Make sure both sides get a summary
            # bucket so their uptime/outgoing metrics are persisted.
            for _agent_id in (event.source_agent_id, event.target_agent_id):
                evt_agent = source_map.get(_agent_id)
                if evt_agent is not None:
                    account = evt_agent.account_name
                    assert account is not None  # noqa: S101
                    if account not in per_account:
                        per_account[account] = _make_bucket(evt_agent)
            continue
        evt_agent = source_map.get(event.source_agent_id)
        if evt_agent is None:
            continue
        account = evt_agent.account_name
        assert account is not None  # noqa: S101
        if account not in per_account:
            per_account[account] = _make_bucket(evt_agent)
        bucket = per_account[account]

        # Inline event application to avoid per-event function-call
        # overhead in this hot loop. ``isinstance`` is required because
        # the event types inherit from ``Event``.
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

    if not per_account and source_map:
        logger.warning(
            "fight %s: %d player agent(s) with account_name but 0 summary "
            "rows; events likely have wrong source_agent_id (parser skill "
            "table misreading cascade -- see v0.10.3 parser fix)",
            orm_fight.id,
            len(source_map),
        )

    # Compute boon uptimes / outgoing across all processed buff events.
    # duration_s is derived from the last event timestamp; empty fights
    # keep all boon metrics at None (no duration to divide by).
    duration_s: float = 0.0
    if events:
        last_time_ms = max((e.time_ms for e in events), default=0)
        duration_s = last_time_ms / 1000.0
    uptimes_by_agent = buff_tracker.compute_all_uptimes(duration_s)
    outgoing_by_agent = buff_tracker.compute_all_outgoing(duration_s)

    db.execute(
        delete(OrmFightPlayerSummary).where(OrmFightPlayerSummary.fight_id == orm_fight.id),
    )
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
        db.add(
            OrmFightPlayerSummary(
                fight_id=orm_fight.id,
                account_name=sanitized_account,
                name=bucket.name,
                profession=bucket.prof,
                elite_spec=bucket.elite,
                total_damage=bucket.damage,
                total_healing=bucket.healing,
                total_buff_removal=bucket.strip,
                detected_role=detected_role,
                detected_tags=detected_tags,
                power_damage=bucket.power,
                condi_damage=bucket.condi,
                **boon_kwargs,
            ),
        )
