from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from gw2_analytics.ei_compare import _skill_stats, compare_elite_insights
from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    ActivationType,
    Agent,
    BoonApplyEvent,
    CombatOutcomeEvent,
    DamageEvent,
    DeathEvent,
    EliteSpec,
    EvtcHeader,
    Fight,
    Profession,
    Skill,
    SkillActivationEvent,
    SpawnEvent,
)
from gw2_evtc_parser import OwnershipInterval


def _rows(result: dict[str, object]) -> dict[str, dict[str, Any]]:
    return {str(row["key"]): row for row in cast("list[dict[str, Any]]", result["results"])}


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


def test_compare_elite_insights_does_not_overwrite_same_start_slice_differences() -> None:
    fight = Fight(
        id="fight",
        agents=[
            Agent(
                id=1,
                name="Player",
                profession=Profession.GUARDIAN,
                elite=EliteSpec.FIREBRAND,
                is_player=True,
                account_name=":Player.1234",
                instance_id=1111,
            )
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {"account": "Player.1234", "instanceID": 1111, "firstAware": 0, "group": 1},
            {"account": "Player.1234", "instanceID": 1111, "firstAware": 0, "group": 2},
        ]
    }

    result = compare_elite_insights(fight, expected, [])

    assert result["differences"] == {
        "players[Player.1234@0].group": {"expected": 1, "actual": 0},
        "players[Player.1234@0].2.group": {"expected": 2, "actual": 0},
    }


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


def test_compare_elite_insights_emits_atomic_results_for_players_and_header() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=1, duration_ms=10_000),
        agents=[
            Agent(
                id=1,
                name="Player",
                profession=Profession.MESMER,
                elite=EliteSpec.CHRONOMANCER,
                is_player=True,
                account_name=":Player.1234",
                subgroup="1",
                instance_id=1111,
            )
        ],
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 0,
                "name": "Player",
                "group": 1,
            }
        ]
    }

    result = compare_elite_insights(fight, expected, [])

    assert result["differences"] == {}
    rows = _rows(result)
    player = rows["players[Player.1234].name"]
    assert player["status"] == "PASS"
    assert player["rule"] == "player-field"
    assert player["dimensions"] == {"account": "Player.1234", "slice": 0}
    assert player["delta"] is None


def test_compare_elite_insights_reports_fail_with_numeric_delta() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=1, duration_ms=10_000),
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
                "instanceID": 1111,
                "firstAware": 0,
                "name": "Wrong Name",
                "group": 99,
            }
        ]
    }

    result = compare_elite_insights(fight, expected, [])

    assert len(cast("list[dict[str, object]]", result["differences"])) == 2
    rows = _rows(result)
    name = rows["players[Player.1234].name"]
    assert name["status"] == "FAIL"
    assert name["expected"] == "Wrong Name"
    assert name["actual"] == "Player"
    assert name["delta"] is None
    group = rows["players[Player.1234].group"]
    assert group["status"] == "FAIL"
    assert group["delta"] == 0 - 99


def test_compare_elite_insights_emits_player_present_result_when_agent_missing() -> None:
    fight = Fight(id="fight", agents=[])
    expected: dict[str, Any] = {
        "players": [{"account": "Ghost.1234", "instanceID": 1111, "name": "Ghost"}]
    }

    result = compare_elite_insights(fight, expected, [])

    rows = _rows(result)
    row = rows["players[Ghost.1234]"]
    assert row["status"] == "FAIL"
    assert row["rule"] == "player-present"
    assert row["dimensions"] == {"account": "Ghost.1234", "slice": None}


def test_compare_elite_insights_emits_buff_uptime_tolerance_result() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=1, duration_ms=10_000),
        agents=[
            Agent(
                id=1,
                name="Player",
                profession=Profession.ENGINEER,
                elite=EliteSpec.SCRAPPER,
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
                "firstAware": 0,
                "buffUptimes": [{"id": 1187, "buffData": [{"uptime": 100.0}]}],
            }
        ]
    }
    events = [
        BoonApplyEvent(
            time_ms=0,
            source_agent_id=1,
            target_agent_id=1,
            skill_id=1187,
            duration_ms=10_000,
            stacks=1,
            kind="apply",
        )
    ]

    result = compare_elite_insights(fight, expected, events)

    assert result["differences"] == {}
    rows = _rows(result)
    row = rows["players[Player.1234].buffUptimes[1187].uptime"]
    assert row["status"] == "PASS"
    assert row["rule"] == "buff-uptime-tolerance"
    assert row["dimensions"] == {"account": "Player.1234", "slice": 0, "buff_id": 1187}


