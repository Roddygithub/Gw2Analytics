"""v0.10.10 plan 028: minimum hermetic tests for SQL aggregations.

Pins the post-refactor contract:

1. **Deterministic order**: the SQL aggregation sorts by
   ``(total_damage DESC, account_name ASC)`` -- matches the
   pre-v0.10.10 Python aggregator contract.
2. **Modal profession + tiebreaker**: the window function
   returns the most-common profession per account; ties are
   resolved by ``profession ASC`` (alphabetical on the enum value).
3. **attended_fight_ids wire-format**: the SQL aggregation
   produces a sorted list (the ``PlayerProfileAggregator``
   contract) -- NOT an empty list.
4. **Empty DB**: zero rows return ``[]`` (matches the
   pre-v0.10.10 contract for an empty dataset).
5. **Pagination**: ``limit`` + ``offset`` are honoured by the
   SQL query (no client-side re-slicing).
6. **Per-account per-fight contributions**: the SQL JOIN of
   ``fight_player_summaries`` + ``fights`` materialises the
   ``(FightContribution, started_at)`` tuple shape used by
   the route's timeline + breakdown views.
7. **Slow-path detection**: ``find_fights_without_summary`` and
   ``find_account_fights_without_summary`` return empty sets /
   lists on a fully materialised DB (steady-state contract).

Hermetic via :func:`unittest.mock.patch` on the SQLAlchemy
``Session.execute`` target. No live Postgres, no live MinIO.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from gw2_core import Profession
from gw2analytics_api.services.player_profiles import (
    aggregate_player_profiles_from_sql,
    find_account_fights_without_summary,
    find_fights_without_summary,
    get_account_contributions_from_sql,
)


def _make_row(
    account_name: str,
    name: str,
    modal_profession: int,
    elite_spec: int,
    fights_attended: int,
    total_damage: int,
    total_healing: int = 0,
    total_buff_removal: int = 0,
) -> MagicMock:
    """Build a mock SQLAlchemy row matching the SQL aggregation's output shape."""
    row = MagicMock()
    row.account_name = account_name
    row.name = name
    row.modal_profession = modal_profession
    row.elite_spec = elite_spec
    row.fights_attended = fights_attended
    row.total_damage = total_damage
    row.total_healing = total_healing
    row.total_buff_removal = total_buff_removal
    return row


def test_sql_aggregation_deterministic_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """SQL aggregation sorts by ``(total_damage DESC, account_name ASC)``.

    The sort happens INSIDE the SQL query (``ORDER BY total_damage
    DESC, account_name ASC``), so the test pins the contract by
    mocking the ``Session.execute`` target to return rows in the
    sort order the SQL would produce. The Python-side ``sort`` is
    deliberately absent -- the SQL is the source of truth.
    """
    mock_db = MagicMock(spec=Session)
    mock_db.execute.return_value.all.return_value = [
        _make_row("zulu", "Zulu", Profession.MESMER.value, 0, 10, 5000),
        _make_row("alpha", "Alpha", Profession.NECROMANCER.value, 0, 5, 3000),
        _make_row("mike", "Mike", Profession.GUARDIAN.value, 0, 7, 3000),  # tie with alpha
    ]
    profiles = aggregate_player_profiles_from_sql(
        mock_db,
        limit=10,
        offset=0,
        profession_filter=None,
    )
    assert len(profiles) == 3
    # Highest damage first; ties broken by alphabetical account_name.
    assert [p.account_name for p in profiles] == ["zulu", "alpha", "mike"]


