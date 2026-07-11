from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session

from gw2_analytics.condi_power_split import KNOWN_CONDI_NAMES
from gw2_analytics.role_detection import detect_role_lite
from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerSummary,
)
from gw2analytics_api.services.fight_persistence import _sanitize_name

logger = logging.getLogger(__name__)


def _persist_player_summaries(  # noqa: PLR0912
    db: Session,
    orm_fight: OrmFight,
    events: list[Event],
) -> None:
    source_map: dict[int, OrmFightAgent] = {
        a.agent_id: a for a in orm_fight.agents if a.is_player and a.account_name
    }
    if not source_map:
        return

    skill_name_map: dict[int, str | None] = {int(s.skill_id): s.name for s in orm_fight.skills}

    per_account: dict[str, dict[str, int | str]] = {}
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
                per_account[account] = {
                    "damage": 0,
                    "healing": 0,
                    "strip": 0,
                    "power": 0,
                    "condi": 0,
                    "name": _sanitize_name(agent.name),
                    "prof": int(agent.profession),
                    "elite": int(agent.elite_spec),
                }

    for event in events:
        agent = source_map.get(event.source_agent_id)
        if agent is None:
            continue
        account = agent.account_name
        assert account is not None  # noqa: S101
        if account in per_account:
            bucket: dict[str, int | str] = per_account[account]
            bucket["name"] = _sanitize_name(agent.name)
        else:
            bucket = {
                "damage": 0,
                "healing": 0,
                "strip": 0,
                "power": 0,
                "condi": 0,
                "name": _sanitize_name(agent.name),
                "prof": int(agent.profession),
                "elite": int(agent.elite_spec),
            }
            per_account[account] = bucket
        if isinstance(event, DamageEvent):
            bucket["damage"] = int(bucket["damage"]) + event.damage
            skill_name = skill_name_map.get(event.skill_id)
            if skill_name in KNOWN_CONDI_NAMES:
                bucket["condi"] = int(bucket["condi"]) + event.damage
            else:
                bucket["power"] = int(bucket["power"]) + event.damage
        elif isinstance(event, HealingEvent):
            bucket["healing"] = int(bucket["healing"]) + event.healing
        elif isinstance(event, BuffRemovalEvent):
            bucket["strip"] = int(bucket["strip"]) + event.buff_removal

    if not per_account and source_map:
        logger.warning(
            "fight %s: %d player agent(s) with account_name but 0 summary "
            "rows; events likely have wrong source_agent_id (parser skill "
            "table misreading cascade -- see v0.10.3 parser fix)",
            orm_fight.id,
            len(source_map),
        )

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
            total_damage=int(bucket["damage"]),
            total_healing=int(bucket["healing"]),
            total_buff_removal=int(bucket["strip"]),
            profession_int=int(bucket["prof"]),
            elite_spec_int=int(bucket["elite"]),
        )
        db.add(
            OrmFightPlayerSummary(
                fight_id=orm_fight.id,
                account_name=sanitized_account,
                name=bucket["name"],
                profession=int(bucket["prof"]),
                elite_spec=int(bucket["elite"]),
                total_damage=int(bucket["damage"]),
                total_healing=int(bucket["healing"]),
                total_buff_removal=int(bucket["strip"]),
                detected_role=detected_role,
                detected_tags=detected_tags,
                power_damage=int(bucket.get("power", 0)),
                condi_damage=int(bucket.get("condi", 0)),
            ),
        )
