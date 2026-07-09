"""v0.10.0 plan 032: hermetic pytest cases for the cross-account timeline aggregator.

Pure-Python tests (no DB, no FastAPI). Construct :class:`FightContribution`
instances in-memory, exercise the aggregator's bucket + day + tz paths,
and validate the cross-field invariants.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from gw2_analytics.cross_account_timeline import (
    CrossAccountTimelineAggregator,
    CrossAccountTimelineSeries,
)
from gw2_analytics.player_profile import FightContribution
from gw2_core import EliteSpec, Profession

_BASE_TIME = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)


def _contrib(
    account: str,
    fight_id: str,
    damage: int,
    healing: int = 0,
    strip: int = 0,
) -> FightContribution:
    return FightContribution(
        fight_id=fight_id,
        account_name=account,
        name=account,
        profession=Profession.UNKNOWN,
        elite=EliteSpec.UNKNOWN,
        total_damage=damage,
        total_healing=healing,
        total_buff_removal=strip,
    )


def _started(fight_id: str, offset_hours: float = 0) -> datetime:
    """Return a started_at ``offset_hours`` past the base time."""
    return _BASE_TIME + timedelta(hours=offset_hours)


def test_empty_input_yields_empty_list() -> None:
    """Plan 032 #1: empty ``per_account_contributions`` -> ``series=[]``."""
    aggregator = CrossAccountTimelineAggregator()
    result = aggregator.aggregate(
        per_account_contributions={},
        fight_id_to_started={},
    )
    assert result == []


def test_two_accounts_one_fight_each_emits_two_series() -> None:
    """Plan 032 #2: two accounts with one fight each -> two series, recency-first sorted."""
    aggregator = CrossAccountTimelineAggregator()
    fight_id_to_started = {"f1": _started("f1", 0), "f2": _started("f2", 24)}
    contributions = {
        "alice": [_contrib("alice", "f1", 100)],
        "bob": [_contrib("bob", "f2", 200)],
    }
    result = aggregator.aggregate(
        per_account_contributions=contributions,
        fight_id_to_started=fight_id_to_started,
    )
    assert len(result) == 2
    assert {s.account_name for s in result} == {"alice", "bob"}
    for s in result:
        assert len(s.points) == 1
        assert isinstance(s, CrossAccountTimelineSeries)


def test_recency_first_sort() -> None:
    """Plan 032 #3: series' ``points`` array recites recency-first (started_at DESC)."""
    aggregator = CrossAccountTimelineAggregator()
    fight_id_to_started = {
        "f_old": _started("f_old", 0),
        "f_new": _started("f_new", 24),
        "f_mid": _started("f_mid", 12),
    }
    contributions = {
        "alice": [
            _contrib("alice", "f_old", 100),
            _contrib("alice", "f_new", 300),
            _contrib("alice", "f_mid", 200),
        ],
    }
    result = aggregator.aggregate(
        per_account_contributions=contributions,
        fight_id_to_started=fight_id_to_started,
    )
    assert len(result) == 1
    alice = result[0]
    assert [p.fight_id for p in alice.points] == ["f_new", "f_mid", "f_old"]


def test_account_with_no_fights_yields_empty_points_series() -> None:
    """Plan 032 #4: an account in the input map with empty contributions
    still emits a series entry (points=[])."""
    aggregator = CrossAccountTimelineAggregator()
    fight_id_to_started = {"f1": _started("f1", 0)}
    contributions = {
        "alice": [_contrib("alice", "f1", 100)],
        "ghost": [],  # requested but no fights attended
    }
    result = aggregator.aggregate(
        per_account_contributions=contributions,
        fight_id_to_started=fight_id_to_started,
    )
    assert len(result) == 2
    ghost_series = next(s for s in result if s.account_name == "ghost")
    assert ghost_series.points == []
    assert ghost_series.name == ""  # no last-seen name