def test_compare_elite_insights_emits_per_cast_rotation_results() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=1, duration_ms=10_000),
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
                "instanceID": 1111,
                "firstAware": 0,
                "rotation": [{"id": 42, "skills": [{"castTime": 100, "duration": 500}]}],
            }
        ]
    }

    result = compare_elite_insights(fight, expected, [])

    rows = _rows(result)
    row = rows["players[Player.1234].rotation[castTime=100][duration=500][skillID=42]"]
    assert row["status"] == "FAIL"
    assert row["rule"] == "rotation-cast-match"
    assert row["dimensions"] == {"account": "Player.1234", "slice": 0, "skill_id": 42}


def test_compare_elite_insights_reports_dps_all_scalar_results() -> None:
    fight = Fight(
        id="fight",
        header=EvtcHeader(build_version="20260224", agent_count=1, duration_ms=10_000),
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
        skills=[Skill(id=42, name="Blurred Frenzy")],
    )
    damage = DamageEvent(
        time_ms=500,
        source_agent_id=1,
        target_agent_id=2,
        skill_id=42,
        damage=1000,
        connected=True,
    )
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Player.1234",
                "instanceID": 1111,
                "firstAware": 0,
                "lastAware": 10000,
                "dpsAll": [{"damage": 2000, "condiDamage": 0, "powerDamage": 2000}],
            }
        ]
    }

    result = compare_elite_insights(fight, expected, [damage])

    rows = _rows(result)
    row = rows["players[Player.1234].dpsAll.damage"]
    assert row["status"] == "FAIL"
    assert row["rule"] == "dpsAll-field"
    assert row["expected"] == 2000
    assert row["actual"] == 1000
    assert row["delta"] == -1000
    assert row["dimensions"] == {"account": "Player.1234", "slice": 0}


# ---------------------------------------------------------------------------
# Temporal ownership wiring (ei_compare -> build_skill_rotation)
# ---------------------------------------------------------------------------


def _recycled_instance_fixture() -> tuple[
    Fight, dict[int, tuple[int, int]], list[OwnershipInterval]
]:
    """A familiar whose real owner and whose static instance lookup differ.

    Two player agents share instance id 500 (arcdps recycles instance ids and
    the parsed agent table keeps one row per agent, so the sharing is real --
    see ``test_compare_elite_insights_keeps_first_anonymous_agent_for_shared_instance``).
    The static ``agent_id_by_instance`` map is a last-write-wins dict built in
    ``compare_elite_insights``, so it resolves 500 to the LATER carrier (agent
    2, Beta). The temporally scoped ownership scan resolves the familiar's
    master against the candidate aware at the linking instant -- the earlier
    carrier (agent 1, Alpha).
    """
    origin = 1_000_000
    fight = Fight(
        id="fight",
        header=EvtcHeader(
            build_version="20250925", agent_count=3, start_time_ms=origin, duration_ms=10_000
        ),
        agents=[
            Agent(
                id=1,
                name="Alpha",
                profession=Profession.NECROMANCER,
                elite=EliteSpec.HARBINGER,
                is_player=True,
                account_name=":Alpha.1111",
                subgroup="1",
                instance_id=500,
            ),
            Agent(
                id=2,
                name="Beta",
                profession=Profession.WARRIOR,
                elite=EliteSpec.SPELLBREAKER,
                is_player=True,
                account_name=":Beta.2222",
                subgroup="1",
                instance_id=500,
            ),
            Agent(
                id=3,
                name="Familiar",
                profession=Profession.UNKNOWN,
                species_id=1,
                instance_id=900,
            ),
        ],
    )
    agent_awareness = {1: (0, 2_000), 2: (3_000, 9_000), 3: (500, 600)}
    ownership_intervals = [
        OwnershipInterval(
            agent_id=3,
            owner_agent_id=1,
            instance_id=900,
            species_id=None,
            start_ms=0,
            end_ms=9_000,
            is_player=False,
        )
    ]
    return fight, agent_awareness, ownership_intervals


def _familiar_activation(origin: int = 1_000_000) -> SkillActivationEvent:
    """One Evoker familiar ``Zap`` (76803) cast, whose owner skill is 77370."""
    return SkillActivationEvent(
        time_ms=origin + 500,
        source_agent_id=3,
        target_agent_id=0,
        skill_id=76803,
        activation=ActivationType.NORMAL,
        duration_ms=0,
        expected_duration_ms=0,
        src_master_instid=500,
    )


