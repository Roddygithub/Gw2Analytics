"""Tests for :mod:`gw2_analytics.player_profile`.

Sister suite to ``test_multi_fight.py``. Mirrors the in-place
``FightContribution`` construction pattern so we are not dependent on
the EVTC binary parser's edge-case coverage -- the
:class:`PlayerProfileAggregator` is fed synthetic
``FightContribution`` inputs.

Invariants locked down here:

- every cross-field contract listed on
  :class:`gw2_analytics.player_profile.PlayerProfileAggregator`
- deterministic ordering: highest ``total_damage`` first, ties
  broken by ascending ``account_name``
- stable output for empty / single-contribution inputs
- dedup policy on ``(account_name, fight_id)`` (silent fold)
- ``fights_attended == len(attended_fight_ids)`` invariant
- the returned profile is immutable (frozen pydantic model)
"""

from __future__ import annotations

import pytest

from gw2_analytics.player_profile import (
    FightContribution,
    PlayerProfileAggregator,
)
from gw2_core import EliteSpec, Profession


def _contrib(
    fight_id: str,
    account_name: str,
    *,
    name: str = "X",
    profession: Profession = Profession.WARRIOR,
    elite: EliteSpec = EliteSpec.BERSERKER,
    total_damage: int = 0,
    total_healing: int = 0,
    total_buff_removal: int = 0,
) -> FightContribution:
    """Build one synthetic :class:`FightContribution` for the test."""
    return FightContribution(
        fight_id=fight_id,
        account_name=account_name,
        name=name,
        profession=profession,
        elite=elite,
        total_damage=total_damage,
        total_healing=total_healing,
        total_buff_removal=total_buff_removal,
    )


# ---------------------------------------------------------------------------
# Empty + single-contribution cases
# ---------------------------------------------------------------------------


def test_empty_input_yields_no_profiles() -> None:
    """An empty input yields ``[]`` -- no synthesised rows."""
    profiles = PlayerProfileAggregator().aggregate([])
    assert profiles == []


def test_single_contribution_yields_one_profile() -> None:
    """A single contribution lands as a one-row profile with all totals."""
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib(
                "fid-1",
                ":a",
                name="Alice",
                profession=Profession.GUARDIAN,
                elite=EliteSpec.DRAGONHUNTER,
                total_damage=1_000,
                total_healing=500,
                total_buff_removal=200,
            ),
        ],
    )
    assert len(profiles) == 1
    p = profiles[0]
    assert p.account_name == ":a"
    assert p.name == "Alice"
    assert p.profession == Profession.GUARDIAN
    assert p.elite == EliteSpec.DRAGONHUNTER
    assert p.fights_attended == 1
    assert p.total_damage == 1_000
    assert p.total_healing == 500
    assert p.total_buff_removal == 200
    assert p.attended_fight_ids == ["fid-1"]


# ---------------------------------------------------------------------------
# Cross-fight + dedup
# ---------------------------------------------------------------------------


def test_two_fights_same_player_merges() -> None:
    """Same account across two fights -> one profile with attendance=2."""
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib("fid-1", ":a", total_damage=500, total_healing=100),
            _contrib("fid-2", ":a", total_damage=700, total_healing=200),
        ],
    )
    assert len(profiles) == 1
    p = profiles[0]
    assert p.account_name == ":a"
    assert p.fights_attended == 2
    assert p.total_damage == 1_200
    assert p.total_healing == 300
    assert p.attended_fight_ids == ["fid-1", "fid-2"]


def test_two_disjoint_players_two_profiles() -> None:
    """Disjoint accounts -> two profiles, sorted by total_damage DESC."""
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib("fid-1", ":a", total_damage=500),
            _contrib("fid-1", ":b", total_damage=1_000),
        ],
    )
    assert len(profiles) == 2
    assert [p.account_name for p in profiles] == [":b", ":a"]
    assert [p.total_damage for p in profiles] == [1_000, 500]


