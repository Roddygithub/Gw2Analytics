"""Unit tests for :mod:`gw2_analytics.per_player_timeline` (v0.10.3 plan 083 Feature 3A).

The aggregator groups the per-fight events stream by
``source_agent_id`` (filtered to player agents) and per time
bucket, producing one :class:`PerPlayerTimelineSeries` per
player with nested :class:`PerPlayerTimelinePoint` rows. The
tests cover:

- The per-player grouping contract (each player gets a
  distinct series; events are attributed to the source-side
  account).
- The zero-fill contract (every player gets a point at every
  bucket index from 0 to ``max(bucket_index)`` -- the visx
  multi-line chart's array-alignment requirement).
- The sum-preservation contract (no damage / healing / strip
  events are dropped during aggregation).
- The contiguous-points contract (every 2 adjacent points
  tile the timeline without overlap or gap).
- The NPC filter (NPC agents are excluded; only
  ``is_player=True`` + non-empty ``account_name`` agents
  produce a series).
- The deterministic-ordering contract (highest total_damage
  first; ties broken by ascending ``account_name``).
- The empty-input contract (zero events -> empty list; no
  placeholder series).

The aggregator is **pure** (no I/O, no DB) so the tests are
straight function-call assertions on synthetic ``Event`` +
``OrmFightAgent``-like objects. No fixtures, no async, no DB.
"""

from __future__ import annotations

import pytest

import gw2_analytics.per_player_timeline as _per_player_timeline_mod
from gw2_analytics.per_player_timeline import (
    PerPlayerTimelineAggregator,
    PerPlayerTimelinePoint,
    PerPlayerTimelineSeries,
)
from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent

