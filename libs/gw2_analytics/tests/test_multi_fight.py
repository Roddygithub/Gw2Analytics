"""Tests for :mod:`gw2_analytics.multi_fight`.

Sister suite to ``test_aggregate.py``. Mirrors the in-place ``Fight``
construction pattern so we are not dependent on the EVTC binary
parser's edge-case coverage -- the :class:`MultiFightAggregator`
is fed synthetic ``Agent`` / ``Skill`` / ``EvtcHeader`` ``Fight``
inputs.

Invariants locked down here:

- every cross-field contract listed on
  :class:`gw2_analytics.multi_fight.MultiFightAggregator`
- deterministic ordering: ``fight_ids`` ascending;
  ``combatant_rollups`` sorted by ``account_name``
- stable output for empty / all-NPC / single-fight inputs
- dedup policy (silent skip + log warning) for duplicate ``Fight.id``
- empty-agents drop policy (silently skipped, not in ``fight_ids``)
- the lenient-parser WvW empty-account quirk filter is inherited
  unchanged from :class:`gw2_analytics.aggregate.SingleFightAggregator`
- the returned aggregate is immutable (frozen pydantic model)
"""

from __future__ import annotations

from typing import Final

import pytest

from gw2_analytics.multi_fight import (
    MultiFightAggregator,
)
from gw2_core import (
    Agent,
    EliteSpec,
    EvtcHeader,
    Fight,
    Profession,
    Skill,
)

_MULTI_FIGHT_TEST_LOGGER: Final[str] = "gw2_analytics.multi_fight"

# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------


def _player(
    aid: int,
    *,
    account_name: str,
    name: str = "X",
    subgroup: str = "",
    profession: Profession = Profession.WARRIOR,
    elite: EliteSpec = EliteSpec.BERSERKER,
) -> Agent:
    """Build a player agent for in-place ``Fight`` construction."""
    return Agent(
        id=aid,
        name=name,
        profession=profession,
        elite=elite,
        is_player=True,
        account_name=account_name,
        subgroup=subgroup,
    )


def _npc(aid: int, name: str = "Mob") -> Agent:
    """Build an NPC agent for in-place ``Fight`` construction."""
    return Agent(id=aid, name=name, profession=Profession.UNKNOWN, is_player=False)


def _fight(
    fight_id: str,
    agents: list[Agent],
    skills: list[Skill] | None = None,
    *,
    encounter_id: int = 0,
) -> Fight:
    """Build a fully-formed :class:`Fight` for a multi-fight test."""
    if skills is None:
        skills = []
    return Fight(
        id=fight_id,
        agents=agents,
        skills=skills,
        header=EvtcHeader(
            build_version="20250925",
            encounter_id=encounter_id,
            agent_count=len(agents),
            skill_count=len(skills),
        ),
    )


# ---------------------------------------------------------------------------
# Empty + single-fight cases
# ---------------------------------------------------------------------------


def test_empty_input_yields_zero_everything() -> None:
    """An empty input yields empty aggregates -- no synthesised rows."""
    agg = MultiFightAggregator().aggregate([])
    assert agg.fight_ids == []
    assert agg.total_agents == 0
    assert agg.total_players == 0
    assert agg.combatant_rollups == []


def test_single_fight_replays_single_fight_aggregator() -> None:
    """A single-fight call forwards to ``SingleFightAggregator`` faithfully."""
    fight = _fight(
        "fid-1",
        [
            _player(1, account_name=":a", name="A", subgroup="S"),
            _player(2, account_name=":b", name="B", subgroup="S"),
            _npc(99),
        ],
    )
    agg = MultiFightAggregator().aggregate([fight])
    assert agg.fight_ids == ["fid-1"]
    assert agg.total_agents == 3
    assert agg.total_players == 2
    assert len(agg.combatant_rollups) == 2
    by_acct = {c.account_name: c for c in agg.combatant_rollups}
    assert by_acct[":a"].player_attendance == 1
    assert by_acct[":a"].name == "A"
    assert by_acct[":b"].name == "B"


# ---------------------------------------------------------------------------
# Disjoint / overlapping / full-attendance rolls-up
# ---------------------------------------------------------------------------