def test_dedup_same_fight_account_pair_accumulates_magnitudes() -> None:
    """v0.9.6 plan 023: same (account_name, fight_id) twice -> magnitudes accumulate.

    The ``attended_fight_ids`` set still collapses to a single
    fight, so ``fights_attended`` stays 1, but the per-character
    totals are summed (a class swap / reconnect emits a new
    agent under the same account_name).
    """
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib("fid-1", ":a", total_damage=500, total_healing=100),
            _contrib("fid-1", ":a", total_damage=300, total_healing=200, total_buff_removal=10),
        ],
    )
    assert len(profiles) == 1
    p = profiles[0]
    assert p.account_name == ":a"
    assert p.fights_attended == 1
    assert p.total_damage == 800
    assert p.total_healing == 300
    assert p.total_buff_removal == 10
    assert p.attended_fight_ids == ["fid-1"]


def test_player_profile_accumulates_per_character_contributions() -> None:
    """v0.9.6 plan 023: 2 characters in 1 fight contribute their magnitudes."""
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib(
                "fid-1",
                ":acct.1234",
                name="CharA",
                profession=Profession.WARRIOR,
                elite=EliteSpec.BERSERKER,
                total_damage=1000,
                total_healing=0,
                total_buff_removal=0,
            ),
            _contrib(
                "fid-1",
                ":acct.1234",
                name="CharB",
                profession=Profession.MESMER,
                elite=EliteSpec.MIRAGE,
                total_damage=500,
                total_healing=200,
                total_buff_removal=10,
            ),
        ],
    )
    assert len(profiles) == 1
    p = profiles[0]
    assert p.fights_attended == 1  # set semantics
    assert p.total_damage == 1500  # 1000 + 500
    assert p.total_healing == 200  # 0 + 200
    assert p.total_buff_removal == 10  # 0 + 10
    assert p.name == "CharB"  # last-seen name wins


# ---------------------------------------------------------------------------
# Identity rules (first-seen profession/elite, last-seen name)
# ---------------------------------------------------------------------------


def test_first_seen_profession_and_elite_anchor() -> None:
    """A player who switches class stays anchored to the first-seen pair."""
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib(
                "fid-1",
                ":shared",
                name="Old",
                profession=Profession.GUARDIAN,
                elite=EliteSpec.DRAGONHUNTER,
                total_damage=100,
            ),
            _contrib(
                "fid-2",
                ":shared",
                name="New",
                profession=Profession.WARRIOR,
                elite=EliteSpec.BERSERKER,
                total_damage=200,
            ),
        ],
    )
    assert len(profiles) == 1
    p = profiles[0]
    assert p.profession == Profession.GUARDIAN  # first-seen wins
    assert p.elite == EliteSpec.DRAGONHUNTER  # first-seen wins
    assert p.name == "New"  # last-seen wins
    assert p.fights_attended == 2
    assert p.total_damage == 300


# ---------------------------------------------------------------------------
# Ordering: total_damage DESC, account_name ASC tie-break
# ---------------------------------------------------------------------------


def test_deterministic_ordering_by_total_damage_desc() -> None:
    """``(-total_damage, account_name)`` sort is stable + ascending tie-break."""
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib("fid-1", ":zelta", total_damage=300),
            _contrib("fid-1", ":alpha", total_damage=300),
            _contrib("fid-1", ":mike", total_damage=1_000),
        ],
    )
    assert [p.account_name for p in profiles] == [":mike", ":alpha", ":zelta"]
    # Tie on total_damage (300) is broken by ascending account_name:
    # ``:alpha`` < ``:zelta`` lexicographically.


# ---------------------------------------------------------------------------
# Invariant enforcement
# ---------------------------------------------------------------------------


def test_profile_is_frozen_pydantic() -> None:
    """Mutating the returned profile is rejected (``frozen=True``)."""
    profiles = PlayerProfileAggregator().aggregate(
        [_contrib("fid-1", ":a", total_damage=100)],
    )
    p = profiles[0]
    with pytest.raises((TypeError, ValueError, AttributeError)):
        p.total_damage = 999  # type: ignore[misc]


def test_fights_attended_matches_attended_fight_ids_length() -> None:
    """The ``fights_attended == len(attended_fight_ids)`` invariant holds."""
    profiles = PlayerProfileAggregator().aggregate(
        [
            _contrib("fid-1", ":a", total_damage=100),
            _contrib("fid-2", ":a", total_damage=200),
            _contrib("fid-3", ":a", total_damage=300),
        ],
    )
    p = profiles[0]
    assert p.fights_attended == len(p.attended_fight_ids) == 3
    assert p.total_damage == 600
