"""v0.10.10 plan 028: SQL aggregations on ``OrmFightPlayerSummary``.

Phase 2.2: delegates all SQL queries to :class:`PlayerRepository`
so the service layer becomes a thin orchestration wrapper. The
public function signatures are unchanged so callers (routes,
backfill scripts) do not need to be updated.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from gw2_analytics.player_profile import FightContribution, PlayerProfile
from gw2_core import Profession
from gw2analytics_api.repositories import PlayerRepository

# Module-level docstring preserved; full design rationale moved to the
# repository docstring. This file now orchestrates calls to the
# repository layer, keeping the public API stable.


def aggregate_player_profiles_from_sql(
    db: Session,
    *,
    limit: int,
    offset: int,
    profession_filter: Profession | None = None,
) -> list[PlayerProfile]:
    """SQL-only cross-fight roll-up: one :class:`PlayerProfile` per account.

    Delegates to :meth:`PlayerRepository.aggregate_profiles`.
    See the repository docstring for the full query design rationale.
    """
    repo = PlayerRepository(db)
    return repo.aggregate_profiles(
        limit=limit,
        offset=offset,
        profession_filter=profession_filter,
    )


def get_account_contributions_from_sql(
    db: Session,
    *,
    account_name: str,
    limit: int,
    offset: int,
) -> list[tuple[FightContribution, datetime]]:
    """SQL-only per-account per-fight contributions.

    Delegates to :meth:`PlayerRepository.get_account_contributions`.
    """
    repo = PlayerRepository(db)
    return repo.get_account_contributions(
        account_name=account_name,
        limit=limit,
        offset=offset,
    )


def aggregate_player_profiles_cursor(
    db: Session,
    *,
    limit: int,
    cursor: str | None = None,
    profession_filter: Profession | None = None,
) -> tuple[list[PlayerProfile], str | None]:
    """Cursor-based pagination for the player list (Phase 4.4).

    Delegates to :meth:`PlayerRepository.aggregate_profiles_cursor`.
    Returns ``(profiles, next_cursor)``.
    """
    repo = PlayerRepository(db)
    return repo.aggregate_profiles_cursor(
        limit=limit,
        cursor=cursor,
        profession_filter=profession_filter,
    )


def find_fights_without_summary(db: Session, fight_ids: list[str] | None = None) -> set[str]:
    """Return fight ids with no ``OrmFightPlayerSummary`` rows.

    Delegates to :meth:`PlayerRepository.find_fights_without_summary`.
    """
    repo = PlayerRepository(db)
    return repo.find_fights_without_summary(fight_ids=fight_ids)


def find_account_fights_without_summary(
    db: Session,
    *,
    account_name: str,
) -> list[str]:
    """Return fight ids where ``account_name`` had an agent but no summary row.

    Delegates to :meth:`PlayerRepository.find_account_fights_without_summary`.
    """
    repo = PlayerRepository(db)
    return repo.find_account_fights_without_summary(account_name=account_name)


__all__ = [
    "aggregate_player_profiles_cursor",
    "aggregate_player_profiles_from_sql",
    "find_account_fights_without_summary",
    "find_fights_without_summary",
    "get_account_contributions_from_sql",
]
