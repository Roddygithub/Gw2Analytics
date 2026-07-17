from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.orm import Session

from gw2_core import Fight as DomainFight
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightSkill,
    Upload,
)

logger = logging.getLogger(__name__)

MAX_NAME_LEN: Final[int] = 128


def _sanitize_name(name: str | None, max_length: int = MAX_NAME_LEN) -> str:
    """Normalise a free-text name from the EVTC parser to a safe ORM string.

    The contract is intentionally non-obvious from the body alone:

    - Input contract: ``name`` may be ``None`` or empty; both produce
      ``""`` (NOT ``None``). The return type is ``str`` (never
      ``Optional[str]``) so callers can pass the result directly to a
      non-nullable SQLAlchemy ``String`` column without a defensive
      ``or ""`` wrap.
    - ``"\\x00"`` is stripped BEFORE truncation so a NUL at position
      ``max_length - 1`` cannot push a partial byte past the limit
      (the parser may surface NULs in synthetic agent names).
    - The function is a 1-line wrapper around the static helper, but
      callers MUST NOT re-wrap with ``or ""`` or re-strip ``\\x00`` --
      both are already handled here. The pre-plan-028 callers were
      already in the right shape; this docstring is preventive against
      future drift.
    """
    if not name:
        return ""
    return name.replace("\x00", "")[:max_length]


def _deduplicate_ids[T](
    items: list[T],
    *,
    key: Callable[[T], int],
    log_type: str,
    fight_id: str,
) -> Iterator[T]:
    """Yield ``items`` keeping the first occurrence of each id."""
    seen: set[int] = set()
    for item in items:
        item_id = key(item)
        if item_id in seen:
            logger.info(
                "fight %s: deduplicating duplicate %s_id=%s; first-seen entry wins",
                fight_id,
                log_type,
                item_id,
            )
            continue
        seen.add(item_id)
        yield item


def _save_fight(db: Session, upload: Upload, cf: DomainFight) -> None:
    if cf.header is None:
        msg = "_save_fight called without header"
        raise ValueError(msg)

    head = cf.header
    started_at = datetime.now(UTC)

    orm_fight = OrmFight(
        id=cf.id,
        upload_id=upload.id,
        build_version=head.build_version,
        encounter_id=head.encounter_id,
        agent_count=head.agent_count,
        started_at=started_at,
        game_type=int(cf.game_type),
    )
    db.add(orm_fight)
    db.flush()

    for agent in _deduplicate_ids(
        cf.agents,
        key=lambda a: int(a.id),
        log_type="agent",
        fight_id=cf.id,
    ):
        db.add(
            OrmFightAgent(
                fight_id=cf.id,
                agent_id=int(agent.id),
                name=_sanitize_name(agent.name),
                profession=int(agent.profession.value),
                elite_spec=int(agent.elite.value),
                is_player=agent.is_player,
                account_name=(
                    None
                    if agent.account_name is None
                    else _sanitize_name(agent.account_name.lstrip(":"))
                ),
                subgroup=(None if agent.subgroup is None else _sanitize_name(agent.subgroup)),
            ),
        )

    for skill in _deduplicate_ids(
        cf.skills,
        key=lambda s: int(s.id),
        log_type="skill",
        fight_id=cf.id,
    ):
        db.add(
            OrmFightSkill(
                fight_id=cf.id,
                skill_id=int(skill.id),
                name=_sanitize_name(skill.name),
            ),
        )

    if head.skill_count > 0 and not cf.skills:
        logger.warning(
            "fight %s: header claims skill_count=%d but parser yielded 0 skills; "
            "skill table likely truncated or corrupted (see MAX_SKILL_NAME_BYTES "
            "warning in gw2_evtc_parser.parser)",
            cf.id,
            head.skill_count,
        )

    db.flush()