def test_two_fights_disjoint_accounts_no_merge() -> None:
    """When no account appears in both fights, the rollup is two rows of 1."""
    fights = [
        _fight("fid-1", [_player(1, account_name=":a", name="A")]),
        _fight("fid-2", [_player(2, account_name=":c", name="C")]),
    ]
    agg = MultiFightAggregator().aggregate(fights)
    assert agg.fight_ids == ["fid-1", "fid-2"]
    assert agg.total_agents == 2
    assert agg.total_players == 2
    assert len(agg.combatant_rollups) == 2
    assert {c.account_name for c in agg.combatant_rollups} == {":a", ":c"}
    assert all(c.player_attendance == 1 for c in agg.combatant_rollups)


def test_overlapping_plays_in_both_fights() -> None:
    """Overlap = merged row with attendance=2; name=last-seen; prof=first-seen."""
    fights = [
        _fight(
            "fid-1",
            [
                _player(
                    1,
                    account_name=":shared",
                    name="Old",
                    profession=Profession.GUARDIAN,
                    elite=EliteSpec.DRAGONHUNTER,
                ),
            ],
        ),
        _fight(
            "fid-2",
            [
                _player(
                    1,
                    account_name=":shared",
                    name="New",
                    profession=Profession.WARRIOR,
                    elite=EliteSpec.BERSERKER,
                ),
            ],
        ),
    ]
    agg = MultiFightAggregator().aggregate(fights)
    assert agg.fight_ids == ["fid-1", "fid-2"]
    assert agg.total_agents == 2
    assert agg.total_players == 2
    assert len(agg.combatant_rollups) == 1
    r = agg.combatant_rollups[0]
    assert r.account_name == ":shared"
    assert r.name == "New"  # last-seen wins
    assert r.profession == Profession.GUARDIAN  # first-seen wins
    assert r.elite == EliteSpec.DRAGONHUNTER  # first-seen wins
    assert r.player_attendance == 2


def test_full_attendance_over_three_fights() -> None:
    """One player across N fights -> player_attendance == len(fight_ids)."""
    fights = [
        _fight(f"fid-{i:02d}", [_player(i, account_name=":a", name=f"A{i}")]) for i in range(3)
    ]
    agg = MultiFightAggregator().aggregate(fights)
    assert agg.fight_ids == ["fid-00", "fid-01", "fid-02"]
    assert agg.total_agents == 3
    assert agg.total_players == 3
    assert agg.combatant_rollups[0].player_attendance == 3


# ---------------------------------------------------------------------------
# Dedup + drop policies
# ---------------------------------------------------------------------------


