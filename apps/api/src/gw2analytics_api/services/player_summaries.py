from __future__ import annotations

import logging
from dataclasses import dataclass

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

    def _make_bucket(agent: OrmFightAgent) -> _SummaryBucket:
        """Return a fresh zero-totals summary bucket for ``agent``."""
        return _SummaryBucket(
            name=_sanitize_name(agent.name),
            prof=int(agent.profession),
            elite=int(agent.elite_spec),
        )

    per_account: dict[str, _SummaryBucket] = {}
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
            ),
        )
