"""Tests for :mod:`gw2_analytics.aggregate`.

These tests construct :class:`~gw2_core.Fight` records in-place from
:class:`~gw2_core.Agent` / :class:`~gw2_core.Skill` /
:class:`~gw2_core.EvtcHeader` instances so we are not dependent on the
EVTC binary parser's edge-case coverage -- the
:class:`SingleFightAggregator` is tested at the unit level, fed
synthetic (``Agent`` / ``Skill`` / ``EvtcHeader``) ``Fight`` inputs.

The invariants we lock down here:

- every cross-field contract listed on
  :class:`gw2_analytics.aggregate.SingleFightAggregator`
- deterministic ordering: ``combatants`` by ``(account_name, name)``,
  ``groups`` by ``subgroup``, ``skill_catalog`` by ``Skill.id``
- stable output for empty / all-NPC inputs (no KeyError on the
  defaultdict lookup; ``combatants=[]``, ``skill_catalog=[]``)
- the returned aggregate is immutable (frozen pydantic model)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from gw2_analytics.aggregate import (
    SingleFightAggregator,
)
from gw2_core import (
    Agent,
    EliteSpec,
    EvtcHeader,
    Fight,
    GameType,
    Profession,
    Skill,
)

_FIXED_FIGHT_ID: Final[str] = "deadbeef" * 8  # 64 hex chars; SHA-256-shaped sentinel


# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------


def _player(
    aid: int,
    *,
    account_name: str,
    name: str,
    subgroup: str,
    profession: Profession,
    elite: EliteSpec,
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
    agents: list[Agent],
    skills: list[Skill] | None = None,
    *,
    encounter_id: int = 0,
) -> Fight:
    """Build a fully-formed :class:`Fight` for an aggregate test."""
    if skills is None:
        skills = []
    return Fight(
        id=_FIXED_FIGHT_ID,
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
# Empty / single-row cases
# ---------------------------------------------------------------------------


def test_empty_fight_yields_zero_everything() -> None:
    """An empty input yields empty aggregates -- no synthesised rows."""
    agg = SingleFightAggregator().aggregate(_fight([]))
    assert agg.fight_id == _FIXED_FIGHT_ID
    assert agg.encounter_id == 0
    assert agg.agent_count == 0
    assert agg.player_count == 0
    assert agg.npc_count == 0
    assert agg.skill_count == 0
    assert agg.combatants == []
    assert agg.groups == []
    assert agg.skill_catalog == []


def test_single_player_no_subgroup_rolls_into_empty_subgroup_bucket() -> None:
    """A single player with ``subgroup=''`` gets its own GroupSummary.

    The parser surfaces ``subgroup=None`` for NPCs and the empty string
    for players-with-no-squad-position; the aggregator flattens this
    so the resulting schema has string-only subgroup fields.
    """
    agg = SingleFightAggregator().aggregate(
        _fight(
            [
                _player(
                    1,
                    account_name=":acc.1",
                    name="G1",
                    subgroup="",
                    profession=Profession.GUARDIAN,
                    elite=EliteSpec.DRAGONHUNTER,
                ),
            ],
        ),
    )
    assert agg.player_count == 1
    assert agg.npc_count == 0
    assert agg.agent_count == 1
    assert len(agg.combatants) == 1
    c = agg.combatants[0]
    assert c.agent_id == 1
    assert c.account_name == ":acc.1"
    assert c.name == "G1"
    assert c.subgroup == ""
    assert c.profession == Profession.GUARDIAN
    assert c.elite == EliteSpec.DRAGONHUNTER
    assert len(agg.groups) == 1
    assert agg.groups[0].subgroup == ""
    assert agg.groups[0].combatant_count == 1
    assert agg.groups[0].account_names == [":acc.1"]


def test_single_npc_only_yields_no_combatants_and_no_groups() -> None:
    """NPCs surface in the counts but do not appear in ``combatants``."""
    agg = SingleFightAggregator().aggregate(_fight([_npc(99)]))
    assert agg.agent_count == 1
    assert agg.player_count == 0
    assert agg.npc_count == 1
    assert agg.combatants == []
    # No player -> no group bucket (even the empty-subgroup bucket only
    # exists when at least one combatant lands in it).
    assert agg.groups == []


# ---------------------------------------------------------------------------
# Mixed player / NPC ordering
# ---------------------------------------------------------------------------


def test_combatants_are_sorted_by_account_name_then_name() -> None:
    """Deterministic ordering: (account_name, name) ascending."""
    agg = SingleFightAggregator().aggregate(
        _fight(
            [
                _player(
                    2,
                    account_name=":acc.2",
                    name="N1",
                    subgroup="Sub 2",
                    profession=Profession.NECROMANCER,
                    elite=EliteSpec.REAPER,
                ),
                _player(
                    1,
                    account_name=":acc.1",
                    name="G1",
                    subgroup="Sub 1",
                    profession=Profession.GUARDIAN,
                    elite=EliteSpec.DRAGONHUNTER,
                ),
                _npc(99),
            ],
        ),
    )
    assert agg.agent_count == 3
    assert agg.player_count == 2
    assert agg.npc_count == 1
    assert len(agg.combatants) == 2
    assert agg.combatants[0].account_name == ":acc.1"
    assert agg.combatants[1].account_name == ":acc.2"


def test_groups_are_sorted_by_subgroup_string() -> None:
    """Group rows ordered by ``subgroup`` (alphabetical)."""
    agents = [
        _player(
            i,
            account_name=f":acc.{i}",
            name=f"P{i}",
            subgroup=("Zeta" if i % 2 == 0 else "Alpha"),
            profession=Profession.WARRIOR,
            elite=EliteSpec.BERSERKER,
        )
        for i in range(1, 5)
    ]
    agg = SingleFightAggregator().aggregate(_fight(agents))
    assert len(agg.groups) == 2
    assert agg.groups[0].subgroup == "Alpha"
    assert agg.groups[1].subgroup == "Zeta"


def test_skill_catalog_is_sorted_by_skill_id() -> None:
    """The catalog reflects the parser's input -- but always sorted by id."""
    agg = SingleFightAggregator().aggregate(
        _fight(
            [],
            skills=[Skill(id=202, name="Burning"), Skill(id=101, name="Whirlwind")],
        ),
    )
    assert agg.skill_count == 2
    assert [e.id for e in agg.skill_catalog] == [101, 202]
    assert agg.skill_catalog[0].name == "Whirlwind"
    assert agg.skill_catalog[1].name == "Burning"


