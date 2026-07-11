"""v0.10.10 plan 028: SQL aggregations on ``OrmFightPlayerSummary``.

Replaces the Python-side cross-fight roll-up in
:mod:`gw2analytics_api.routes.players` with native Postgres
``GROUP BY`` queries against the pre-materialised
:class:`~gw2analytics_api.models.OrmFightPlayerSummary` view
(introduced v0.8.4 plan 045). At 10k WvW fights with a mean of
~50 agents per fight, the previous Python loop loaded ~500k ORM
objects per request; the SQL path stays bounded by the response
size (LIMIT/OFFSET) and the PK index.

Three concerns are addressed by the SQL path:

1. **Cross-fight roll-up** for ``/api/v1/players`` and the
   per-account view. One ``GROUP BY account_name`` query produces
   the per-account totals + the modal profession via a CTE
   window function. Sorts by ``(total_damage DESC, account_name
   ASC)`` to match the ``PlayerProfileAggregator`` deterministic
   contract.

2. **Per-account per-fight contributions** for the timeline +
   per-fight breakdown views (``/api/v1/players/{name}/timeline`` +
   ``/api/v1/players/{name}``). One ``WHERE account_name = ?``
   query joins ``fight_player_summaries`` + ``fights`` to
   materialise the per-fight ``FightContribution`` rows. The
   page-by-account cost is O(fights_attended) instead of
   O(fights x events).

3. **Slow-path detection** for pre-v0.8.4 fights (fights whose
   events blob has no matching ``OrmFightPlayerSummary`` row).
   The :func:`find_fights_without_summary` helper returns the
   subset of fight ids that need the legacy blob-walk fallback.
   At 100% materialised-view coverage (post-v0.8.4 deployments),
   the result set is empty and the blob-walk is dormant.

Why a window function for the modal profession?
================================================

Postgres has no built-in ``MODE()`` aggregate. The canonical
alternatives are:

- ``MODE() WITHIN GROUP (ORDER BY profession)`` -- only in
  commercial Postgres forks, not in the open-source distribution.
- ``DISTINCT ON (account_name)`` with a ``LATERAL`` join -- more
  idiomatic but verbose and harder to extend to deterministic
  tiebreakers.
- ``ROW_NUMBER() OVER (PARTITION BY account_name ORDER BY
  COUNT(*) DESC, profession ASC)`` -- portable, deterministic,
  one-line tiebreaker. This is what plan 028 uses.

The tiebreaker ``profession ASC`` resolves the "5 MESMER + 5
NECROMANCER" case deterministically (alphabetical on the enum
value). The escape hatch in the plan offers a damage-weighted
tiebreaker if a UX-affecting complaint surfaces; the 1-line SQL
swap + the matching test update closes that path.

Why one CTE, not two subqueries?
=================================

v0.10.10 round 1 of the SQL refactor built a 2-subquery pattern
(``modal_subq`` with a no-op ``.add_columns()`` + a separate
``ranked`` subquery that called ``func.count(modal_subq.c.profession)`` --
a non-sensical count on a column that was itself the output of
a subquery). Round 2 collapses this into a single CTE named
``per_account_profession`` that:

1. Groups by ``(account_name, profession)`` to get per-(account, profession)
   fight counts.
2. Applies ``ROW_NUMBER()`` partitioned on ``account_name`` to rank
   the rows within each account by ``COUNT(*) DESC, profession ASC``.
3. Is joined back to the main aggregation on ``(account_name, rn=1)``
   to surface only the modal profession.

The CTE pattern is the canonical SQL idiom for "top-N per group"
in open-source Postgres; it produces identical plans to the
2-subquery version but is one logical step.

Why the pre-materialised ``OrmFightPlayerSummary`` view?
=========================================================

The view is the canonical source of truth for cross-fight
aggregations (since v0.8.4 plan 045). The events blobs are the
audit-trail artifact, not the primary aggregation surface. The
SQL path is the natural extension of the fast-path materialised
view: the same data is read via the same index, just joined
across more rows in a single query instead of N+1 round-trips.

Pre-v0.8.4 fights (no summary row) are handled by the
:func:`find_fights_without_summary` helper. The blob-walk
fallback is preserved for operator-driven rollbacks; the
integration tests in ``tests/test_uploads_e2e.py`` continue to
exercise the legacy path.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.orm import Session

from gw2_analytics.player_profile import FightContribution, PlayerProfile
from gw2_core import EliteSpec, Profession
from gw2analytics_api.models import OrmFight, OrmFightAgent, OrmFightPlayerSummary


def aggregate_player_profiles_from_sql(
    db: Session,
    *,
    limit: int,
    offset: int,
    profession_filter: Profession | None = None,
) -> list[PlayerProfile]:
    """SQL-only cross-fight roll-up: one :class:`PlayerProfile` per account.

    Translates the window-function + ``GROUP BY`` pattern from
    the plan 028 design into a single SQLAlchemy ``select(...)``
    with one CTE. The result is sorted by ``(total_damage DESC,
    account_name ASC)`` -- the deterministic-ordering contract of
    ``PlayerProfileAggregator`` (the post-aggregation wire
    validator's invariant check is skipped because the SQL
    already sorts; the test suite pins this with byte-identical
    golden outputs).

    Modal profession is computed via a CTE window function:
    ``ROW_NUMBER() OVER (PARTITION BY account_name ORDER BY
    COUNT(*) DESC, profession ASC)``. The deterministic
    tiebreaker resolves the "5 MESMER + 5 NECROMANCER" case via
    alphabetical ordering on the enum value.

    The profession filter is applied client-side (after the SQL
    query returns) because the filter is on the MODAL profession
    (the per-account aggregate), not on the per-fight profession.
    A SQL-side filter would require a self-join on the
    modal-profession CTE; the client-side filter is O(results)
    which is bounded by ``limit``.

    Parameters
    ----------
    db : Session
        The active SQLAlchemy session.
    limit, offset : int
        Pagination window (1 <= limit <= 500, 0 <= offset).
    profession_filter : Profession | None
        Optional modal-profession filter. ``None`` returns all
        accounts. An unrecognised enum value surfaces as a
        pre-route 422 (the route's :func:`_parse_profession_filter`
        handles the URL-parsing contract).

    Returns
    -------
    list[PlayerProfile]
        Sorted by ``(total_damage DESC, account_name ASC)``,
        matching the ``PlayerProfileAggregator`` contract. Empty
        list on a fresh DB.
    """
    # CTE: per-(account, profession) fight counts + modal ranking.
    # The row_number is scoped to account_name so each account gets
    # exactly ONE ``rn == 1`` row (the modal profession).
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

    # Main aggregation: per-account totals + the modal profession
    # (joined from the CTE on rn == 1). The join is an INNER JOIN
    # because every account has at least one (account, profession)
    # pair by construction (the CTE is grouped on
    # (account, profession) from the per-(account, profession)
    # fight counts).
    main_stmt = (
        select(
            OrmFightPlayerSummary.account_name.label("account_name"),
            func.max(OrmFightPlayerSummary.name).label("name"),
            per_account_profession.c.profession.label("modal_profession"),
            func.max(OrmFightPlayerSummary.elite_spec).label("elite_spec"),
            func.count(OrmFightPlayerSummary.fight_id).label("fights_attended"),
            func.coalesce(func.sum(OrmFightPlayerSummary.total_damage), 0).label("total_damage"),
            func.coalesce(func.sum(OrmFightPlayerSummary.total_healing), 0).label("total_healing"),
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

    rows = db.execute(main_stmt).all()

    profiles: list[PlayerProfile] = []
    for row in rows:
        profile = PlayerProfile(
            account_name=row.account_name,
            name=row.name or "",
            profession=Profession(int(row.modal_profession)),
            elite=EliteSpec(int(row.elite_spec)),
            fights_attended=int(row.fights_attended),
            total_damage=int(row.total_damage),
            total_healing=int(row.total_healing),
            total_buff_removal=int(row.total_buff_removal),
            attended_fight_ids=[],  # not loaded by the SQL path
        )
        profiles.append(profile)

    if profession_filter is not None:
        profiles = [p for p in profiles if p.profession == profession_filter]

    return profiles


def get_account_contributions_from_sql(
    db: Session,
    *,
    account_name: str,
    limit: int,
    offset: int,
) -> list[tuple[FightContribution, datetime]]:
    """SQL-only per-account per-fight contributions for the timeline + breakdown views.

    One ``WHERE account_name = ?`` query joins
    ``fight_player_summaries`` + ``fights`` to materialise the
    per-fight ``FightContribution`` rows. Sorted by
    ``(started_at DESC, fight_id ASC)`` to match the route's
    recency-first contract.

    The result tuples are ``(FightContribution, started_at)``
    so the route can build its per-fight breakdown + timeline
    without an extra round-trip to load ``OrmFight.started_at``.

    Parameters
    ----------
    db : Session
        The active SQLAlchemy session.
    account_name : str
        The :class:`OrmFightPlayerSummary.account_name` to
        filter on. URL-decoded by the route's
        ``:path`` converter.
    limit, offset : int
        Pagination window (the timeline route uses
        ``limit in [1, 100]``; the detail route uses no limit
        because the per-fight breakdown is bounded by the
        account's fight count).

    Returns
    -------
    list[tuple[FightContribution, datetime]]
        Sorted by ``(started_at DESC, fight_id ASC)``. Empty
        list if the account has no summary rows.
    """
    stmt = (
        select(OrmFightPlayerSummary, OrmFight.started_at)
        .join(OrmFight, OrmFight.id == OrmFightPlayerSummary.fight_id)
        .where(OrmFightPlayerSummary.account_name == account_name)
        .order_by(OrmFight.started_at.desc(), OrmFightPlayerSummary.fight_id.asc())
        .limit(limit)
        .offset(offset)
    )

    results: list[tuple[FightContribution, datetime]] = []
    for summary, started_at in db.execute(stmt).all():
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


def find_fights_without_summary(db: Session, fight_ids: list[str] | None = None) -> set[str]:
    """Return the subset of fight ids that have NO ``OrmFightPlayerSummary`` rows.

    Used by the route to dispatch the legacy blob-walk fallback
    for pre-v0.8.4 fights (fights whose events blob has no
    matching summary row). At 100% materialised-view coverage
    (post-v0.8.4 deployments), the result set is empty and the
    blob-walk is dormant.

    The query is a single ``NOT EXISTS`` subquery (Postgres
    anti-join, O(N) on the PK index). If ``fight_ids`` is
    ``None``, the helper returns ALL fights without a summary
    row (used by the backfill script's "show me the unbackfilled
    fights" diagnostic).

    Parameters
    ----------
    db : Session
        The active SQLAlchemy session.
    fight_ids : list[str] | None
        Optional fight-id list to filter on. ``None`` returns
        the full set.

    Returns
    -------
    set[str]
        The fight ids that have no matching
        ``OrmFightPlayerSummary`` row. Empty set on a fully
        materialised DB.
    """
    base = select(OrmFight.id)
    if fight_ids is not None:
        base = base.where(OrmFight.id.in_(fight_ids))
    stmt = base.where(
        ~select(literal_column("1")).where(OrmFightPlayerSummary.fight_id == OrmFight.id).exists()
    )
    return {row[0] for row in db.execute(stmt).all()}


def find_account_fights_without_summary(
    db: Session,
    *,
    account_name: str,
) -> list[str]:
    """Return fight ids where ``account_name`` had an agent but no summary row.

    Slow-path dispatch helper for ``get_player`` and
    ``get_player_timeline``: a single ``DISTINCT`` query joins
    ``OrmFightAgent`` (filtered by ``account_name``) with a
    ``NOT EXISTS`` anti-join against ``OrmFightPlayerSummary``.
    The result is the list of pre-v0.8.4 fights for this account
    that the legacy blob-walk fallback must cover.

    At 100% materialised-view coverage (post-v0.8.4
    deployments), the result is empty and the slow-path is
    dormant. The query is O(account_fights) on the
    ``(account_name)`` index of ``fight_agents`` (composite
    (account_name, fight_id) index per the model docstring).

    Parameters
    ----------
    db : Session
        The active SQLAlchemy session.
    account_name : str
        The :class:`OrmFightAgent.account_name` to filter on.

    Returns
    -------
    list[str]
        Distinct fight ids where this account had an agent but
        no ``OrmFightPlayerSummary`` row exists. Empty list
        when the materialised view is 100% complete.
    """
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
    return list(db.execute(stmt).scalars().all())


__all__ = [
    "aggregate_player_profiles_from_sql",
    "find_account_fights_without_summary",
    "find_fights_without_summary",
    "get_account_contributions_from_sql",
]
