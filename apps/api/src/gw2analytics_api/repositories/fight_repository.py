"""Repository for ``OrmFight`` and related models."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from gw2analytics_api.models import OrmFight, OrmFightAgent, OrmFightSkill

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session


__all__ = ["FightRepository"]


class FightRepository:
    """All DB access for fights, agents, and skills."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── getters ──────────────────────────────────────────────

    def get_by_id(self, fight_id: str) -> OrmFight | None:
        return self._session.get(OrmFight, fight_id)

    def get_by_id_with_agents_and_skills(self, fight_id: str) -> OrmFight | None:
        return self._session.execute(
            select(OrmFight)
            .where(OrmFight.id == fight_id)
            .options(
                selectinload(OrmFight.agents),
                selectinload(OrmFight.skills),
            ),
        ).scalar_one_or_none()

    def get_by_upload_id(self, upload_id: UUID) -> OrmFight | None:
        return self._session.execute(
            select(OrmFight).where(OrmFight.upload_id == upload_id),
        ).scalar_one_or_none()

    # ── finders ──────────────────────────────────────────────

    def find_by_ids(self, fight_ids: list[str]) -> Sequence[OrmFight]:
        return (
            self._session.execute(
                select(OrmFight)
                .where(OrmFight.id.in_(fight_ids))
                .options(
                    selectinload(OrmFight.agents),
                    selectinload(OrmFight.skills),
                ),
            )
            .scalars()
            .all()
        )

    # ── save ─────────────────────────────────────────────────

    def add(self, orm_fight: OrmFight) -> None:
        self._session.add(orm_fight)

    def add_agent(self, agent: OrmFightAgent) -> None:
        self._session.add(agent)

    def add_skill(self, skill: OrmFightSkill) -> None:
        self._session.add(skill)

    def flush(self) -> None:
        self._session.flush()

    # ── delete ───────────────────────────────────────────────

    def delete(self, orm_fight: OrmFight) -> None:
        self._session.delete(orm_fight)