# ---------------------------------------------------------------------------
# Group roll-up invariants
# ---------------------------------------------------------------------------


def test_multiple_combatants_same_subgroup_rolls_into_one_group() -> None:
    """Three players in the same squad bucket → one row with three names."""
    agents = [
        _player(
            i,
            account_name=f":acc.{i}",
            name=f"P{i}",
            subgroup="Squad 1",
            profession=Profession.WARRIOR,
            elite=EliteSpec.BERSERKER,
        )
        for i in (3, 1, 2)  # intentionally unsorted input
    ]
    agg = SingleFightAggregator().aggregate(_fight(agents))
    assert len(agg.groups) == 1
    assert agg.groups[0].subgroup == "Squad 1"
    assert agg.groups[0].combatant_count == 3
    assert agg.groups[0].account_names == [":acc.1", ":acc.2", ":acc.3"]


def test_group_combatant_count_matches_actual_combatants_in_bucket() -> None:
    """Cross-field invariant: ``GroupSummary.combatant_count`` is honest."""
    agents = [
        _player(
            i,
            account_name=f":acc.{i}",
            name=f"P{i}",
            subgroup="Squad 1" if i % 2 == 0 else "Squad 2",
            profession=Profession.WARRIOR,
            elite=EliteSpec.BERSERKER,
        )
        for i in range(1, 11)
    ]
    agg = SingleFightAggregator().aggregate(_fight(agents))
    assert agg.player_count == 10
    assert len(agg.groups) == 2
    for g in agg.groups:
        expected = sum(1 for c in agg.combatants if c.subgroup == g.subgroup)
        assert g.combatant_count == expected  # invariant cross-check


