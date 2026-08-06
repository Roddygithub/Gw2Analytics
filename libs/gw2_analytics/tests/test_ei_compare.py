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
    Fight,
    Profession,
)


def test_compare_elite_insights_keeps_first_anonymous_agent_for_shared_instance() -> None:
    fight = Fight(
        id="fight",
        agents=[
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
    # Breakbar + blocked/evaded only: EI drops the skill entirely.
    stats = _skill_stats([_dmg(10, True), _dmg(3, False)])
    assert stats[42]["connectedHits"] == 0
    # Condition landed alongside breakbar: normals win, breakbar dropped.
    stats = _skill_stats([_dmg(10, True), _dmg(0, True, is_condition=True)])
    assert stats[42]["connectedHits"] == 1
