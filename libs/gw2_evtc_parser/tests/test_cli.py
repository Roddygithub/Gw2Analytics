from __future__ import annotations

from gw2_core import Agent, BlockEvent, DamageEvent, EvtcHeader, Fight
from gw2_evtc_parser.__main__ import _build_parser, _compare_ei_metadata


def test_compare_ei_metadata_reports_exact_differences() -> None:
    fight = Fight(
        id="golden",
        success=True,
        ei_encounter_id=459_520,
        agents=[
            Agent(
                id=1,
                name="Player",
                is_player=True,
                account_name=":Player.1234",
                subgroup="1",
                instance_id=10,
                team_id=20,
            )
        ],
        header=EvtcHeader(
            build_version="20250925",
            encounter_id=1,
            agent_count=13,
            gw2_build=188_004,
            map_id=96,
            arc_revision=162_433,
            duration_ms=11_789,
        ),
    )
    expected = {
        "arcVersion": "EVTC20250925",
        "triggerID": 1,
        "gW2Build": 188_004,
        "mapID": 96,
        "arcRevision": 162_433,
        "durationMS": 12_000,
        "success": True,
        "eiEncounterID": 459_520,
        "players": [
            {
                "account": "Player.1234",
                "name": "Player",
                "group": 1,
                "instanceID": 10,
                "teamID": 20,
                "dpsAll": [{"damage": 100, "condiDamage": 30, "powerDamage": 70}],
                "defenses": [
                    {
                        "damageTaken": 50,
                        "damageTakenCount": 1,
                        "conditionDamageTaken": 0,
                        "powerDamageTaken": 50,
                        "blockedCount": 1,
                        "evadedCount": 0,
                        "downCount": 0,
                        "deadCount": 0,
                    }
                ],
            }
        ],
    }

    result = _compare_ei_metadata(
        fight,
        expected,
        [
            DamageEvent(
                time_ms=1,
                source_agent_id=1,
                target_agent_id=2,
                skill_id=3,
                damage=100,
                buff_dmg=30,
            ),
            DamageEvent(
                time_ms=2,
                source_agent_id=2,
                target_agent_id=1,
                skill_id=4,
                damage=50,
            ),
            BlockEvent(
                time_ms=3,
                source_agent_id=1,
                target_agent_id=0,
                skill_id=0,
            ),
        ],
    )

    assert result["matches"] is False
    assert result["differences"] == {
        "durationMS": {"expected": 12_000, "actual": 11_789}
    }


def test_compare_ei_command_is_registered() -> None:
    args = _build_parser().parse_args(["compare-ei", "fight.zevtc", "ei.json"])

    assert args.cmd == "compare-ei"