def test_group_subgroup_is_empty_string_not_none_for_player_with_empty_squad() -> None:
    """The schema flattens ``Optional[str]`` to ``str`` -- no ``None`` slips in."""
    agg = SingleFightAggregator().aggregate(
        _fight(
            [
                _player(
                    1,
                    account_name=":a",
                    name="A",
                    subgroup="",
                    profession=Profession.GUARDIAN,
                    elite=EliteSpec.DRAGONHUNTER,
                ),
            ],
        ),
    )
    assert all(isinstance(g.subgroup, str) for g in agg.groups)
    assert all(isinstance(c.subgroup, str) for c in agg.combatants)


def test_player_with_empty_account_name_is_filtered() -> None:
    """Lenient-parser WvW quirk player (account_name=None + subgroup set).

    Per the aggregator's documented ``player_rows`` filter, this agent is
    dropped from ``combatants`` (we cannot dedupe across uploads without
    a stable identifier) but its presence is still reflected in
    ``agent_count``: it counts as an NPC for the purposes of
    ``player_count + npc_count == agent_count``.
    """
    quirk_agent = Agent(
        id=42,
        name="Name",
        profession=Profession.GUARDIAN,
        elite=EliteSpec.DRAGONHUNTER,
        is_player=True,
        account_name=None,  # the lenient-parser quirk
        subgroup="Subgroup-X",
    )
    agg = SingleFightAggregator().aggregate(_fight([quirk_agent]))
    assert agg.agent_count == 1
    assert agg.player_count == 0
    assert agg.npc_count == 1
    assert agg.combatants == []
    # No player reached the group roll-up -> empty groups list.
    assert agg.groups == []


def test_aggregate_rejects_empty_fight_id_via_model_construct() -> None:
    """Defense-in-depth: even if upstream bypasses Pydantic validation
    via ``model_construct``, the aggregator refuses to construct an
    aggregate for an empty-id fight.
    """
    empty_fight = Fight.model_construct(
        id="",
        agents=[],
        skills=[],
        header=EvtcHeader.model_construct(
            build_version="20250925",
            encounter_id=0,
            agent_count=0,
            skill_count=0,
        ),
        started_at=datetime(1970, 1, 1, tzinfo=UTC),
        game_type=GameType.WVW,
    )
    with pytest.raises(ValueError, match=r"fight\.id must be non-empty"):
        SingleFightAggregator().aggregate(empty_fight)


# ---------------------------------------------------------------------------
# Frozen-pydantic + cross-field invariants
# ---------------------------------------------------------------------------


def test_aggregate_is_frozen_pydantic() -> None:
    """Mutating the returned aggregate is rejected (frozen=True)."""
    agg = SingleFightAggregator().aggregate(
        _fight(
            [
                _player(
                    1,
                    account_name=":a",
                    name="A",
                    subgroup="Squad",
                    profession=Profession.GUARDIAN,
                    elite=EliteSpec.DRAGONHUNTER,
                ),
            ],
        ),
    )
    with pytest.raises((TypeError, ValueError, AttributeError)):
        agg.player_count = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# propagate-from-Fight fields
# ---------------------------------------------------------------------------


def test_encounter_id_propagates_from_header() -> None:
    """``FightAggregate.encounter_id`` mirrors ``Fight.header.encounter_id``."""
    agg = SingleFightAggregator().aggregate(_fight([], encounter_id=0xBEEF))
    assert agg.encounter_id == 0xBEEF


def test_fight_id_propagates_verbatim() -> None:
    """``FightAggregate.fight_id`` mirrors ``Fight.id`` 1:1."""
    custom_id = "custom-id-string-123"
    fight = Fight(
        id=custom_id,
        agents=[],
        skills=[],
        header=EvtcHeader(build_version="20250925", agent_count=0, skill_count=0),
    )
    agg = SingleFightAggregator().aggregate(fight)
    assert agg.fight_id == custom_id