def test_compare_elite_insights_consumes_the_temporal_ownership_resolver() -> None:
    """The rotation builder must be handed the temporal resolver by ei_compare.

    The familiar's ``MinionCastCastFinder`` instant cast (77370) has to land on
    Alpha -- the owner the ownership scan resolved at that timestamp -- even
    though the static ``agent_id_by_instance[500]`` names Beta. Crediting it to
    Beta would show up as an EXTRA cast on Beta's row (and Beta's expected
    rotation is empty), so this test fails whenever the resolver is not wired
    into ``build_skill_rotation``.
    """
    fight, agent_awareness, ownership_intervals = _recycled_instance_fixture()
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Alpha.1111",
                "instanceID": 500,
                "firstAware": 0,
                "lastAware": 2_000,
                "rotation": [{"id": 77370, "skills": [{"castTime": 500, "duration": 0}]}],
            },
            {
                "account": "Beta.2222",
                "instanceID": 500,
                "firstAware": 3_000,
                "lastAware": 9_000,
                "rotation": [],
            },
        ]
    }

    result = compare_elite_insights(
        fight,
        expected,
        [_familiar_activation()],
        agent_awareness=agent_awareness,
        ownership_intervals=ownership_intervals,
    )

    differences = cast("dict[str, Any]", result["differences"])
    rotation_keys = sorted(key for key in differences if "rotation" in key)
    assert rotation_keys == [], differences

    # Evidence that the fixture is discriminating: the static last-write-wins
    # instance map -- the pre-integration fallback -- attributes the same cast
    # to Beta, not Alpha.
    static_map = {agent.instance_id: agent.id for agent in fight.agents if agent.instance_id}
    assert static_map[500] == 2
    assert static_map[900] == 3


def test_rotation_ownership_resolver_takes_precedence_over_static_instance_map() -> None:
    """``ownership_resolver`` wins over ``agent_id_by_instance`` in rotation.

    Same fixture, asserted directly on ``build_skill_rotation`` so the
    precedence rule and the absolute/fight-relative time bridging are both
    pinned: the callback receives ABSOLUTE event times and the ownership
    intervals are fight-relative, so the adapter must subtract the fight origin.
    """
    fight, _agent_awareness, ownership_intervals = _recycled_instance_fixture()
    origin = 1_000_000
    event = _familiar_activation(origin)
    static_map = {agent.instance_id: agent.id for agent in fight.agents if agent.instance_id}

    def credits(resolver: Callable[[int, int], int | None] | None) -> set[tuple[int, int]]:
        return {
            (cast.source_agent_id, cast.skill_id)
            for cast in build_skill_rotation(
                [event],
                duration_ms=10_000,
                start_time_ms=origin,
                agent_id_by_instance=static_map,
                ownership_resolver=resolver,
            )
        }

    # Without the resolver the static map credits Beta (agent 2).
    assert credits(None) == {(3, 76803), (2, 77370)}
    # With the resolver the owner is Alpha (agent 1).
    assert credits(
        lambda agent_id, time_ms: 1 if agent_id == 3 and time_ms == origin + 500 else None
    ) == {
        (3, 76803),
        (1, 77370),
    }
    assert ownership_intervals[0].owner_agent_id == 1


def test_compare_elite_insights_aggregates_owned_minion_in_all_statistics() -> None:
    """EI 3.26 includes owned-minion damage in ``dpsAll`` and ``statsAll``.

    The same-instance alias remains part of the player entity, while
    actor-only fields continue to use the actor/alias set rather than the
    owned-minion set.
    """
    origin = 1_000_000
    fight = Fight(
        id="fight",
        header=EvtcHeader(
            build_version="20250925", agent_count=3, start_time_ms=origin, duration_ms=10_000
        ),
        agents=[
            Agent(
                id=1,
                name="Alpha",
                profession=Profession.NECROMANCER,
                elite=EliteSpec.HARBINGER,
                is_player=True,
                account_name=":Alpha.1111",
                subgroup="1",
                instance_id=500,
            ),
            # Recycled alias of the same player identity (same instance id).
            Agent(
                id=4,
                name="Alpha",
                profession=Profession.NECROMANCER,
                elite=EliteSpec.HARBINGER,
                is_player=True,
                instance_id=500,
            ),
            # Minion owned by agent 1.
            Agent(
                id=3,
                name="Minion",
                profession=Profession.UNKNOWN,
                species_id=1,
                instance_id=900,
            ),
        ],
    )

    def hit(source: int, at: int, damage: int) -> DamageEvent:
        return DamageEvent(
            time_ms=origin + at,
            source_agent_id=source,
            target_agent_id=99,
            skill_id=0,
            damage=damage,
            connected=True,
        )

    events = [
        hit(1, 100, 100),  # the player's own hit
        hit(4, 200, 10),  # recycled same-instance alias of the player
        hit(3, 300, 50),  # owned minion's hit -- NOT the player's
    ]
    ownership_intervals = [
        OwnershipInterval(
            agent_id=3,
            owner_agent_id=1,
            instance_id=900,
            species_id=None,
            start_ms=0,
            end_ms=9_000,
            is_player=False,
        )
    ]
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Alpha.1111",
                "instanceID": 500,
                "firstAware": 0,
                "lastAware": 9_000,
                "dpsAll": [{"damage": 160, "condiDamage": 0, "powerDamage": 160}],
                "statsAll": [{"totalDamageCount": 3, "totalDmg": 160}],
                "defenses": [{"damageTaken": 0}],
            }
        ]
    }

    result = compare_elite_insights(
        fight,
        expected,
        events,
        agent_awareness={1: (0, 9_000), 4: (0, 9_000), 3: (300, 400)},
        ownership_intervals=ownership_intervals,
    )

    differences = cast("dict[str, Any]", result["differences"])
    over_attributed = sorted(key for key in differences if ".dpsAll" in key or ".statsAll" in key)
    assert over_attributed == [], differences