def test_duplicate_fight_id_logged_and_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same ``Fight.id`` twice -> second occurrence is silent (logged)."""
    fight = _fight("dup-id", [_player(1, account_name=":a", name="A")])
    with caplog.at_level("WARNING", logger=_MULTI_FIGHT_TEST_LOGGER):
        agg = MultiFightAggregator().aggregate([fight, fight])
    assert agg.fight_ids == ["dup-id"]
    assert agg.total_agents == 1
    assert agg.total_players == 1
    assert any("duplicate fight_id" in r.message for r in caplog.records)


def test_empty_agents_fight_silently_dropped() -> None:
    """A fight whose agent block is empty is excluded from ``fight_ids``."""
    fights = [
        _fight("good", [_player(1, account_name=":a", name="A")]),
        _fight("empty", []),
    ]
    agg = MultiFightAggregator().aggregate(fights)
    assert agg.fight_ids == ["good"]
    assert agg.total_agents == 1
    assert agg.total_players == 1


def test_all_npc_multi_fight_run() -> None:
    """NPC-only fights roll up into ``total_agents`` but no player rows."""
    fights = [
        _fight("fid-1", [_npc(1, "Mob1"), _npc(2, "Mob2")]),
        _fight("fid-2", [_npc(3, "Mob3")]),
    ]
    agg = MultiFightAggregator().aggregate(fights)
    assert agg.fight_ids == ["fid-1", "fid-2"]
    assert agg.total_agents == 3
    assert agg.total_players == 0
    assert agg.combatant_rollups == []


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


def test_deterministic_ordering_combatants_by_account_name() -> None:
    """Random input account_name order -> strictly sorted combatant_rollups."""
    fights = [
        _fight(
            "fid-1",
            [
                _player(1, account_name=":zelta", name="Z"),
                _player(2, account_name=":alpha", name="A"),
            ],
        ),
        _fight("fid-3", [_player(3, account_name=":mike", name="M")]),
    ]
    agg = MultiFightAggregator().aggregate(fights)
    assert [c.account_name for c in agg.combatant_rollups] == [
        ":alpha",
        ":mike",
        ":zelta",
    ]
    assert agg.fight_ids == ["fid-1", "fid-3"]


# ---------------------------------------------------------------------------
# frozen + invariant enforcement surfaces
# ---------------------------------------------------------------------------


def test_aggregate_is_frozen_pydantic() -> None:
    """Mutating the returned aggregate is rejected (frozen=True)."""
    fight = _fight("fid", [_player(1, account_name=":a", name="A")])
    agg = MultiFightAggregator().aggregate([fight])
    with pytest.raises((TypeError, ValueError, AttributeError)):
        agg.total_players = 999  # type: ignore[misc]


def test_combatant_rollup_is_frozen_pydantic() -> None:
    """``CombatantRollup`` is also frozen -- no per-row mutation."""
    fight = _fight("fid", [_player(1, account_name=":a", name="A")])
    agg = MultiFightAggregator().aggregate([fight])
    c = agg.combatant_rollups[0]
    with pytest.raises((TypeError, ValueError, AttributeError)):
        c.player_attendance = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Lenient-parser WvW quirk inheriting from SingleFightAggregator
# ---------------------------------------------------------------------------


def test_empty_account_name_player_is_filtered() -> None:
    """Lenient parser WvW quirk (account_name=None + subgroup set) is
    inherited from ``SingleFightAggregator``: counts as NPC, never
    surfaces as a ``CombatantRollup`` row.
    """
    quirk_agent = Agent(
        id=42,
        name="Name",
        profession=Profession.GUARDIAN,
        elite=EliteSpec.DRAGONHUNTER,
        is_player=True,
        account_name=None,
        subgroup="Subgroup-X",
    )
    fight = _fight("fid", [quirk_agent])
    agg = MultiFightAggregator().aggregate([fight])
    assert agg.fight_ids == ["fid"]
    assert agg.total_agents == 1  # counted as agent (later slotted as NPC)
    assert agg.total_players == 0  # but not as a player
    assert agg.combatant_rollups == []


# ---------------------------------------------------------------------------
# Cross-fight invariant math
# ---------------------------------------------------------------------------


def test_cross_fight_math_sum_3_fights_mixed_player_npc() -> None:
    """3 fights with [1p+1npc], [1p], [1p+2npc] -> total_agents=6, total_players=3.

    The shared player across all 3 fights should have attendance=3.
    """
    shared = _player(1, account_name=":shared", name="A")
    fights = [
        _fight("fid-1", [shared, _npc(99)]),  # 1p + 1npc
        _fight("fid-2", [shared]),  # 1p
        _fight("fid-3", [shared, _npc(98), _npc(97)]),  # 1p + 2npc
    ]
    agg = MultiFightAggregator().aggregate(fights)
    assert agg.fight_ids == ["fid-1", "fid-2", "fid-3"]
    assert agg.total_agents == 6  # 2 + 1 + 3
    assert agg.total_players == 3  # 1 + 1 + 1
    assert len(agg.combatant_rollups) == 1
    assert agg.combatant_rollups[0].player_attendance == 3
    assert agg.combatant_rollups[0].account_name == ":shared"


def test_multi_fight_dedups_reconnecting_players_per_fight() -> None:
    """v0.9.6 plan 022: a single account with 2 combatants in 1 fight counts as 1 attendance."""
    fight = _fight(
        "fid-1",
        [
            _player(1, account_name=":acct.1234", name="CharA"),
            _player(2, account_name=":acct.1234", name="CharA"),
        ],
    )
    agg = MultiFightAggregator().aggregate([fight])
    assert agg.fight_ids == ["fid-1"]
    assert agg.total_agents == 2
    assert agg.total_players == 1  # deduped to one attendance
    assert len(agg.combatant_rollups) == 1
    assert agg.combatant_rollups[0].account_name == ":acct.1234"
    assert agg.combatant_rollups[0].player_attendance == 1  # not 2
