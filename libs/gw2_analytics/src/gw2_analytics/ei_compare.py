"""Compare parsed combat data with an Elite Insights detailed JSON export."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from gw2_analytics.buff_state import TRACKED_BUFFS, BuffStateTracker
from gw2_analytics.down_contribution import DownContributionAggregator
from gw2_analytics.initial_buffs import extract_initial_buffs
from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    CCEvent,
    CombatOutcomeEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    DownEvent,
    Event,
    Fight,
    HealthUpdateEvent,
)

_STAT_FIELDS = (
    "totalDamageCount",
    "totalDmg",
    "connectedDamageCount",
    "connectedDmg",
    "connectedDirectDamageCount",
    "connectedDirectDmg",
    "connectedConditionCount",
    "connectedConditionDamage",
    "critableDirectDamageCount",
    "criticalRate",
    "criticalDmg",
    "invulned",
    "killed",
    "downed",
    "againstDownedCount",
    "againstDownedDamage",
    "downContribution",
    "appliedCrowdControlDownContribution",
    "appliedCrowdControlDurationDownContribution",
    "appliedCrowdControl",
    "appliedCrowdControlDuration",
)


def _compare_fields(
    prefix: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    differences: dict[str, object],
    fields: Sequence[str] | None = None,
) -> None:
    for field in fields or tuple(actual):
        if field in expected and expected[field] != actual.get(field):
            differences[f"{prefix}.{field}"] = {
                "expected": expected[field],
                "actual": actual.get(field),
            }


def _damage_stats(
    damage: list[DamageEvent],
    crowd_control: list[CCEvent],
    down_row: object | None,
) -> dict[str, int]:
    connected = [event for event in damage if event.damage > 0]
    direct = [event for event in connected if event.buff_dmg == 0]
    condition = [event for event in connected if event.buff_dmg > 0]
    critical = [event for event in direct if event.result == 1]
    return {
        "totalDamageCount": len(damage),
        "totalDmg": sum(event.damage for event in damage),
        "connectedDamageCount": len(connected),
        "connectedDmg": sum(event.damage for event in connected),
        "connectedDirectDamageCount": len(direct),
        "connectedDirectDmg": sum(event.damage for event in direct),
        "connectedConditionCount": len(condition),
        "connectedConditionDamage": sum(event.buff_dmg for event in condition),
        "critableDirectDamageCount": len(direct),
        "criticalRate": len(critical),
        "criticalDmg": sum(event.damage for event in critical),
        "invulned": sum(event.result in {6, 9} for event in damage),
        "killed": getattr(down_row, "kills", 0),
        "downed": getattr(down_row, "downs", 0),
        "againstDownedCount": getattr(down_row, "against_downed_count", 0),
        "againstDownedDamage": getattr(down_row, "against_downed_damage", 0),
        "downContribution": getattr(down_row, "down_contribution_damage", 0),
        "appliedCrowdControlDownContribution": getattr(down_row, "down_contribution_cc_count", 0),
        "appliedCrowdControlDurationDownContribution": getattr(
            down_row, "down_contribution_cc_duration_ms", 0
        ),
        "appliedCrowdControl": len(crowd_control),
        "appliedCrowdControlDuration": sum(event.cc_value for event in crowd_control),
    }


def _skill_stats(events: list[DamageEvent]) -> dict[int, dict[str, int]]:
    by_skill: dict[int, list[DamageEvent]] = defaultdict(list)
    for event in events:
        by_skill[event.skill_id].append(event)
    return {
        skill_id: {
            "totalDamage": sum(event.damage for event in skill_events),
            "connectedHits": sum(event.damage > 0 for event in skill_events),
            "crit": sum(event.result == 1 and event.buff_dmg == 0 for event in skill_events),
            "critDamage": sum(
                event.damage for event in skill_events if event.result == 1 and event.buff_dmg == 0
            ),
        }
        for skill_id, skill_events in by_skill.items()
    }


def compare_elite_insights(  # noqa: PLR0912, PLR0915
    fight: Fight,
    expected: dict[str, object],
    events: Sequence[Event],
) -> dict[str, object]:
    """Return a JSON-serializable comparison report."""
    header = fight.header
    actual: dict[str, object] = {
        "arcVersion": f"EVTC{header.build_version}" if header else None,
        "triggerID": header.encounter_id if header else None,
        "gW2Build": header.gw2_build if header else None,
        "mapID": header.map_id if header else None,
        "arcRevision": header.arc_revision if header else None,
        "durationMS": header.duration_ms if header else None,
        "success": fight.success,
        "eiEncounterID": fight.ei_encounter_id,
    }
    differences: dict[str, object] = {}
    _compare_fields("", expected, actual, differences)
    differences = {key.removeprefix("."): value for key, value in differences.items()}

    expected_players = expected.get("players")
    if not isinstance(expected_players, list):
        return {"matches": not differences, "compared": actual, "differences": differences}

    event_list = list(events)
    origin = min((event.time_ms for event in event_list), default=0)
    duration_ms = header.duration_ms if header and header.duration_ms else 0
    damage_events = [event for event in event_list if isinstance(event, DamageEvent)]
    cc_events = [event for event in event_list if isinstance(event, CCEvent)]
    down_rows = DownContributionAggregator().aggregate(
        damage_events,
        [event for event in event_list if isinstance(event, DownEvent)],
        [event for event in event_list if isinstance(event, DeathEvent)],
        duration_ms / 1000,
        health_events=[event for event in event_list if isinstance(event, HealthUpdateEvent)],
        outcome_events=[event for event in event_list if isinstance(event, CombatOutcomeEvent)],
        cc_events=cc_events,
    )
    down_by_source = {row.source_agent_id: row for row in down_rows}
    agents_by_account = {
        agent.account_name.lstrip(":"): agent for agent in fight.agents if agent.account_name
    }
    agents_by_instance = {agent.instance_id: agent for agent in fight.agents if agent.instance_id}
    targets = expected.get("targets") if isinstance(expected.get("targets"), list) else []

    tracker = BuffStateTracker(start_time_ms=origin)
    for event in event_list:
        if isinstance(event, (BoonApplyEvent, BuffApplyEvent)):
            tracker.process(event)
    rotation = build_skill_rotation(event_list, duration_ms, origin)
    compared_players: dict[str, object] = {}

    for player in expected_players:
        if not isinstance(player, dict) or not isinstance(player.get("account"), str):
            continue
        account = player["account"]
        agent = agents_by_account.get(account)
        if agent is None:
            compared_players[account] = None
            differences[f"players[{account}]"] = {"expected": "present", "actual": None}
            continue
        prefix = f"players[{account}]"
        values: dict[str, object] = {
            "name": agent.name,
            "group": int(agent.subgroup or 0),
            "instanceID": agent.instance_id,
            "teamID": agent.team_id,
        }
        _compare_fields(prefix, player, values, differences)
        source_damage = [event for event in damage_events if event.source_agent_id == agent.id]
        source_cc = [event for event in cc_events if event.source_agent_id == agent.id]

        dps_all = player.get("dpsAll")
        if isinstance(dps_all, list) and dps_all and isinstance(dps_all[0], dict):
            damage = sum(event.damage for event in source_damage)
            condition = sum(event.buff_dmg for event in source_damage)
            dps_values = {
                "damage": damage,
                "condiDamage": condition,
                "powerDamage": damage - condition,
            }
            values["dpsAll"] = dps_values
            _compare_fields(f"{prefix}.dpsAll", dps_all[0], dps_values, differences)

        defenses = player.get("defenses")
        if isinstance(defenses, list) and defenses and isinstance(defenses[0], dict):
            taken = [event for event in damage_events if event.target_agent_id == agent.id]
            downed = [
                event
                for event in event_list
                if isinstance(event, DownEvent) and event.source_agent_id == agent.id
            ]
            defense_values = {
                "damageTaken": sum(event.damage for event in taken),
                "damageTakenCount": sum(event.damage > 0 for event in taken),
                "conditionDamageTaken": sum(event.buff_dmg for event in taken),
                "powerDamageTaken": sum(event.damage - event.buff_dmg for event in taken),
                "blockedCount": sum(
                    isinstance(event, BlockEvent) and event.source_agent_id == agent.id
                    for event in event_list
                ),
                "evadedCount": sum(
                    isinstance(event, DodgeEvent) and event.source_agent_id == agent.id
                    for event in event_list
                ),
                "downCount": len(downed),
                "downDuration": sum(event.downtime_ms for event in downed),
                "deadCount": sum(
                    isinstance(event, DeathEvent) and event.source_agent_id == agent.id
                    for event in event_list
                ),
            }
            values["defenses"] = defense_values
            _compare_fields(f"{prefix}.defenses", defenses[0], defense_values, differences)

        stats_all = player.get("statsAll")
        if isinstance(stats_all, list) and stats_all and isinstance(stats_all[0], dict):
            stats_values = _damage_stats(source_damage, source_cc, down_by_source.get(agent.id))
            values["statsAll"] = stats_values
            _compare_fields(
                prefix + ".statsAll", stats_all[0], stats_values, differences, _STAT_FIELDS
            )

        expected_buffs = player.get("buffUptimes")
        if isinstance(expected_buffs, list):
            uptime = tracker.compute_player_uptimes(agent.id, duration_ms)
            by_id = {buff_id: uptime[name] for name, buff_id in TRACKED_BUFFS.items()}
            compared_buffs: dict[int, float] = {}
            for expected_buff in expected_buffs:
                if not isinstance(expected_buff, dict) or not isinstance(
                    expected_buff.get("id"), int
                ):
                    continue
                buff_data = expected_buff.get("buffData")
                if (
                    not isinstance(buff_data, list)
                    or not buff_data
                    or not isinstance(buff_data[0], dict)
                ):
                    continue
                buff_id = expected_buff["id"]
                if buff_id not in by_id:
                    continue
                compared_buffs[buff_id] = round(by_id[buff_id], 3)
                expected_uptime = buff_data[0].get("uptime")
                if expected_uptime != compared_buffs[buff_id]:
                    differences[f"{prefix}.buffUptimes[{buff_id}].uptime"] = {
                        "expected": expected_uptime,
                        "actual": compared_buffs[buff_id],
                    }
            values["buffUptimes"] = compared_buffs

        expected_rotation = player.get("rotation")
        if isinstance(expected_rotation, list):
            expected_casts = sorted(
                (
                    (
                        group["id"],
                        cast["castTime"],
                        cast["duration"],
                    )
                    for group in expected_rotation
                    if isinstance(group, dict) and isinstance(group.get("id"), int)
                    for cast in group.get("skills", [])
                    if isinstance(cast, dict)
                ),
                key=lambda item: (item[1], item[0]),
            )
            actual_casts = sorted(
                (
                    (cast.skill_id, cast.time_ms, cast.duration_ms)
                    for cast in rotation
                    if cast.source_agent_id == agent.id
                ),
                key=lambda item: (item[1], item[0]),
            )
            values["rotation"] = actual_casts
            if expected_casts != actual_casts:
                differences[f"{prefix}.rotation"] = {
                    "expected": expected_casts,
                    "actual": actual_casts,
                }

        consumables = player.get("consumables")
        if isinstance(consumables, list):
            ids = {
                item["id"]
                for item in consumables
                if isinstance(item, dict) and isinstance(item.get("id"), int)
            }
            actual_consumables = sorted(
                (buff.skill_id, buff.time_ms, buff.duration_ms, buff.stacks)
                for buff in extract_initial_buffs(event_list, origin, ids)
                if buff.agent_id == agent.id
            )
            expected_consumables = sorted(
                (item["id"], item["time"], item["duration"], item["stack"])
                for item in consumables
                if isinstance(item, dict)
            )
            values["consumables"] = actual_consumables
            if expected_consumables != actual_consumables:
                differences[f"{prefix}.consumables"] = {
                    "expected": expected_consumables,
                    "actual": actual_consumables,
                }

        dps_targets = player.get("dpsTargets")
        stats_targets = player.get("statsTargets")
        if isinstance(targets, list):
            compared_targets: dict[int, object] = {}
            for index, target in enumerate(targets):
                if not isinstance(target, dict) or not isinstance(target.get("instanceID"), int):
                    continue
                target_agent = agents_by_instance.get(target["instanceID"])
                target_damage = [
                    event
                    for event in source_damage
                    if target_agent is not None and event.target_agent_id == target_agent.id
                ]
                target_cc = [
                    event
                    for event in source_cc
                    if target_agent is not None and event.target_agent_id == target_agent.id
                ]
                target_id = target_agent.id if target_agent is not None else 0
                target_down_rows = DownContributionAggregator().aggregate(
                    target_damage,
                    [
                        event
                        for event in event_list
                        if isinstance(event, DownEvent) and event.source_agent_id == target_id
                    ],
                    [
                        event
                        for event in event_list
                        if isinstance(event, DeathEvent) and event.source_agent_id == target_id
                    ],
                    duration_ms / 1000,
                    health_events=[
                        event
                        for event in event_list
                        if isinstance(event, HealthUpdateEvent)
                        and event.source_agent_id == target_id
                    ],
                    outcome_events=[
                        event
                        for event in event_list
                        if isinstance(event, CombatOutcomeEvent)
                        and event.target_agent_id == target_id
                    ],
                    cc_events=target_cc,
                )
                target_down_by_source = {row.source_agent_id: row for row in target_down_rows}
                target_stats = _damage_stats(
                    target_damage, target_cc, target_down_by_source.get(agent.id)
                )
                target_values = {
                    "damage": sum(event.damage for event in target_damage),
                    "condiDamage": sum(event.buff_dmg for event in target_damage),
                    "powerDamage": sum(event.damage - event.buff_dmg for event in target_damage),
                }
                seconds = duration_ms / 1000
                target_values.update(
                    {
                        "dps": round(target_values["damage"] / seconds) if seconds else 0,
                        "condiDps": round(target_values["condiDamage"] / seconds) if seconds else 0,
                        "powerDps": round(target_values["powerDamage"] / seconds) if seconds else 0,
                    }
                )
                compared_targets[target["instanceID"]] = {
                    "dps": target_values,
                    "stats": target_stats,
                }
                if (
                    isinstance(dps_targets, list)
                    and index < len(dps_targets)
                    and dps_targets[index]
                ):
                    _compare_fields(
                        f"{prefix}.dpsTargets[instanceID={target['instanceID']}]",
                        dps_targets[index][0],
                        target_values,
                        differences,
                    )
                if (
                    isinstance(stats_targets, list)
                    and index < len(stats_targets)
                    and stats_targets[index]
                ):
                    _compare_fields(
                        f"{prefix}.statsTargets[instanceID={target['instanceID']}]",
                        stats_targets[index][0],
                        target_stats,
                        differences,
                        _STAT_FIELDS,
                    )
            values["targets"] = compared_targets

        damage_dist = player.get("totalDamageDist")
        if isinstance(damage_dist, list) and damage_dist and isinstance(damage_dist[0], list):
            actual_skills = _skill_stats(source_damage)
            values["totalDamageDist"] = actual_skills
            for expected_skill in damage_dist[0]:
                if not isinstance(expected_skill, dict) or not isinstance(
                    expected_skill.get("id"), int
                ):
                    continue
                skill_id = expected_skill["id"]
                _compare_fields(
                    f"{prefix}.totalDamageDist[skillID={skill_id}]",
                    expected_skill,
                    actual_skills.get(skill_id, {}),
                    differences,
                    ("totalDamage", "connectedHits", "crit", "critDamage"),
                )

        compared_players[account] = values

    actual["players"] = compared_players
    return {"matches": not differences, "compared": actual, "differences": differences}


__all__ = ["compare_elite_insights"]