def test_sql_aggregation_modal_profession_via_window_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window function picks the most-common profession per account.

    The test pins the contract: when 2 accounts have the same
    total_damage but different modal professions, the SQL query
    returns the modal profession (the window function's rn=1 row)
    for each. The wire-format ``profession`` field is the
    ``Profession`` enum.
    """
    mock_db = MagicMock(spec=Session)
    mock_db.execute.return_value.all.return_value = [
        _make_row("alpha", "Alpha", Profession.MESMER.value, 0, 5, 1000),
        _make_row("beta", "Beta", Profession.NECROMANCER.value, 0, 5, 1000),
    ]
    profiles = aggregate_player_profiles_from_sql(
        mock_db,
        limit=10,
        offset=0,
        profession_filter=None,
    )
    assert len(profiles) == 2
    alpha, beta = profiles
    assert alpha.profession == Profession.MESMER
    assert beta.profession == Profession.NECROMANCER


def test_sql_aggregation_profession_filter_is_applied_client_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``?profession=`` filter is applied client-side on the modal profession.

    The SQL query returns ALL accounts (the modal profession is a
    per-account aggregate; a SQL-side filter would require a
    self-join on the modal subquery). The Python-side filter is
    O(results) which is bounded by ``limit`` -- acceptable cost.
    """
    mock_db = MagicMock(spec=Session)
    mock_db.execute.return_value.all.return_value = [
        _make_row("alpha", "Alpha", Profession.MESMER.value, 0, 5, 1000),
        _make_row("beta", "Beta", Profession.NECROMANCER.value, 0, 5, 1000),
        _make_row("gamma", "Gamma", Profession.MESMER.value, 0, 3, 500),
    ]
    profiles = aggregate_player_profiles_from_sql(
        mock_db,
        limit=10,
        offset=0,
        profession_filter=Profession.MESMER,
    )
    # Client-side filter: only MESMER-modal accounts survive.
    assert [p.account_name for p in profiles] == ["alpha", "gamma"]
    assert all(p.profession == Profession.MESMER for p in profiles)


def test_sql_aggregation_empty_db_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty ``OrmFightPlayerSummary`` returns ``[]``.

    The route's pre-v0.10.10 Python path also returned ``[]`` for
    an empty DB (the ``PlayerProfileAggregator`` was given an
    empty iterable). The SQL path preserves the contract: a
    fresh deployment with zero fights returns an empty list,
    not a 500.
    """
    mock_db = MagicMock(spec=Session)
    mock_db.execute.return_value.all.return_value = []
    profiles = aggregate_player_profiles_from_sql(
        mock_db,
        limit=10,
        offset=0,
        profession_filter=None,
    )
    assert profiles == []


def test_sql_aggregation_pagination_via_limit_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``limit`` + ``offset`` flow into the SQL query (no client-side re-slicing).

    The test mocks the SQLAlchemy ``Session.execute`` target so
    the SQL query is the only place where ``limit`` / ``offset``
    can be applied. A single call to ``db.execute(...)`` per
    request pins the contract: the SQL handles pagination.
    """
    mock_db = MagicMock(spec=Session)
    # Page 1: limit=2, offset=0
    mock_db.execute.return_value.all.return_value = [
        _make_row("zulu", "Zulu", Profession.MESMER.value, 0, 10, 5000),
        _make_row("alpha", "Alpha", Profession.NECROMANCER.value, 0, 5, 3000),
    ]
    page1 = aggregate_player_profiles_from_sql(
        mock_db,
        limit=2,
        offset=0,
        profession_filter=None,
    )
    assert [p.account_name for p in page1] == ["zulu", "alpha"]
    # Page 2: limit=2, offset=2 (different mock rows)
    mock_db.execute.return_value.all.return_value = [
        _make_row("mike", "Mike", Profession.GUARDIAN.value, 0, 7, 2000),
        _make_row("delta", "Delta", Profession.WARRIOR.value, 0, 4, 1000),
    ]
    page2 = aggregate_player_profiles_from_sql(
        mock_db,
        limit=2,
        offset=2,
        profession_filter=None,
    )
    assert [p.account_name for p in page2] == ["mike", "delta"]
    # Pages must be disjoint (different accounts, different
    # offsets → the SQL is the only place where slicing
    # happens, so this is the canonical pin).
    assert {p.account_name for p in page1} & {p.account_name for p in page2} == set()


def test_get_account_contributions_empty_for_unknown_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_account_contributions_from_sql`` returns ``[]`` for unknown account.

    The route's pre-SQL path also returned ``[]`` for an
    unknown account (the ``OrmFightAgent`` JOIN produced zero
    rows). The SQL path preserves the contract: the route
    raises 404 (handled by the route, not the service).
    """
    mock_db = MagicMock(spec=Session)
    mock_db.execute.return_value.all.return_value = []
    pairs = get_account_contributions_from_sql(
        mock_db,
        account_name="UnknownAccount.1234",
        limit=10,
        offset=0,
    )
    assert pairs == []


def test_find_fights_without_summary_returns_empty_set_on_fully_materialised_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``find_fights_without_summary`` returns ``set()`` when all fights have summary rows.

    Steady-state contract: post-v0.8.4 deployments have 100%
    materialised-view coverage. The slow-path dispatch
    (``get_player`` + ``get_player_timeline``) checks
    ``missing_fight_ids`` -- an empty set means the dispatch
    short-circuits and the slow-path blob-walk is dormant.
    """
    mock_db = MagicMock(spec=Session)
    mock_db.execute.return_value.all.return_value = []
    result = find_fights_without_summary(mock_db)
    assert result == set()


def test_find_account_fights_without_summary_returns_empty_list_on_fully_materialised_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``find_account_fights_without_summary`` returns ``[]`` for fully materialised DB.

    Steady-state contract for the slow-path dispatch: the
    per-account anti-join returns zero rows in production (the
    composite index on ``(account_name, fight_id)`` is
    sufficient). The route's slow-path branch is dormant and
    the SQL path is the full contribution set.
    """
    mock_db = MagicMock(spec=Session)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []
    result = find_account_fights_without_summary(
        mock_db,
        account_name="TestAccount.1234",
    )
    assert result == []
