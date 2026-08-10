from __future__ import annotations

from typing import Any

from gw2_analytics.ei_compare import _skill_stats, compare_elite_insights
from gw2_core import (
    Agent,
    BoonApplyEvent,
    CombatOutcomeEvent,
    DamageEvent,
    DeathEvent,
    EliteSpec,
    EvtcHeader,
    Fight,
    Profession,
)


def test_compare_elite_insights_keeps_first_anonymous_agent_for_shared_instance() -> None:
    fight = Fight(
        id="fight",
        agents=[
            Agent(
                id=99,
                name="Named Player",
                profession=Profession.GUARDIAN,
                elite=EliteSpec.DRAGONHUNTER,
                is_player=True,
                account_name=":Named.1234",
                instance_id=3994,
            ),
            Agent(
                id=1,
                name="Chronomancienne",
                profession=Profession.MESMER,
                elite=EliteSpec.CHRONOMANCER,
                is_player=True,
                instance_id=3994,
            ),
            Agent(
                id=2,
                name="Virtuose",
                profession=Profession.MESMER,
                elite=EliteSpec.VIRTUOSO,
                is_player=True,
                instance_id=3994,
            ),
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Non Squad Player 5",
                "instanceID": 3994,
                "name": "Chronomancer pl-3994",
                "defenses": [{"deadCount": 2}],
            }
        ]
    }
    events = [
        DeathEvent(time_ms=1, source_agent_id=1, target_agent_id=0, skill_id=0),
        DeathEvent(time_ms=2, source_agent_id=2, target_agent_id=0, skill_id=0),
    ]

    result = compare_elite_insights(fight, expected, events)

    assert result["differences"] == {}


def test_compare_elite_insights_selects_split_account_agent_by_name() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=2, duration_ms=10_000),
        agents=[
            Agent(
                id=1,
                name="First Character",
                profession=Profession.NECROMANCER,
                elite=EliteSpec.RITUALIST,
                is_player=True,
                account_name=":Player.1234",
                subgroup="1",
                instance_id=1111,
            ),
            Agent(
                id=1,
                name="Second Character",
                profession=Profession.WARRIOR,
                elite=EliteSpec.SPELLBREAKER,
                is_player=True,
                account_name=":Player.1234",
                subgroup="1",
                instance_id=1111,
            ),
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 0,
                "name": "First Character",
                "profession": "Ritualist",
                "group": 1,
            },
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 1,
                "name": "Second Character",
                "profession": "Spellbreaker",
                "group": 1,
            },
        ]
    }

    result = compare_elite_insights(fight, expected, [])

    assert result["differences"] == {}


def test_compare_elite_insights_keeps_team_for_character_swap_slices() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=2, duration_ms=10_000),
        agents=[
            Agent(
                id=1,
                name="First Character",
                profession=Profession.NECROMANCER,
                elite=EliteSpec.RITUALIST,
                is_player=True,
                account_name=":Player.1234",
                subgroup="1",
                instance_id=1111,
                team_id=2767,
            ),
            Agent(
                id=1,
                name="Second Character",
                profession=Profession.WARRIOR,
                elite=EliteSpec.SPELLBREAKER,
                is_player=True,
                account_name=":Player.1234",
                subgroup="1",
                instance_id=1111,
                team_id=2767,
            ),
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 0,
                "name": "First Character",
                "profession": "Ritualist",
                "teamID": 2767,
            },
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 1,
                "name": "Second Character",
                "profession": "Spellbreaker",
                "teamID": 2767,
            },
        ]
    }

    result = compare_elite_insights(fight, expected, [])

    assert result["differences"] == {}


def test_compare_elite_insights_keeps_team_on_last_same_character_slice_only() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260424", agent_count=1, duration_ms=10_000),
        agents=[
            Agent(
                id=1,
                name="Same Character",
                profession=Profession.GUARDIAN,
                elite=EliteSpec.FIREBRAND,
                is_player=True,
                account_name=":Player.1234",
                subgroup="5",
                instance_id=1111,
                team_id=2767,
            ),
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 0,
                "name": "Same Character",
                "teamID": 0,
            },
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 1,
                "name": "Same Character",
                "teamID": 2767,
            },
        ]
    }

    result = compare_elite_insights(fight, expected, [])

    assert result["differences"] == {}


