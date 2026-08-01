"""Compare parsed combat data with an Elite Insights detailed JSON export."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from gw2_analytics.buff_state import MAX_STACKS, TRACKED_BUFFS, BuffStateTracker
from gw2_analytics.down_contribution import DownContributionAggregator
from gw2_analytics.initial_buffs import extract_initial_buffs
from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    Agent,
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    CCEvent,
    CombatOutcomeEvent,
    DamageEvent,
    DeathEvent,
    DespawnEvent,
    DodgeEvent,
    DownEvent,
    EliteSpec,
    Event,
    Fight,
    HealthUpdateEvent,
    Profession,
    UpEvent,
    spec_display_name,
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
    noncritable_skill_ids: set[int],
    condition_skill_ids: set[int] | None,
) -> dict[str, int]:
    counted = [event for event in damage if event.result != 10]
    connected = [event for event in counted if _connected(event)]
    # Direct and condition do NOT partition ``connected``: EI counts a hit
    # as direct when it came down the physical channel, and as condition
    # when the buff behind it is classified as one. Life-steal effects
    # travel the buff-damage channel without being conditions, so they
    # land in neither counter -- while still contributing to connectedDmg.
    condition = [event for event in connected if _is_condition(event, condition_skill_ids)]
    direct = [event for event in connected if not event.is_condition]
    critable = [event for event in direct if event.skill_id not in noncritable_skill_ids]
    critical = [event for event in critable if event.result in {1, 8}]
    return {
        "totalDamageCount": len(counted),
        "totalDmg": sum(event.damage for event in counted),
        "connectedDamageCount": len(connected),
        "connectedDmg": sum(event.damage for event in connected),
        "connectedDirectDamageCount": len(direct),
        "connectedDirectDmg": sum(event.damage for event in direct),
        "connectedConditionCount": len(condition),
        "connectedConditionDamage": sum(event.damage for event in condition),
        "critableDirectDamageCount": len(critable),
        "criticalRate": len(critical),
        "criticalDmg": sum(event.damage for event in critical),
        "invulned": sum(_invulned(event) for event in counted),
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


#: Direct-hit ``cbtresult`` values EI counts as landed. Only used as a
#: fallback for DamageEvents built by hand rather than by the parser
#: (tests, fixtures, synthetic streams), which leave ``connected`` unset.
#: The parser resolves the flag itself because the condition enum was
#: renumbered in 2026-05 and reading it needs the build version.
_DIRECT_HIT_RESULTS = frozenset({0, 1, 2, 8, 10})
_DIRECT_ABSORB_RESULT = 6


def _connected(event: DamageEvent) -> bool:
    """Whether EI would count this record as a landed hit.

    A condition tick that lands for zero health damage -- fully mitigated,
    or entirely converted to barrier -- still counts, so the magnitude is
    not a usable stand-in for the result byte.
    """
    if event.is_condition:
        return event.connected
    if event.connected:
        return True
    if event.buff_dmg > 0:
        return event.damage > 0
    return event.result in _DIRECT_HIT_RESULTS


def _invulned(event: DamageEvent) -> bool:
    if event.is_condition:
        return event.absorbed
    return event.absorbed or event.result == _DIRECT_ABSORB_RESULT


def _is_condition(event: DamageEvent, condition_skill_ids: set[int] | None) -> bool:
    """Whether EI books this record under condition rather than power damage.

    This is *not* the same question as ``DamageEvent.is_condition``, which
    records the arcdps channel the record arrived on (and so decides which
    enum the ``result`` byte belongs to). EI splits condi from power by the
    buff's ``classification`` in its own buff catalogue, so life-steal
    effects that arcdps sends down the buff-damage channel -- Vampiric
    Strikes, Battle Scars, Fulgor -- count as *power* damage there.

    ``condition_skill_ids`` is that catalogue, read from the EI export.
    Without it the arcdps channel is the best available approximation.
    """
    if condition_skill_ids is not None:
        return event.skill_id in condition_skill_ids
    return event.is_condition or event.buff_dmg > 0


def _condition_damage(event: DamageEvent, condition_skill_ids: set[int] | None) -> int:
    if not _is_condition(event, condition_skill_ids) or event.is_life_leech:
        return 0
    return min(event.damage, event.buff_dmg)


def _skill_stats(events: list[DamageEvent]) -> dict[int, dict[str, int]]:
    by_skill: dict[int, list[DamageEvent]] = defaultdict(list)
    for event in events:
        by_skill[event.skill_id].append(event)
    result: dict[int, dict[str, int]] = {}
    for skill_id, skill_events in by_skill.items():
        connected = sum(_connected(event) for event in skill_events)
        direct_crits = [
            event
            for event in skill_events
            if not event.is_condition and event.result in {1, 8} and event.buff_dmg == 0
        ]
        result[skill_id] = {
            "totalDamage": sum(event.damage for event in skill_events),
            "connectedHits": connected or sum(event.result == 10 for event in skill_events),
            "crit": len(direct_crits),
            "critDamage": sum(event.damage for event in direct_crits),
        }
    return result


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
    actor_damage_events = [event for event in damage_events if event.src_master_instid == 0]
    cc_events = [event for event in event_list if isinstance(event, CCEvent)]
    down_rows = DownContributionAggregator().aggregate(
        actor_damage_events,
        [event for event in event_list if isinstance(event, DownEvent)],
        [event for event in event_list if isinstance(event, DeathEvent)],
        duration_ms / 1000,
        health_events=[event for event in event_list if isinstance(event, HealthUpdateEvent)],
        up_events=[event for event in event_list if isinstance(event, UpEvent)],
        outcome_events=[event for event in event_list if isinstance(event, CombatOutcomeEvent)],
        cc_events=cc_events,
    )
    down_by_source = {row.source_agent_id: row for row in down_rows}
    agents_by_account = {
        agent.account_name.lstrip(":"): agent for agent in fight.agents if agent.account_name
    }
    agents_by_instance: dict[int, Agent] = {}
    for fight_agent in fight.agents:
        if fight_agent.instance_id:
            agents_by_instance.setdefault(fight_agent.instance_id, fight_agent)
    agent_ids_by_instance: dict[int, set[int]] = defaultdict(set)
    for fight_agent in fight.agents:
        if fight_agent.instance_id:
            agent_ids_by_instance[fight_agent.instance_id].add(fight_agent.id)
    targets = expected.get("targets") if isinstance(expected.get("targets"), list) else []
    buff_map = expected.get("buffMap")
    condition_skill_ids: set[int] | None = (
        {
            int(skill_id.lstrip("b"))
            for skill_id, data in buff_map.items()
            if isinstance(data, dict) and data.get("classification") == "Condition"
        }
        if isinstance(buff_map, dict)
        else None
    )
    skill_map = expected.get("skillMap")
    noncritable_skill_ids = (
        {
            int(skill_id.lstrip("s"))
            for skill_id, data in skill_map.items()
            if isinstance(data, dict) and data.get("canCrit") is False
        }
        if isinstance(skill_map, dict)
        else set()
    )

    tracker = BuffStateTracker(
        start_time_ms=origin,
        healing_by_agent={agent.id: agent.healing for agent in fight.agents},
    )
    for event in event_list:
        if isinstance(event, (BoonApplyEvent, BuffApplyEvent)):
            tracker.process(event)
        elif isinstance(event, DespawnEvent):
            tracker.end_agent(event.source_agent_id, event.time_ms + 10)
    rotation = build_skill_rotation(
        event_list,
        duration_ms,
        origin,
        {agent.id for agent in fight.agents if agent.elite == EliteSpec.VIRTUOSO},
        {
            agent.id
            for agent in fight.agents
            if agent.profession == Profession.MESMER
            and agent.elite in {EliteSpec.UNKNOWN, EliteSpec.MIRAGE}
        },
        {agent.id for agent in fight.agents if agent.species_id == 8111},
        {agent.id for agent in fight.agents if agent.name.startswith("Juvenile ")},
        {agent.id for agent in fight.agents if agent.species_id == 24796},
    )
    has_downed_buff_applies = any(
        isinstance(event, BoonApplyEvent) and event.kind == "apply" and event.skill_id == 770
        for event in event_list
    )
    compared_players: dict[str, object] = {}

    for player in expected_players:
        if not isinstance(player, dict) or not isinstance(player.get("account"), str):
            continue
        account = player["account"]
        instance_id = player.get("instanceID")
        agent: Agent | None = agents_by_account.get(account)
        if agent is None and isinstance(instance_id, int):
            agent = agents_by_instance.get(instance_id)
        if agent is None:
            compared_players[account] = None
            differences[f"players[{account}]"] = {"expected": "present", "actual": None}
            continue
        prefix = f"players[{account}]"
        anonymous = agent.account_name is None
        agent_ids = agent_ids_by_instance.get(agent.instance_id, {agent.id})
        # An anonymized enemy player carries no account name, and arcdps
        # has replaced their character name with the *localized* spec
        # string. EI labels them "<English spec> pl-<instanceID>", so the
        # label has to be rebuilt from the profession/elite IDs rather
        # than echoed from the name buffer.
        values: dict[str, object] = {
            "name": (
                f"{spec_display_name(agent.profession, agent.elite)} pl-{agent.instance_id}"
                if anonymous
                else agent.name
            ),
            "group": 51 if anonymous else int(agent.subgroup or 0),
            "instanceID": agent.instance_id,
            "teamID": agent.team_id,
        }
        _compare_fields(prefix, player, values, differences)
        # v0.17.0: exclude self-inflicted damage (src == dst) from the
        # DEALT side. A self-condition tick (e.g. skill 19426 on
        # wvw-large-fight) is recorded by arcdps with src == dst == the
        # player; EI counts it as damage TAKEN (defenses.damageBarrier /
        # damageTaken) but NOT as damage dealt (dpsAll / statsAll /
        # totalDamageDist stay unchanged by it). The ``taken`` aggregate
        # below still includes it because it filters ``damage_events`` on
        # target only.
        source_damage = [
            event
            for event in damage_events
            if event.source_agent_id in agent_ids and event.source_agent_id != event.target_agent_id
        ]
        actor_damage = [event for event in source_damage if event.src_master_instid == 0]
        source_cc = [event for event in cc_events if event.source_agent_id in agent_ids]

        dps_all = player.get("dpsAll")
        if isinstance(dps_all, list) and dps_all and isinstance(dps_all[0], dict):
            damage = sum(event.damage for event in source_damage)
            condition = sum(
                _condition_damage(event, condition_skill_ids) for event in source_damage
            )
            dps_values = {
                "damage": damage,
                "condiDamage": condition,
                "powerDamage": damage - condition,
            }
            values["dpsAll"] = dps_values
            _compare_fields(f"{prefix}.dpsAll", dps_all[0], dps_values, differences)

        defenses = player.get("defenses")
        if isinstance(defenses, list) and defenses and isinstance(defenses[0], dict):
            taken = [event for event in damage_events if event.target_agent_id in agent_ids]
            downed = [
                event
                for event in event_list
                if isinstance(event, DownEvent) and event.source_agent_id in agent_ids
            ]
            outcome_downs = {
                event.time_ms
                for event in event_list
                if isinstance(event, CombatOutcomeEvent)
                and event.outcome == "downed"
                and event.target_agent_id in agent_ids
            }
            defense_values = {
                "damageTaken": sum(event.damage for event in taken),
                "damageTakenCount": sum(_connected(event) for event in taken),
                "conditionDamageTaken": sum(
                    _condition_damage(event, condition_skill_ids) for event in taken
                ),
                "powerDamageTaken": sum(
                    event.damage - _condition_damage(event, condition_skill_ids) for event in taken
                ),
                "blockedCount": sum(
                    isinstance(event, BlockEvent) and event.source_agent_id == agent.id
                    for event in event_list
                ),
                "evadedCount": sum(
                    isinstance(event, DodgeEvent) and event.source_agent_id == agent.id
                    for event in event_list
                ),
                "downCount": (
                    len(outcome_downs)
                    if outcome_downs and not anonymous
                    else len(
                        {
                            event.time_ms
                            for event in event_list
                            if isinstance(event, BoonApplyEvent)
                            and event.kind == "apply"
                            and event.skill_id == 770
                            and event.target_agent_id in agent_ids
                        }
                    )
                )
                or (
                    len(downed)
                    if anonymous
                    else len(outcome_downs)
                    if not has_downed_buff_applies
                    else 0
                ),
                "downDuration": sum(event.downtime_ms for event in downed),
                "deadCount": sum(
                    isinstance(event, DeathEvent) and event.source_agent_id in agent_ids
                    for event in event_list
                ),
            }
            values["defenses"] = defense_values
            _compare_fields(f"{prefix}.defenses", defenses[0], defense_values, differences)

        stats_all = player.get("statsAll")
        if isinstance(stats_all, list) and stats_all and isinstance(stats_all[0], dict):
            stats_values = _damage_stats(
                actor_damage,
                source_cc,
                down_by_source.get(agent.id),
                noncritable_skill_ids,
                condition_skill_ids,
            )
            values["statsAll"] = stats_values
            _compare_fields(
                prefix + ".statsAll", stats_all[0], stats_values, differences, _STAT_FIELDS
            )

        expected_buffs = player.get("buffUptimes")
        if isinstance(expected_buffs, list):
            uptime = dict.fromkeys(TRACKED_BUFFS, 0.0)
            for alias_id in agent_ids:
                alias_uptime = tracker.compute_player_uptimes(alias_id, duration_ms)
                for name, value in alias_uptime.items():
                    uptime[name] += value
            for name, value in uptime.items():
                if name not in MAX_STACKS:
                    uptime[name] = min(100.0, value)
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
                if (
                    not isinstance(expected_uptime, int | float)
                    or abs(expected_uptime - compared_buffs[buff_id]) > 0.005
                ):
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
                # An EI target is an instance, and arcdps hands the same
                # instance ID to every agent record that instance produced
                # over the fight (a player who dies and respawns, a minion
                # re-summoned). Matching on one agent ID drops the damage
                # dealt to the others, which is why per-target totals came
                # up short while the whole-fight totals matched.
                target_ids = (
                    agent_ids_by_instance.get(target["instanceID"], {target_agent.id})
                    if target_agent is not None
                    else set()
                )
                target_damage = [
                    event for event in source_damage if event.target_agent_id in target_ids
                ]
                actor_target_damage = [
                    event for event in target_damage if event.src_master_instid == 0
                ]
                target_cc = [event for event in source_cc if event.target_agent_id in target_ids]
                target_down_rows = DownContributionAggregator().aggregate(
                    actor_target_damage,
                    [
                        event
                        for event in event_list
                        if isinstance(event, DownEvent) and event.source_agent_id in target_ids
                    ],
                    [
                        event
                        for event in event_list
                        if isinstance(event, DeathEvent) and event.source_agent_id in target_ids
                    ],
                    duration_ms / 1000,
                    health_events=[
                        event
                        for event in event_list
                        if isinstance(event, HealthUpdateEvent)
                        and event.source_agent_id in target_ids
                    ],
                    up_events=[
                        event
                        for event in event_list
                        if isinstance(event, UpEvent) and event.source_agent_id in target_ids
                    ],
                    outcome_events=[
                        event
                        for event in event_list
                        if isinstance(event, CombatOutcomeEvent)
                        and event.target_agent_id in target_ids
                    ],
                    cc_events=target_cc,
                )
                target_down_by_source = {row.source_agent_id: row for row in target_down_rows}
                target_stats = _damage_stats(
                    actor_target_damage,
                    target_cc,
                    target_down_by_source.get(agent.id),
                    noncritable_skill_ids,
                    condition_skill_ids,
                )
                target_values = {
                    "damage": sum(event.damage for event in target_damage),
                    "condiDamage": sum(
                        _condition_damage(event, condition_skill_ids) for event in target_damage
                    ),
                    "powerDamage": sum(
                        event.damage - _condition_damage(event, condition_skill_ids)
                        for event in target_damage
                    ),
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
            actual_skills = _skill_stats(actor_damage)
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
                    actual_skills.get(
                        skill_id,
                        {"totalDamage": 0, "connectedHits": 0, "crit": 0, "critDamage": 0},
                    ),
                    differences,
                    ("totalDamage", "connectedHits", "crit", "critDamage"),
                )

        compared_players[account] = values

    actual["players"] = compared_players
    return {"matches": not differences, "compared": actual, "differences": differences}


__all__ = ["compare_elite_insights"]