def test_all_statistics_use_final_owner_per_interval_not_slice_midpoint() -> None:
    """Minion damage on both sides of an ownership change stays with its actor.

    The direct owners are chain links to Alpha and change around the slice
    midpoint. Midpoint/direct-owner aggregation misses one or both events;
    EI's all-statistics path uses the final owner for each event interval.
    """
    origin = 1_000_000
    fight = Fight(
        id="fight",
        header=EvtcHeader(
            build_version="20250925", agent_count=4, start_time_ms=origin, duration_ms=10_000
        ),
        agents=[
            Agent(
                id=1,
                name="Alpha",
                profession=Profession.NECROMANCER,
                elite=EliteSpec.HARBINGER,
                is_player=True,
                account_name=":Alpha.1111",
                subgroup="1",
                instance_id=500,
            ),
            Agent(id=2, name="Chain A", profession=Profession.UNKNOWN, instance_id=501),
            Agent(id=4, name="Chain B", profession=Profession.UNKNOWN, instance_id=502),
            Agent(
                id=3,
                name="Minion",
                profession=Profession.UNKNOWN,
                species_id=1,
                instance_id=900,
            ),
        ],
    )

    def hit(at: int, damage: int) -> DamageEvent:
        return DamageEvent(
            time_ms=origin + at,
            source_agent_id=3,
            target_agent_id=99,
            skill_id=0,
            damage=damage,
            connected=True,
        )

    result = compare_elite_insights(
        fight,
        {
            "players": [
                {
                    "account": "Alpha.1111",
                    "instanceID": 500,
                    "firstAware": 0,
                    "lastAware": 9_000,
                    "dpsAll": [{"damage": 150, "condiDamage": 0, "powerDamage": 150}],
                    "statsAll": [{"totalDamageCount": 2, "totalDmg": 150}],
                    "defenses": [{"damageTaken": 0}],
                }
            ]
        },
        [hit(4_900, 100), hit(5_100, 50)],
        agent_awareness={1: (0, 9_000), 2: (0, 9_000), 4: (0, 9_000), 3: (0, 9_000)},
        ownership_intervals=[
            OwnershipInterval(
                agent_id=3,
                owner_agent_id=2,
                instance_id=900,
                species_id=1,
                start_ms=0,
                end_ms=5_000,
                is_player=False,
                final_master_agent_id=1,
            ),
            OwnershipInterval(
                agent_id=3,
                owner_agent_id=4,
                instance_id=900,
                species_id=1,
                start_ms=5_000,
                end_ms=9_000,
                is_player=False,
                final_master_agent_id=1,
            ),
        ],
    )

    differences = cast("dict[str, Any]", result["differences"])
    assert not [key for key in differences if ".dpsAll" in key or ".statsAll" in key], differences


def _shambling_horror_fight() -> Fight:
    """A Reaper player and the Shambling Horror it spawned 26 ms earlier.

    Mirrors the corpus shape (20260125-194936): the horror's CBTS_SPAWN record
    carries no master instid, and the master link only appears in a later
    record. Nothing about the two agents is temporally recycled here, so the
    only variable under test is WHEN ownership may be queried.
    """
    origin = 1_000_000
    return Fight(
        id="fight",
        header=EvtcHeader(
            build_version="20250925", agent_count=2, start_time_ms=origin, duration_ms=10_000
        ),
        agents=[
            Agent(
                id=10,
                name="Faucheuse",
                profession=Profession.NECROMANCER,
                elite=EliteSpec.REAPER,
                is_player=True,
                account_name=":Owner.1111",
                subgroup="1",
                instance_id=4960,
            ),
            Agent(
                id=11,
                name="Horreur chancelante",
                profession=Profession.UNKNOWN,
                species_id=15314,
                instance_id=2472,
            ),
        ],
    )