# ---------------------------------------------------------------------------
# Minimal in-memory agent stand-in (avoids the SQLAlchemy ORM
# dependency in the unit tests). The aggregator only reads
# ``is_player`` / ``account_name`` / ``name`` / ``agent_id`` via
# ``getattr``, so any object with those 4 attributes works.
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Drop-in stand-in for ``OrmFightAgent`` (reads 4 attrs only)."""

    def __init__(
        self,
        agent_id: int,
        account_name: str | None,
        is_player: bool,
        name: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.account_name = account_name
        self.is_player = is_player
        self.name = name


def _dmg(time_ms: int, src: int, value: int) -> DamageEvent:
    # ``target_agent_id`` + ``skill_id`` are required by the
    # Pydantic model but unused by the per-player aggregator
    # (which keys on ``source_agent_id`` only). The sentinel
    # ``0`` mirrors the parser's "unknown / ungrouped"
    # default for both fields.
    return DamageEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=0,
        skill_id=0,
        damage=value,
    )


def _heal(time_ms: int, src: int, value: int) -> HealingEvent:
    return HealingEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=0,
        skill_id=0,
        healing=value,
    )


def _strip(time_ms: int, src: int, value: int) -> BuffRemovalEvent:
    return BuffRemovalEvent(
        time_ms=time_ms,
        source_agent_id=src,
        target_agent_id=0,
        skill_id=0,
        buff_removal=value,
    )


# ---------------------------------------------------------------------------
# Per-player grouping
# ---------------------------------------------------------------------------


def test_two_players_get_two_series_with_source_side_attribution() -> None:
    """Two player agents each generating events -> two series, one per player.

    The events from player A land in series A; events from
    player B land in series B. The aggregator is per-SOURCE
    (the player who generated the event), not per-target.
    """
    agents = [
        _FakeAgent(agent_id=1, account_name=":a.1", is_player=True, name="Alice"),
        _FakeAgent(agent_id=2, account_name=":b.2", is_player=True, name="Bob"),
    ]
    events: list[Event] = [
        _dmg(1_000, 1, 1_000),  # Alice @ 1s
        _dmg(1_500, 2, 2_000),  # Bob @ 1.5s
        _dmg(2_000, 1, 500),  # Alice @ 2s
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert len(series) == 2
    # Deterministic ordering: highest total_damage first. Bob
    # has 2_000 (one event), Alice has 1_500 (two events). Bob
    # wins.
    assert series[0].account_name == ":b.2"
    assert series[0].name == "Bob"
    assert series[1].account_name == ":a.1"
    assert series[1].name == "Alice"
    # Bob's series: 1 point at bucket 1 (time 1000-1999), zero
    # elsewhere. The zero-fill at bucket 0 + 2 makes Bob's
    # series length-3 (the aligned-array contract).
    assert len(series[0].points) == 3
    assert series[0].points[0].total_damage == 0
    assert series[0].points[1].total_damage == 2_000
    assert series[0].points[2].total_damage == 0
    # Alice's series: 1 point at bucket 1 (time 1000-1999) +
    # 1 point at bucket 2 (time 2000-2999), zero elsewhere.
    assert len(series[1].points) == 3
    assert series[1].points[0].total_damage == 0
    assert series[1].points[1].total_damage == 1_000
    assert series[1].points[2].total_damage == 500


def test_npc_agents_are_filtered_out() -> None:
    """NPC agents (is_player=False) are excluded from the source map.

    The aggregator builds the source_map from the
    ``is_player=True`` agents only. Events whose
    ``source_agent_id`` maps to an NPC are silently dropped
    (the per-target roll-up would still see them, but the
    per-source-side attribution only counts player agents --
    the :func:`_persist_player_summaries` contract).
    """
    agents = [
        _FakeAgent(agent_id=1, account_name=":a.1", is_player=True, name="Alice"),
        _FakeAgent(agent_id=99, account_name=None, is_player=False, name="NPC"),
    ]
    events: list[Event] = [
        _dmg(1_000, 1, 1_000),  # Alice's event
        _dmg(1_500, 99, 9_999),  # NPC's event -- dropped
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert len(series) == 1
    assert series[0].account_name == ":a.1"
    # The NPC's 9_999 damage does NOT land in Alice's series.
    assert sum(p.total_damage for p in series[0].points) == 1_000


def test_agent_with_empty_account_name_is_filtered_out() -> None:
    """An agent with ``is_player=True`` but empty ``account_name`` is dropped.

    Mirrors the per-source-side filter in
    :func:`apps.api.services._persist_player_summaries`:
    ``is_player and a.account_name`` (the empty string is
    falsy). A registered player agent without an arcdps
    account name (rare but possible) is NOT attributed to
    any series.
    """
    agents = [
        _FakeAgent(agent_id=1, account_name="", is_player=True, name="NoAccount"),
        _FakeAgent(agent_id=2, account_name=":b.2", is_player=True, name="Bob"),
    ]
    events: list[Event] = [
        _dmg(1_000, 1, 1_000),  # NoAccount's event -- dropped
        _dmg(1_500, 2, 2_000),  # Bob's event
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert len(series) == 1
    assert series[0].account_name == ":b.2"


# ---------------------------------------------------------------------------
# Zero-fill + array-alignment
# ---------------------------------------------------------------------------


def test_zero_fill_aligns_all_series_to_max_bucket_index() -> None:
    """All series have the same point count (the visx multi-line chart contract).

    Player A generates events at bucket 0; player B generates
    events at bucket 5. The aggregator zero-fills both series
    from 0 to 5 (the max bucket index across all players), so
    the 2 series have the same length AND every point at
    every bucket index. Without zero-fill, A's series would
    have 1 point and B's would have 1 point, but the
    visx-aligned array would break.

    Note on the sort order: the deterministic-ordering
    contract is ``(-total_damage, account_name)``, so
    Bob (total 200) lands as ``series[0]`` and Alice
    (total 100) lands as ``series[1]``. The test asserts
    the per-account damage values via the account_name
    so the assertions are robust to the sort order.
    """
    agents = [
        _FakeAgent(agent_id=1, account_name=":a.1", is_player=True),
        _FakeAgent(agent_id=2, account_name=":b.2", is_player=True),
    ]
    events: list[Event] = [
        _dmg(0, 1, 100),  # Alice @ bucket 0
        _dmg(5_000, 2, 200),  # Bob @ bucket 5
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    # Both series have 6 points (buckets 0..5 inclusive).
    assert len(series) == 2
    assert len(series[0].points) == 6
    assert len(series[1].points) == 6
    # Deterministic-ordering: Bob (200) > Alice (100) ->
    # series[0] is Bob, series[1] is Alice.
    assert series[0].account_name == ":b.2"
    assert series[1].account_name == ":a.1"
    # Bob: only bucket 5 has damage; buckets 0..4 are zero.
    for i in range(5):
        assert series[0].points[i].total_damage == 0
    assert series[0].points[5].total_damage == 200
    # Alice: only bucket 0 has damage; buckets 1..5 are zero.
    for i in range(1, 6):
        assert series[1].points[i].total_damage == 0
    assert series[1].points[0].total_damage == 100


def test_contiguous_points_per_series() -> None:
    """Every 2 adjacent points in a series tile the timeline without overlap or gap.

    Pins the per-series contiguous-points contract. The
    aggregator's zero-fill at index ``max(bucket_index)`` is
    what makes the contract hold: a missing bucket between 2
    events would leave a gap, and a duplicate bucket would
    leave an overlap.
    """
    agents = [_FakeAgent(agent_id=1, account_name=":a.1", is_player=True)]
    events: list[Event] = [
        _dmg(0, 1, 100),
        _dmg(3_000, 1, 200),
        _dmg(7_000, 1, 300),
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert len(series) == 1
    assert len(series[0].points) == 8  # buckets 0..7
    for i in range(7):
        assert series[0].points[i].window_end_ms == series[0].points[i + 1].window_start_ms


# ---------------------------------------------------------------------------
# 3 magnitudes (damage + healing + strip) accumulate independently
# ---------------------------------------------------------------------------


def test_damage_healing_and_strip_accumulate_independently() -> None:
    """The 3 per-axis magnitudes sum into the same bucket independently.

    A single player generating damage + healing + strip events
    in the same bucket gets all 3 totals on the same point
    (NOT a multi-point split). The v0.6.0 dual-emit case
    (a single cbtevent that yields BOTH a HealingEvent AND a
    BuffRemovalEvent) is a parser concern, not an aggregator
    concern; here we explicitly feed 3 events.
    """
    agents = [_FakeAgent(agent_id=1, account_name=":a.1", is_player=True)]
    events: list[Event] = [
        _dmg(1_000, 1, 1_000),
        _heal(1_000, 1, 500),
        _strip(1_000, 1, 10),
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert len(series) == 1
    # All 3 events land at bucket 1 (time 1000-1999).
    assert series[0].points[1].total_damage == 1_000
    assert series[0].points[1].total_healing == 500
    assert series[0].points[1].total_buff_removal == 10
    # Bucket 0 is zero-filled.
    assert series[0].points[0].total_damage == 0
    assert series[0].points[0].total_healing == 0
    assert series[0].points[0].total_buff_removal == 0


# ---------------------------------------------------------------------------
# Sum-preservation invariants (the 3 per-kind totals)
# ---------------------------------------------------------------------------


def test_sum_preservation_damage() -> None:
    """Per-series sum of points.total_damage == per-series event-damage sum.

    No damage events are dropped. Checked post-construct via
    ``_check_invariants``. A buggy aggregator (missed
    isinstance check) would fail this test.
    """
    agents = [_FakeAgent(agent_id=1, account_name=":a.1", is_player=True)]
    events: list[Event] = [
        _dmg(0, 1, 100),
        _dmg(2_500, 1, 200),
        _dmg(7_500, 1, 300),
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert sum(p.total_damage for p in series[0].points) == 600


def test_sum_preservation_healing() -> None:
    """Per-series sum of points.total_healing == per-series event-healing sum."""
    agents = [_FakeAgent(agent_id=1, account_name=":a.1", is_player=True)]
    events: list[Event] = [
        _heal(0, 1, 100),
        _heal(2_500, 1, 200),
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert sum(p.total_healing for p in series[0].points) == 300


def test_sum_preservation_strip() -> None:
    """Per-series sum of points.total_buff_removal == per-series event-buff_removal sum."""
    agents = [_FakeAgent(agent_id=1, account_name=":a.1", is_player=True)]
    events: list[Event] = [
        _strip(0, 1, 5),
        _strip(2_500, 1, 10),
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert sum(p.total_buff_removal for p in series[0].points) == 15


# ---------------------------------------------------------------------------
# Empty + window_s validation
# ---------------------------------------------------------------------------


def test_empty_events_returns_empty_list() -> None:
    """Zero events + zero agents -> empty list (no placeholders, no synth rows)."""
    series = PerPlayerTimelineAggregator().aggregate([], [], window_s=1)
    assert series == []


def test_zero_agents_with_events_returns_empty_list() -> None:
    """Events with zero player agents -> empty list.

    All events are NPC-sourced (no player agent to attribute
    to). The per-source-side filter drops them all.
    """
    events: list[Event] = [_dmg(1_000, 1, 1_000)]
    series = PerPlayerTimelineAggregator().aggregate(events, [], window_s=1)
    assert series == []


def test_window_s_must_be_positive() -> None:
    """``window_s < 1`` raises ``ValueError`` (matches PerFightTimelineAggregator)."""
    with pytest.raises(ValueError, match="window_s must be >= 1"):
        PerPlayerTimelineAggregator().aggregate([], [], window_s=0)
    with pytest.raises(ValueError, match="window_s must be >= 1"):
        PerPlayerTimelineAggregator().aggregate([], [], window_s=-5)


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


def test_series_sorted_by_total_damage_descending() -> None:
    """The output list is sorted by ``(-total_damage, account_name)``.

    Pin the deterministic-ordering contract. Player A has
    more total damage than player B; A lands first. A
    secondary tie-break on ascending ``account_name``
    resolves the "equal damage" case.
    """
    agents = [
        _FakeAgent(agent_id=1, account_name=":a.1", is_player=True),
        _FakeAgent(agent_id=2, account_name=":b.2", is_player=True),
    ]
    events: list[Event] = [
        _dmg(1_000, 2, 5_000),  # Bob @ 5k
        _dmg(2_000, 1, 10_000),  # Alice @ 10k
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    assert series[0].account_name == ":a.1"  # higher damage
    assert series[1].account_name == ":b.2"


def test_series_sorted_by_account_name_on_equal_damage() -> None:
    """When 2 players have equal total damage, ties are broken by ascending ``account_name``."""
    agents = [
        _FakeAgent(agent_id=1, account_name=":z.99", is_player=True),
        _FakeAgent(agent_id=2, account_name=":a.1", is_player=True),
    ]
    events: list[Event] = [
        _dmg(1_000, 1, 1_000),
        _dmg(1_000, 2, 1_000),
    ]
    series = PerPlayerTimelineAggregator().aggregate(events, agents, window_s=1)
    # Equal damage -> :a.1 (lower account_name) lands first.
    assert series[0].account_name == ":a.1"
    assert series[1].account_name == ":z.99"


# ---------------------------------------------------------------------------
# Public surface (re-export + __all__)
# ---------------------------------------------------------------------------


def test_module_exports() -> None:
    """``__all__`` exports the 3 public names (the aggregator + 2 schemas)."""
    assert _per_player_timeline_mod.__all__ == [
        "PerPlayerTimelineAggregator",
        "PerPlayerTimelinePoint",
        "PerPlayerTimelineSeries",
    ]
    assert isinstance(
        _per_player_timeline_mod.PerPlayerTimelineAggregator(),
        PerPlayerTimelineAggregator,
    )
    assert isinstance(
        PerPlayerTimelinePoint(window_start_ms=0, window_end_ms=1000),
        PerPlayerTimelinePoint,
    )
    assert isinstance(
        PerPlayerTimelineSeries(account_name=":a.1", name="Alice", points=[]),
        PerPlayerTimelineSeries,
    )
