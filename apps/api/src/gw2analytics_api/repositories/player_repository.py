"""Repository for ``OrmFightPlayerSummary`` and player-related queries."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, literal_column, or_, select
from sqlalchemy import delete as delete_stmt
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from gw2_analytics.player_profile import FightContribution, PlayerProfile
from gw2_core import EliteSpec, Profession
from gw2analytics_api.models import (
    OrmFight,
    OrmFightAgent,
    OrmFightPlayerBoon,
    OrmFightPlayerSummary,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


__all__ = ["PlayerRepository"]


class PlayerRepository:
    """All DB access for player summaries and profiles."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Cross-fight roll-up ──────────────────────────────────

    def aggregate_profiles(
        self,
        *,
        limit: int,
        offset: int,
        profession_filter: Profession | None = None,
    ) -> list[PlayerProfile]:
        """SQL-only cross-fight roll-up: one ``PlayerProfile`` per account.

        Sorted by ``(total_damage DESC, account_name ASC)`` — the
        deterministic-ordering contract of ``PlayerProfileAggregator``.
        """
        per_account_profession = (
            select(
                OrmFightPlayerSummary.account_name.label("account_name"),
                OrmFightPlayerSummary.profession.label("profession"),
                func.row_number()
                .over(
                    partition_by=OrmFightPlayerSummary.account_name,
                    order_by=(
                        func.count().desc(),
                        OrmFightPlayerSummary.profession.asc(),
                    ),
                )
                .label("rn"),
            )
            .group_by(
                OrmFightPlayerSummary.account_name,
                OrmFightPlayerSummary.profession,
            )
            .cte("per_account_profession")
        )

        main_stmt = (
            select(
                OrmFightPlayerSummary.account_name.label("account_name"),
                func.max(OrmFightPlayerSummary.name).label("name"),
                per_account_profession.c.profession.label("modal_profession"),
                func.max(OrmFightPlayerSummary.elite_spec).label("elite_spec"),
                func.count(OrmFightPlayerSummary.fight_id).label("fights_attended"),
                func.coalesce(func.sum(OrmFightPlayerSummary.total_damage), 0).label(
                    "total_damage"
                ),
                func.coalesce(func.sum(OrmFightPlayerSummary.total_healing), 0).label(
                    "total_healing"
                ),
                func.coalesce(func.sum(OrmFightPlayerSummary.total_buff_removal), 0).label(
                    "total_buff_removal"
                ),
            )
            .join(
                per_account_profession,
                and_(
                    OrmFightPlayerSummary.account_name == per_account_profession.c.account_name,
                    per_account_profession.c.rn == 1,
                ),
            )
            .group_by(
                OrmFightPlayerSummary.account_name,
                per_account_profession.c.profession,
            )
            .order_by(
                func.coalesce(func.sum(OrmFightPlayerSummary.total_damage), 0).desc(),
                OrmFightPlayerSummary.account_name.asc(),
            )
            .limit(limit)
            .offset(offset)
        )

        if profession_filter is not None:
            main_stmt = main_stmt.where(
                per_account_profession.c.profession == int(profession_filter),
            )

        rows = self._session.execute(main_stmt).all()
        return [
            PlayerProfile(
                account_name=row.account_name,
                name=row.name or "",
                profession=Profession(int(row.modal_profession)),
                elite=EliteSpec(int(row.elite_spec)),
                fights_attended=int(row.fights_attended),
                total_damage=int(row.total_damage),
                total_healing=int(row.total_healing),
                total_buff_removal=int(row.total_buff_removal),
                attended_fight_ids=[],
            )
            for row in rows
        ]

    # ── Per-account contributions ────────────────────────────

    def get_account_contributions(
        self,
        *,
        account_name: str,
        limit: int,
        offset: int,
    ) -> list[tuple[FightContribution, datetime]]:
        """SQL-only per-account per-fight contributions."""
        stmt = (
            select(OrmFightPlayerSummary, OrmFight.started_at)
            .join(OrmFight, OrmFight.id == OrmFightPlayerSummary.fight_id)
            .where(OrmFightPlayerSummary.account_name == account_name)
            .order_by(OrmFight.started_at.desc(), OrmFightPlayerSummary.fight_id.asc())
            .limit(limit)
            .offset(offset)
        )

        results: list[tuple[FightContribution, datetime]] = []
        for summary, started_at in self._session.execute(stmt).all():
            results.append(
                (
                    FightContribution(
                        fight_id=summary.fight_id,
                        account_name=summary.account_name,
                        name=summary.name,
                        profession=Profession(summary.profession),
                        elite=EliteSpec(summary.elite_spec),
                        total_damage=summary.total_damage,
                        total_healing=summary.total_healing,
                        total_buff_removal=summary.total_buff_removal,
                        detected_role=summary.detected_role,
                        detected_tags=summary.detected_tags,
                        power_damage=summary.power_damage,
                        condi_damage=summary.condi_damage,
                    ),
                    started_at,
                )
            )
        return results

    # ── Keyset pagination (Phase 4.4) ────────────────────────

    def aggregate_profiles_cursor(
        self,
        *,
        limit: int,
        cursor: str | None = None,
        profession_filter: Profession | None = None,
    ) -> tuple[list[PlayerProfile], str | None]:
        """Cursor-based pagination for the player list.

        Returns ``(profiles, next_cursor)``. The cursor is a
        URL-safe base64-encoded JSON object with ``last_damage``
        and ``last_account`` fields. ``next_cursor`` is ``None``
        when there are no more pages.

        The query fetches ``limit + 1`` rows to detect the
        presence of a next page without a separate COUNT query.
        """
        per_account_profession = (
            select(
                OrmFightPlayerSummary.account_name.label("account_name"),
                OrmFightPlayerSummary.profession.label("profession"),
                func.row_number()
                .over(
                    partition_by=OrmFightPlayerSummary.account_name,
                    order_by=(
                        func.count().desc(),
                        OrmFightPlayerSummary.profession.asc(),
                    ),
                )
                .label("rn"),
            )
            .group_by(
                OrmFightPlayerSummary.account_name,
                OrmFightPlayerSummary.profession,
            )
            .cte("per_account_profession")
        )

        inner = (
            select(
                OrmFightPlayerSummary.account_name.label("account_name"),
                func.max(OrmFightPlayerSummary.name).label("name"),
                per_account_profession.c.profession.label("modal_profession"),
                func.max(OrmFightPlayerSummary.elite_spec).label("elite_spec"),
                func.count(OrmFightPlayerSummary.fight_id).label("fights_attended"),
                func.coalesce(func.sum(OrmFightPlayerSummary.total_damage), 0).label(
                    "total_damage"
                ),
                func.coalesce(func.sum(OrmFightPlayerSummary.total_healing), 0).label(
                    "total_healing"
                ),
                func.coalesce(func.sum(OrmFightPlayerSummary.total_buff_removal), 0).label(
                    "total_buff_removal"
                ),
            )
            .join(
                per_account_profession,
                and_(
                    OrmFightPlayerSummary.account_name == per_account_profession.c.account_name,
                    per_account_profession.c.rn == 1,
                ),
            )
            .group_by(
                OrmFightPlayerSummary.account_name,
                per_account_profession.c.profession,
            )
            .subquery()
        )

        stmt = select(inner).order_by(
            inner.c.total_damage.desc(),
            inner.c.account_name.asc(),
        )

        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
            except (json.JSONDecodeError, ValueError):
                decoded = {}
            last_damage = decoded.get("last_damage")
            last_account = decoded.get("last_account")
            if last_damage is not None and last_account is not None:
                stmt = stmt.where(
                    or_(
                        inner.c.total_damage < last_damage,
                        and_(
                            inner.c.total_damage == last_damage,
                            inner.c.account_name > last_account,
                        ),
                    )
                )

        if profession_filter is not None:
            stmt = stmt.where(
                inner.c.modal_profession == int(profession_filter),
            )

        rows = self._session.execute(stmt.limit(limit + 1)).all()

        has_more = len(rows) > limit
        rows = rows[:limit]

        profiles = [
            PlayerProfile(
                account_name=row.account_name,
                name=row.name or "",
                profession=Profession(int(row.modal_profession)),
                elite=EliteSpec(int(row.elite_spec)),
                fights_attended=int(row.fights_attended),
                total_damage=int(row.total_damage),
                total_healing=int(row.total_healing),
                total_buff_removal=int(row.total_buff_removal),
                attended_fight_ids=[],
            )
            for row in rows
        ]

        next_cursor: str | None = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "last_damage": int(last.total_damage),
                        "last_account": str(last.account_name),
                    }
                ).encode()
            ).decode()

        return profiles, next_cursor

    # ── Slow-path helpers ────────────────────────────────────

    def find_fights_without_summary(self, fight_ids: list[str] | None = None) -> set[str]:
        """Return fight ids that have NO ``OrmFightPlayerSummary`` rows."""
        base = select(OrmFight.id)
        if fight_ids is not None:
            base = base.where(OrmFight.id.in_(fight_ids))
        stmt = base.where(
            ~select(literal_column("1"))
            .where(OrmFightPlayerSummary.fight_id == OrmFight.id)
            .exists()
        )
        return {row[0] for row in self._session.execute(stmt).all()}

    def find_account_fights_without_summary(self, *, account_name: str) -> list[str]:
        """Return fight ids where ``account_name`` had an agent but no summary row."""
        stmt = (
            select(OrmFightAgent.fight_id)
            .where(OrmFightAgent.account_name == account_name)
            .where(
                ~select(literal_column("1"))
                .where(OrmFightPlayerSummary.fight_id == OrmFightAgent.fight_id)
                .exists()
            )
            .distinct()
        )
        return list(self._session.execute(stmt).scalars().all())

    # ── Boon operations (Phase 3.1) ─────────────────────────

    def delete_boons_for_fight(self, fight_id: str) -> None:
        """Delete all boon rows for a fight (cleanup before re-write)."""
        self._session.execute(
            delete_stmt(OrmFightPlayerBoon).where(
                OrmFightPlayerBoon.fight_id == fight_id,
            ),
        )

    def add_boon(self, boon: OrmFightPlayerBoon) -> None:
        """Add one boon row."""
        self._session.add(boon)

    def find_boons_for_fight(
        self,
        fight_id: str,
        *,
        account_name: str | None = None,
    ) -> list[OrmFightPlayerBoon]:
        """Return boon rows for a fight, optionally filtered by account."""
        stmt = select(OrmFightPlayerBoon).where(
            OrmFightPlayerBoon.fight_id == fight_id,
        )
        if account_name is not None:
            stmt = stmt.where(OrmFightPlayerBoon.account_name == account_name)
        return list(self._session.execute(stmt).scalars().all())

    # ── Write ────────────────────────────────────────────────

    def delete_summaries_for_fight(self, fight_id: str) -> None:
        self._session.execute(
            delete_stmt(OrmFightPlayerSummary).where(
                OrmFightPlayerSummary.fight_id == fight_id,
            ),
        )

    def add_summary(self, summary: OrmFightPlayerSummary) -> None:
        self._session.add(summary)

    # ── Batch upsert (Phase 4.6) ─────────────────────────────

    def upsert_summaries(
        self,
        summaries: list[dict[str, object]],
    ) -> None:
        """Batch upsert summary rows via PostgreSQL ``ON CONFLICT DO UPDATE``.

        Replaces the DELETE + per-row INSERT cycle with a single
        statement that updates existing rows and inserts new ones.
        The conflict target is the composite PK ``(fight_id, account_name)``.
        """
        if not summaries:
            return
        stmt = postgres_insert(OrmFightPlayerSummary).values(summaries)
        # Build the ``set_`` dict from the first row's keys, excluding
        # the PK columns that define the conflict target.
        set_ = {
            col: stmt.excluded[col]
            for col in summaries[0]
            if col not in ("fight_id", "account_name")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["fight_id", "account_name"],
            set_=set_,
        )
        self._session.execute(stmt)

    def flush(self) -> None:
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()