def test_rotation_shambling_horror_falls_back_to_post_hoc_owner_at_spawn() -> None:
    """A spawn-instant resolver miss must not drop EI's ``Rise`` cast.

    EI emits ``30772`` at the SPAWN record's time credited to the minion's
    FINAL master, which is only knowable from a later record. The resolver
    therefore answers ``None`` at that instant on real logs, and the finder has
    to fall back to the post-hoc owner (the parser's final-master analogue)
    instead of silently dropping the cast.
    """
    origin = 1_000_000
    spawn = SpawnEvent(
        time_ms=origin + 500, source_agent_id=10, target_agent_id=11, skill_id=0
    )
    kwargs: dict[str, Any] = {
        "duration_ms": 10_000,
        "start_time_ms": origin,
        "elite_specs": {10: EliteSpec.REAPER},
        "shambling_horror_agent_ids": {11},
    }

    def credits(resolver: Callable[[int, int], int | None] | None) -> set[tuple[int, int]]:
        return {
            (cast.source_agent_id, cast.skill_id)
            for cast in build_skill_rotation([spawn], ownership_resolver=resolver, **kwargs)
        }

    # No resolver: the post-hoc owner is used (pre-integration behaviour).
    assert credits(None) == {(10, 30772)}
    # A resolver miss cannot invent a future owner; the integrated resolver
    # must provide EI's explicit post-hoc final-master projection.
    assert credits(lambda agent_id, time_ms: None) == set()
    # Resolver hit: it wins, and it receives the ABSOLUTE event time.
    seen: list[tuple[int, int]] = []

    def resolving(agent_id: int, time_ms: int) -> int | None:
        seen.append((agent_id, time_ms))
        return 10

    assert credits(resolving) == {(10, 30772)}
    assert seen == [(11, origin + 500)]
    # Unresolvable post-hoc owner (0) and a resolver miss: no cast at all.
    orphan = SpawnEvent(time_ms=origin + 500, source_agent_id=0, target_agent_id=11, skill_id=0)
    assert {
        (cast.source_agent_id, cast.skill_id)
        for cast in build_skill_rotation(
            [orphan], ownership_resolver=lambda agent_id, time_ms: None, **kwargs
        )
    } == set()


def test_compare_elite_insights_credits_horror_spawn_to_final_master() -> None:
    """End-to-end: the resolver path in ei_compare keeps the corpus semantics.

    The horror's ownership interval starts with ``owner_agent_id=None`` (the
    spawn record declares no master) and only gains its owner 26 ms later, so
    ``resolver.owner_at(horror, spawn_time)`` is ``None``. EI still reports the
    ``Rise`` cast on the owner's row at the spawn time, so the comparison must
    match -- and it can only match through the post-hoc fallback.
    """
    origin = 1_000_000
    fight = _shambling_horror_fight()
    events = [
        SpawnEvent(time_ms=origin + 500, source_agent_id=10, target_agent_id=11, skill_id=0)
    ]
    ownership_intervals = [
        OwnershipInterval(
            agent_id=11,
            owner_agent_id=None,
            instance_id=2472,
            species_id=15314,
            start_ms=500,
            end_ms=526,
            is_player=False,
            final_master_agent_id=10,
        ),
        OwnershipInterval(
            agent_id=11,
            owner_agent_id=10,
            instance_id=2472,
            species_id=15314,
            start_ms=526,
            end_ms=9_000,
            is_player=False,
            final_master_agent_id=10,
        ),
    ]
    expected: dict[str, Any] = {
        "players": [
            {
                "account": "Owner.1111",
                "instanceID": 4960,
                "name": "Faucheuse",
                "firstAware": 0,
                "lastAware": 9_000,
                "rotation": [{"id": 30772, "skills": [{"castTime": 500, "duration": 0}]}],
            }
        ]
    }

    result = compare_elite_insights(
        fight,
        expected,
        events,
        agent_awareness={10: (0, 9_000), 11: (500, 9_000)},
        ownership_intervals=ownership_intervals,
    )

    differences = cast("dict[str, Any]", result["differences"])
    assert sorted(key for key in differences if "rotation" in key) == [], differences