def test_compare_elite_insights_does_not_merge_shared_instance_buffs() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=2, duration_ms=10_000),
        agents=[
            Agent(
                id=1,
                name="Named",
                profession=Profession.ENGINEER,
                elite=EliteSpec.SCRAPPER,
                is_player=True,
                account_name=":Named.1234",
                instance_id=1111,
            ),
            Agent(
                id=2,
                name="Mécatronicienne",
                profession=Profession.ENGINEER,
                elite=EliteSpec.SCRAPPER,
                is_player=True,
                instance_id=1111,
            ),
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Named.1234",
                "instanceID": 1111,
                "name": "Named",
                "buffUptimes": [{"id": 1187, "buffData": [{"uptime": 10.0}]}],
            },
            {
                "account": "Non Squad Player 1",
                "instanceID": 1111,
                "name": "Scrapper pl-1111",
                "buffUptimes": [{"id": 1187, "buffData": [{"uptime": 20.0}]}],
            },
        ]
    }
    events = [
        BoonApplyEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=1,
            skill_id=1187,
            duration_ms=1_000,
            stacks=1,
            kind="apply",
        ),
        BoonApplyEvent(
            time_ms=0,
            source_agent_id=2,
            target_agent_id=2,
            skill_id=1187,
            duration_ms=2_000,
            stacks=1,
            kind="apply",
        ),
    ]

    result = compare_elite_insights(fight, expected, events)

    assert result["differences"] == {}


def test_compare_elite_insights_prefers_outcome_downs_for_named_players() -> None:
    fight = Fight(
        id="fight",
        agents=[
            Agent(
                id=1,
                name="Player",
                profession=Profession.MESMER,
                elite=EliteSpec.CHRONOMANCER,
                is_player=True,
                account_name=":Player.1234",
                instance_id=1111,
            )
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Player.1234",
                "name": "Player",
                "defenses": [{"downCount": 1}],
            }
        ]
    }
    events = [
        CombatOutcomeEvent(
            time_ms=100,
            source_agent_id=2,
            target_agent_id=1,
            skill_id=42,
            outcome="downed",
        ),
        BoonApplyEvent(
            time_ms=100,
            source_agent_id=0,
            target_agent_id=1,
            skill_id=770,
            duration_ms=2_147_483_647,
            stacks=1,
            kind="apply",
        ),
        BoonApplyEvent(
            time_ms=200,
            source_agent_id=0,
            target_agent_id=1,
            skill_id=770,
            duration_ms=2_147_483_647,
            stacks=1,
            kind="apply",
        ),
    ]

    result = compare_elite_insights(fight, expected, events)

    assert result["differences"] == {}


def _dmg(result: int, connected: bool, is_condition: bool = False) -> DamageEvent:
    return DamageEvent(
        time_ms=100,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=0,
        connected=connected,
        result=result,
        is_condition=is_condition,
    )


def test_skill_stats_breakbar_grouprule() -> None:
    # Mixed normals + breakbar: EI counts the normals and drops breakbar.
    stats = _skill_stats([_dmg(1, True), _dmg(10, True)])
    assert stats[42]["connectedHits"] == 1
    # Breakbar only: EI counts them.
    stats = _skill_stats([_dmg(10, True)])
    assert stats[42]["connectedHits"] == 1
    # Breakbar only + the player interrupted an enemy cast with that
    # skill: EI books the entry as interrupted and drops the hit.
    stats = _skill_stats([_dmg(10, True)], {42})
    assert stats[42]["connectedHits"] == 0
    # A landed normal keeps the normal count even when the skill
    # interrupted: interrupt only affects the breakbar-only branch.
    stats = _skill_stats([_dmg(1, True), _dmg(10, True)], {42})
    assert stats[42]["connectedHits"] == 1
    # Breakbar + blocked/evaded only: EI drops the skill entirely.
    stats = _skill_stats([_dmg(10, True), _dmg(3, False)])
    assert stats[42]["connectedHits"] == 0
    # Condition landed alongside breakbar: normals win, breakbar dropped.
    stats = _skill_stats([_dmg(10, True), _dmg(0, True, is_condition=True)])
    assert stats[42]["connectedHits"] == 1


def test_compare_elite_insights_excludes_breakbar_from_damage_taken_count() -> None:
    fight = Fight(
        id="fight",
        agents=[
            Agent(
                id=2,
                name="Player",
                profession=Profession.MESMER,
                elite=EliteSpec.CHRONOMANCER,
                is_player=True,
                account_name=":Player.1234",
                instance_id=1111,
            )
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "defenses": [{"damageTakenCount": 0}],
            }
        ]
    }

    result = compare_elite_insights(fight, expected, [_dmg(10, True)])

    assert result["differences"] == {}