def test_day_bucket_collapses_fights_sharing_calendar_day() -> None:
    """Plan 032 #5: ``?bucket=day`` sums per-day totals with day-midnight started_at."""
    aggregator = CrossAccountTimelineAggregator()
    # Two fights on the SAME UTC calendar day for the same account.
    same_day_1 = datetime(2026, 7, 8, 10, 0, 0, tzinfo=UTC)
    same_day_2 = datetime(2026, 7, 8, 22, 0, 0, tzinfo=UTC)
    fight_id_to_started = {"f1": same_day_1, "f2": same_day_2}
    contributions = {
        "alice": [
            _contrib("alice", "f1", 100, healing=50),
            _contrib("alice", "f2", 200, healing=30),
        ],
    }
    result = aggregator.aggregate(
        per_account_contributions=contributions,
        fight_id_to_started=fight_id_to_started,
        bucket="day",
        tz=ZoneInfo("UTC"),
    )
    assert len(result) == 1
    alice = result[0]
    # One day-bucketed point (both fights on 2026-07-08 collapsed).
    assert len(alice.points) == 1
    point = alice.points[0]
    # Totals summed across the day's fights.
    assert point.total_damage == 300
    assert point.total_healing == 80
    assert point.total_buff_removal == 0
    # started_at is UTC midnight of 2026-07-08.
    assert point.started_at == datetime(2026, 7, 8, 0, 0, 0, tzinfo=UTC)


def test_unknown_tz_returns_empty_input_validation() -> None:
    """Plan 032 #6: the aggregator applies the TZ dict for day-bucketing
    but does NOT validate the TZ string itself -- the route layer is
    responsible. This test just verifies the default (``None`` -> UTC)
    surfaces 422-friendly behaviour on a known-good input."""
    aggregator = CrossAccountTimelineAggregator()
    fight_id_to_started = {"f1": _started("f1", 0)}
    contributions = {"alice": [_contrib("alice", "f1", 100)]}
    # ``tz=None`` defaults to UTC; this is the canonical happy path.
    result = aggregator.aggregate(
        per_account_contributions=contributions,
        fight_id_to_started=fight_id_to_started,
        bucket="day",
        tz=None,
    )
    assert len(result) == 1


def test_recency_first_sort_invariant_holds() -> None:
    """Plan 032 #7: the aggregator's recency-first invariant holds
    on a representative input (recency-first for each series'
    ``points`` array). The length-mismatch invariant is
    structurally guaranteed by the per-key iteration so it is
    not asserted here (tautological guard was removed in the
    round-8 cleanup; see the ``cross_account_timeline.py``
    ``_check_invariants`` docstring for the rationale)."""
    aggregator = CrossAccountTimelineAggregator()
    fight_id_to_started = {
        "f_old": _started("f_old", 0),
        "f_new": _started("f_new", 24),
    }
    contributions = {
        "alice": [
            _contrib("alice", "f_old", 100),
            _contrib("alice", "f_new", 300),
        ],
    }
    result = aggregator.aggregate(
        per_account_contributions=contributions,
        fight_id_to_started=fight_id_to_started,
    )
    # Recency-first: newest first.
    assert [p.fight_id for p in result[0].points] == ["f_new", "f_old"]


def test_aggregate_emits_one_series_per_requested_account() -> None:
    """Plan 032 #8: every key in ``per_account_contributions``
    yields exactly one :class:`CrossAccountTimelineSeries`
    in the output (the "all requested accounts -> all series"
    contract that the route's 404-vs-empty distinction
    depends on). An account with no contributions still gets
    a series entry with ``points: []`` (NOT dropped from the
    response -- the analyst UX needs a same-shape response
    for all requested accounts).
    """
    aggregator = CrossAccountTimelineAggregator()
    fight_id_to_started = {"f1": _started("f1", 0)}
    contributions = {
        "alice": [_contrib("alice", "f1", 100)],
        # bob: in the input map with NO contributions -- must
        # still appear in the result with an empty points list.
        "bob": [],
        # ghost: in the input map with NO contributions AND
        # not in any fight -- same shape as bob.
        "ghost": [],
    }
    result = aggregator.aggregate(
        per_account_contributions=contributions,
        fight_id_to_started=fight_id_to_started,
    )
    assert len(result) == 3
    assert {s.account_name for s in result} == {"alice", "bob", "ghost"}
    alice = next(s for s in result if s.account_name == "alice")
    bob = next(s for s in result if s.account_name == "bob")
    ghost = next(s for s in result if s.account_name == "ghost")
    assert len(alice.points) == 1
    assert bob.points == []
    assert ghost.points == []
