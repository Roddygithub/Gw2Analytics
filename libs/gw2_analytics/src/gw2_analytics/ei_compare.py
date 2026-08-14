"""Compare parsed combat data with an Elite Insights detailed JSON export."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from gw2_analytics.buff_state import MAX_STACKS, TRACKED_BUFFS, BuffStateTracker
from gw2_analytics.damage_predicates import absorbed_hit, landed_hit
from gw2_analytics.down_contribution import DownContributionAggregator
from gw2_analytics.initial_buffs import extract_initial_buffs
from gw2_analytics.rotation import build_skill_rotation
from gw2_core import (
    Agent,
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    BuffExtensionEvent,
    BuffStackActiveEvent,
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
    InterruptEvent,
    Profession,
    UpEvent,
    spec_display_name,
)

#: Exact mirror of Elite Insights' ``RangerHelper.JuvenilePetIDs``
#: (union of the 11 juvenile-pet family lists + the base list). A spawn
#: of one of these agents becomes the ``-28`` "Ranger Pet Spawned"
#: rotation entry on its master. ``JuvenilePhoenix`` (25131) is
#: deliberately absent -- EI credits it only via
#: ``MinionCommandCastFinder(GaleBreath)``, so a phoenix spawn must NOT
#: emit ``-28``.
# ponytail:EIJuvenilePetIDs -- from EI RangerHelper.cs / SpeciesIDs.cs
_JUVENILE_PET_SPECIES: frozenset[int] = frozenset(
    {
        3827,
        4425,
        4426,
        5581,
        5582,
        6043,
        6044,
        6045,
        6849,
        6850,
        6883,
        6884,
        6885,
        6886,
        6887,
        6888,
        6889,
        6898,
        6968,
        7336,
        7926,
        7927,
        7928,
        7932,
        7948,
        7949,
        7975,
        7976,
        8002,
        8003,
        8004,
        8005,
        8006,
        8007,
        8008,
        8013,
        8014,
        8015,
        8016,
        8035,
        8041,
        8042,
        9458,
        10022,
        11491,
        15380,
        15399,
        15402,
        15418,
        15436,
        18119,
        18688,
        19005,
        19104,
        19166,
        24203,
        24298,
        24796,
        25652,
        26147,
        26220,
        26628,
        26851,
        27259,
        27687,
    }
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


def _atomic_result(
    key: str,
    matched: bool,
    expected: object,
    actual: object,
    rule: str,
    dimensions: dict[str, object] | None,
) -> dict[str, object]:
    delta: object = None
    if (
        isinstance(expected, (int, float))
        and isinstance(actual, (int, float))
        and not isinstance(expected, bool)
        and not isinstance(actual, bool)
    ):
        computed = actual - expected
        if math.isfinite(computed):
            delta = computed
    return {
        "key": key,
        "status": "PASS" if matched else "FAIL",
        "expected": expected,
        "actual": actual,
        "delta": delta,
        "rule": rule,
        "dimensions": dict(dimensions or {}),
    }


def _compare_fields(
    prefix: str,
    expected: dict[str, Any],
    actual: dict[str, Any],
    differences: dict[str, object],
    fields: Sequence[str] | None = None,
    *,
    results: list[dict[str, object]] | None = None,
    rule: str = "field-equal",
    dimensions: dict[str, object] | None = None,
) -> None:
    for field in fields or tuple(actual):
        if field in expected:
            exp = expected[field]
            act = actual.get(field)
            if exp != act:
                differences[f"{prefix}.{field}"] = {"expected": exp, "actual": act}
            if results is not None:
                results.append(
                    _atomic_result(f"{prefix}.{field}", exp == act, exp, act, rule, dimensions)
                )


def _rotation_unmatched(
    expected: Sequence[tuple[int, int, int]],
    actual: Sequence[tuple[int, int, int]],
    *,
    prefix: str,
    results: list[dict[str, object]],
    dimensions: dict[str, object] | None = None,
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    remaining = list(actual)
    missing: list[tuple[int, int, int]] = []
    for skill_id, cast_time, duration in expected:
        match = next(
            (
                index
                for index, other in enumerate(remaining)
                if other[0] == skill_id
                and (
                    (other[2] == duration and abs(other[1] - cast_time) <= 2)
                    or (other[1] == cast_time and (other[2] == 0 or duration == 0))
                )
            ),
            None,
        )
        if match is None:
            missing.append((skill_id, cast_time, duration))
            results.append(
                _atomic_result(
                    f"{prefix}.rotation[castTime={cast_time}][duration={duration}][skillID={skill_id}]",
                    False,
                    (skill_id, cast_time, duration),
                    None,
                    "rotation-cast-match",
                    {**(dimensions or {}), "skill_id": skill_id},
                )
            )
        else:
            matched = remaining.pop(match)
            results.append(
                _atomic_result(
                    f"{prefix}.rotation[castTime={cast_time}][duration={duration}][skillID={skill_id}]",
                    True,
                    (skill_id, cast_time, duration),
                    matched,
                    "rotation-cast-match",
                    {**(dimensions or {}), "skill_id": skill_id},
                )
            )
    extra = remaining
    for skill_id, cast_time, duration in extra:
        results.append(
            _atomic_result(
                f"{prefix}.rotation[castTime={cast_time}][duration={duration}][skillID={skill_id}]",
                False,
                None,
                (skill_id, cast_time, duration),
                "rotation-cast-match",
                {**(dimensions or {}), "skill_id": skill_id},
            )
        )
    return missing, extra


def _defense_landed_hit(event: DamageEvent) -> bool:
    return landed_hit(event) and not (
        not event.is_condition and event.result == 10 and event.damage == 0 and event.buff_dmg == 0
    )


def _damage_stats(
    damage: list[DamageEvent],
    crowd_control: list[CCEvent],
    down_row: object | None,
    noncritable_skill_ids: set[int],
    condition_skill_ids: set[int] | None,
) -> dict[str, int]:
    counted = [event for event in damage if event.result != 10]
    connected = [event for event in counted if landed_hit(event)]
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
        "invulned": sum(absorbed_hit(event) for event in counted),
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


def _skill_stats(
    events: list[DamageEvent], interrupted_skills: set[int] | None = None
) -> dict[int, dict[str, int]]:
    by_skill: dict[int, list[DamageEvent]] = defaultdict(list)
    for event in events:
        by_skill[event.skill_id].append(event)
    result: dict[int, dict[str, int]] = {}
    for skill_id, skill_events in by_skill.items():
        # EI's ``connectedHits`` rule for direct Breakbar hits (result=10)
        # is group-level, not per-record: a breakbar tick damages the
        # defiance bar rather than health, so EI only counts result-10
        # hits when the player never managed a normal landed hit on that
        # skill -- in which case the breakbar ticks ARE the skill's entry.
        # If any normal landed (0/1/2) or condition landed hit exists, EI
        # books the entry from those and drops result-10. And if the skill
        # has only result-10 plus other non-landed (blocked/evaded/blind)
        # records, EI omits the entry entirely (connectedHits = 0).
        #
        # Verified across the 35-log corpus: 45 over-counts (mixed normals
        # and breakbar) and 8 under-counts (breakbar-only) and 7 misses
        # (breakbar + blocked/evaded only) all explained by this rule.
        #
        # One further corner: when the player interrupted an enemy cast
        # with that skill (an InterruptEvent from the same source), EI
        # books the entry as ``interrupted`` and drops the breakbar-only
        # hit, so connectedHits = 0. Only breakbar-only skills can hit
        # this; a skill with landed normals keeps the normal count.
        # Verified across the corpus: the only two such cases (skills
        # 5930 / 12621 on 20260508-001302) are the sole remaining diffs.
        direct = [e for e in skill_events if not e.is_condition]
        condi = [e for e in skill_events if e.is_condition]
        n_norm_direct = sum(e.result in {0, 1, 2} for e in direct)
        n_condi_landed = sum(landed_hit(e) for e in condi)
        n_breakbar = sum(e.result == 10 for e in direct)
        n_other_failed = sum(e.result not in {0, 1, 2, 10} for e in direct)
        if n_norm_direct + n_condi_landed > 0:
            # Normals exist: EI counts the normals and skips breakbar ticks.
            connected = n_norm_direct + n_condi_landed
        elif n_other_failed == 0 and skill_id not in (interrupted_skills or ()):
            # Only breakbar hits: EI counts them -- unless the skill
            # interrupted an enemy cast, which books the entry as
            # interrupted (connectedHits = 0).
            connected = n_breakbar + n_condi_landed
        else:
            # Breakbar plus blocked/evaded/blind only, or an interrupting
            # breakbar skill: EI drops the skill.
            connected = 0
        direct_crits = [event for event in direct if event.result in {1, 8} and event.buff_dmg == 0]
        result[skill_id] = {
            "totalDamage": sum(event.damage for event in skill_events),
            "connectedHits": connected,
            "crit": len(direct_crits),
            "critDamage": sum(event.damage for event in direct_crits),
        }
    return result


def _slice_bounds(player: dict[str, Any], origin: int) -> tuple[int, int]:
    """Absolute ms bounds of the fight slice one EI player entry covers.

    Elite Insights does not emit one entry per player: it emits one per
    *contiguous stretch of squad membership*. A player who leaves and
    rejoins the squad -- or who is simply out of it before the recorder
    picks them up -- appears several times under the same account and the
    same instance ID, with adjacent, non-overlapping firstAware/lastAware
    windows and a different ``group`` on each. Every counter on an entry
    covers only that stretch.

    arcdps has no such notion: one agent record spans the whole fight. So
    each EI entry has to be compared against the matching slice of our
    event stream rather than against the player's whole-fight totals.
    """
    first = player.get("firstAware")
    last = player.get("lastAware")
    if not isinstance(first, int) or not isinstance(last, int) or last < first:
        return (-(1 << 62), 1 << 62)
    return (origin + first, origin + last)


#: How far before the fight ends an actor's last-aware has to fall before we
#: treat it as "gone" and stop simulating its buffs there.
#:
#: EI runs each actor's buff simulation to the end of the phase, so a player
#: present throughout must not be clamped -- their last-aware trails the phase
#: end by a few tens of milliseconds purely because that is when their last
#: record happens to land, and clamping on it shaves ~0.1 points off every
#: uptime. A player who actually leaves is a different case: their still-active
#: boons would otherwise run to the end of the fight and add the whole absence
#: window to each one.
#:
#: The corpus separates the two cleanly -- absence is 70 ms at the median and
#: jumps to 15 s at the 90th percentile, with a single player anywhere between
#: 1 s and 5 s -- so any bound inside that gap behaves identically. Measured:
#: 0 ms and 50 ms regress badly (440 and 251 buff differences over five logs
#: against 87 unclamped), while 1 s and 3 s both give 79.
_ABSENCE_FLOOR_MS = 1_000

#: Despawn grace, mirroring the tracker's own end_agent(t + 10) convention.
_DESPAWN_GRACE_MS = 10


def _team_for_entry(is_last_slice: bool, team_id: int) -> int:
    """EI reports an actor's team only on the last entry of its account.

    arcdps has no team column in the agent table: the team arrives in a
    ``CBTS_TEAMCHANGE`` record, and EI carries the *final* value on the
    entry that is current at the end of the fight, leaving 0 on the
    earlier slices of a split account.

    The rule is "last slice", not "team known at the slice's end": on
    20260412-220632 the record lands after every single-entry player's
    lastAware, yet EI still reports 707 for them. Keying on the timestamp
    instead fixed 22 differences and broke 36.
    """
    return team_id if is_last_slice else 0


def _awareness_bound(
    agent_awareness: dict[int, tuple[int, int]] | None, alias_id: int, duration_ms: int
) -> int | None:
    """Last-aware to stop an alias's buff simulation at, or ``None`` to run on."""
    if not agent_awareness:
        return None
    span = agent_awareness.get(alias_id)
    if span is None or duration_ms - span[1] <= _ABSENCE_FLOOR_MS:
        return None
    return span[1] + _DESPAWN_GRACE_MS


def compare_elite_insights(  # noqa: PLR0912, PLR0915
    fight: Fight,
    expected: dict[str, object],
    events: Sequence[Event],
    agent_awareness: dict[int, tuple[int, int]] | None = None,
    regen_overstacks: dict[int, list[tuple[int, int, int]]] | None = None,
    ownership_intervals: list[OwnershipInterval] | None = None,
) -> dict[str, object]:
    """Return a JSON-serializable comparison report.

    ``agent_awareness`` maps agent id to ``(first_aware_ms, last_aware_ms)``
    as produced by :func:`gw2_evtc_parser.scan_agent_awareness`. It bounds
    each actor's buff simulation: EI stops accruing uptime once the log
    stops seeing an actor, whereas the tracker would otherwise run that
    actor's still-active buffs to the end of the fight. Optional so
    hand-built event streams keep working; without it the previous
    whole-fight behaviour applies.

    """
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
    results: list[dict[str, object]] = []
    _compare_fields(
        "",
        expected,
        actual,
        differences,
        fields=tuple(field for field in tuple(actual) if field != "players"),
        results=results,
        rule="header-field",
    )
    differences = {key.removeprefix("."): value for key, value in differences.items()}
    for result in results:
        key = result.get("key")
        result["key"] = key.removeprefix(".") if isinstance(key, str) else key

    expected_players = expected.get("players")
    if not isinstance(expected_players, list):
        return {
            "matches": not differences,
            "compared": actual,
            "differences": differences,
            "results": results,
        }

    event_list = list(events)
    origin = (
        header.start_time_ms
        if header and header.start_time_ms is not None
        else min((event.time_ms for event in event_list), default=0)
    )
    duration_ms = header.duration_ms if header and header.duration_ms else 0
    damage_events = [event for event in event_list if isinstance(event, DamageEvent)]
    actor_damage_events = [event for event in damage_events if event.src_master_instid == 0]
    cc_events = [event for event in event_list if isinstance(event, CCEvent)]
    interrupt_events = [event for event in event_list if isinstance(event, InterruptEvent)]
    down_events = [event for event in event_list if isinstance(event, DownEvent)]
    death_events = [event for event in event_list if isinstance(event, DeathEvent)]
    health_events = [event for event in event_list if isinstance(event, HealthUpdateEvent)]
    up_events = [event for event in event_list if isinstance(event, UpEvent)]
    outcome_events = [event for event in event_list if isinstance(event, CombatOutcomeEvent)]
    down_rows = DownContributionAggregator().aggregate(
        actor_damage_events,
        down_events,
        death_events,
        duration_ms / 1000,
        health_events=health_events,
        up_events=up_events,
        outcome_events=outcome_events,
        cc_events=cc_events,
    )
    down_by_source = {row.source_agent_id: row for row in down_rows}

    # A split account's entries each carry their own slice of the fight, and
    # EI's down-contribution counters follow that split -- for
    # krill le faucheur.1679 on 20260125-194936 the three slices report 0 /
    # 1894 / 11441, summing to the 13335 the whole-fight row holds. The
    # damage events feeding statsAll are already sliced; the down row was
    # not, so every slice of a split account reported the whole-fight total.
    # Cached per window because entries of one account share a slice shape
    # and the aggregation walks the whole event stream.
    sliced_down_cache: dict[tuple[int, int], dict[int, object]] = {}

    def down_rows_for_slice(lo: int, hi: int) -> dict[int, object]:
        cached = sliced_down_cache.get((lo, hi))
        if cached is None:
            rows = DownContributionAggregator().aggregate(
                [event for event in actor_damage_events if lo <= event.time_ms <= hi],
                [event for event in down_events if lo <= event.time_ms <= hi],
                [event for event in death_events if lo <= event.time_ms <= hi],
                duration_ms / 1000,
                health_events=[event for event in health_events if lo <= event.time_ms <= hi],
                up_events=[event for event in up_events if lo <= event.time_ms <= hi],
                outcome_events=[event for event in outcome_events if lo <= event.time_ms <= hi],
                cc_events=[event for event in cc_events if lo <= event.time_ms <= hi],
            )
            cached = {row.source_agent_id: row for row in rows}
            sliced_down_cache[(lo, hi)] = cached
        return cached

    agents_by_account: dict[str, list[Agent]] = defaultdict(list)
    for fight_agent in fight.agents:
        if fight_agent.account_name:
            agents_by_account[fight_agent.account_name.lstrip(":")].append(fight_agent)
    agents_by_instance: dict[int, Agent] = {}
    agents_by_instance_entries: dict[int, list[Agent]] = defaultdict(list)
    for fight_agent in fight.agents:
        if fight_agent.instance_id:
            agents_by_instance.setdefault(fight_agent.instance_id, fight_agent)
            agents_by_instance_entries[fight_agent.instance_id].append(fight_agent)
    agent_ids_by_instance: dict[int, set[int]] = defaultdict(set)
    for fight_agent in fight.agents:
        if fight_agent.instance_id:
            agent_ids_by_instance[fight_agent.instance_id].add(fight_agent.id)
    down_events_by_source: dict[int, list[DownEvent]] = defaultdict(list)
    death_events_by_source: dict[int, list[DeathEvent]] = defaultdict(list)
    health_events_by_source: dict[int, list[HealthUpdateEvent]] = defaultdict(list)
    up_events_by_source: dict[int, list[UpEvent]] = defaultdict(list)
    outcome_events_by_target: dict[int, list[CombatOutcomeEvent]] = defaultdict(list)
    block_count_by_source: dict[int, int] = defaultdict(int)
    dodge_count_by_source: dict[int, int] = defaultdict(int)
    block_events_by_source: dict[int, list[BlockEvent]] = defaultdict(list)
    dodge_events_by_source: dict[int, list[DodgeEvent]] = defaultdict(list)
    downed_buff_times_by_target: dict[int, set[int]] = defaultdict(set)
    for down_event in down_events:
        down_events_by_source[down_event.source_agent_id].append(down_event)
    for death_event in death_events:
        death_events_by_source[death_event.source_agent_id].append(death_event)
    for health_event in health_events:
        health_events_by_source[health_event.source_agent_id].append(health_event)
    for up_event in up_events:
        up_events_by_source[up_event.source_agent_id].append(up_event)
    for outcome_event in outcome_events:
        outcome_events_by_target[outcome_event.target_agent_id].append(outcome_event)
    for indexed_event in event_list:
        if isinstance(indexed_event, BlockEvent):
            block_count_by_source[indexed_event.source_agent_id] += 1
            block_events_by_source[indexed_event.source_agent_id].append(indexed_event)
        elif isinstance(indexed_event, DodgeEvent):
            dodge_count_by_source[indexed_event.source_agent_id] += 1
            dodge_events_by_source[indexed_event.source_agent_id].append(indexed_event)
        elif (
            isinstance(indexed_event, BoonApplyEvent)
            and indexed_event.kind == "apply"
            and indexed_event.skill_id == 770
        ):
            downed_buff_times_by_target[indexed_event.target_agent_id].add(indexed_event.time_ms)

    def indexed_events(index: dict[int, list[Any]], agent_ids: set[int]) -> list[Any]:
        return [
            indexed_event for agent_id in agent_ids for indexed_event in index.get(agent_id, [])
        ]

    def select_player_agent(player: dict[str, Any], account: str) -> Agent | None:
        instance_id = player.get("instanceID")
        if account.startswith("Non Squad Player") and isinstance(instance_id, int):
            anonymous = [
                agent
                for agent in agents_by_instance_entries.get(instance_id, [])
                if agent.account_name is None
            ]
            if anonymous:
                return anonymous[0]
        candidates = agents_by_account.get(account, [])
        expected_name = player.get("name")
        if isinstance(expected_name, str):
            for agent in candidates:
                if agent.name == expected_name:
                    return agent
        expected_profession = player.get("profession")
        if isinstance(expected_profession, str):
            for agent in candidates:
                if spec_display_name(agent.profession, agent.elite) == expected_profession:
                    return agent
        if candidates:
            return candidates[-1]
        if isinstance(instance_id, int):
            return agents_by_instance.get(instance_id)
        return None

    def player_agent_ids(agent: Agent) -> set[int]:
        if not agent.instance_id:
            return {agent.id}
        entries = agents_by_instance_entries.get(agent.instance_id, [])
        accounts = {entry.account_name for entry in entries}
        if len(accounts) > 1:
            return {agent.id}
        return agent_ids_by_instance.get(agent.instance_id, {agent.id})

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

    healing_by_agent = {agent.id: agent.healing for agent in fight.agents}
    tracker = BuffStateTracker(
        start_time_ms=origin,
        healing_by_agent=healing_by_agent,
        regen_overstacks=regen_overstacks,
    )
    for tracked_event in event_list:
        if isinstance(
            tracked_event,
            (BoonApplyEvent, BuffApplyEvent, BuffExtensionEvent, BuffStackActiveEvent),
        ):
            tracker.process(tracked_event)
        elif isinstance(tracked_event, DespawnEvent):
            tracker.end_agent(tracked_event.source_agent_id, tracked_event.time_ms + 10)
    rotation = build_skill_rotation(
        event_list,
        duration_ms,
        origin,
        {agent.id for agent in fight.agents if agent.elite == EliteSpec.VIRTUOSO},
        {
            agent.id
            for agent in fight.agents
            if agent.profession == Profession.MESMER
            and agent.elite in {EliteSpec.UNKNOWN, EliteSpec.MIRAGE, EliteSpec.CHRONOMANCER}
        },
        {agent.id for agent in fight.agents if agent.species_id == 8111},
        {agent.id for agent in fight.agents if agent.species_id in _JUVENILE_PET_SPECIES},
        {agent.id for agent in fight.agents if agent.species_id == 24796},
        {agent.id for agent in fight.agents if agent.species_id == 15402},
        {agent.id for agent in fight.agents if agent.species_id == 7336},
        {agent.id for agent in fight.agents if agent.species_id == 26628},
        {agent.id for agent in fight.agents if agent.species_id == 3827},
        {agent.id for agent in fight.agents if agent.species_id == 23549},
        professions={agent.id: agent.profession for agent in fight.agents},
        elite_specs={agent.id: agent.elite for agent in fight.agents},
        agent_id_by_instance={
            agent.instance_id: agent.id for agent in fight.agents if agent.instance_id
        },
    )
    has_downed_buff_applies = any(
        isinstance(event, BoonApplyEvent) and event.kind == "apply" and event.skill_id == 770
        for event in event_list
    )
    account_last_slice: dict[str, object] = {}
    account_names: dict[str, set[str]] = defaultdict(set)
    for entry in expected_players:
        if isinstance(entry, dict) and isinstance(entry.get("account"), str):
            first = entry.get("firstAware")
            previous = account_last_slice.get(entry["account"])
            if isinstance(first, int) and (not isinstance(previous, int) or first > previous):
                account_last_slice[entry["account"]] = first
            name = entry.get("name")
            if isinstance(name, str):
                account_names[entry["account"]].add(name)
    account_entry_count: Counter[str] = Counter(
        entry["account"]
        for entry in expected_players
        if isinstance(entry, dict) and isinstance(entry.get("account"), str)
    )
    # A split account (character swap) is reported by EI as several ``players``
    # entries, one per lifespan slice, and each slice's buffUptimes covers only
    # its own window. The in-house tracker computes whole-fight presence, which
    # equals the *sum* of the slice uptimes (verified on the corpus: Mikey's 3
    # slices 46.3+1.5+52.2 = tracker 100.0). Aggregate the expected uptimes per
    # account so the comparison is against the sum, not each slice.
    account_buff_uptime: dict[str, dict[int, float]] = {}
    for entry in expected_players:
        if not isinstance(entry, dict) or not isinstance(entry.get("account"), str):
            continue
        expected_buffs = entry.get("buffUptimes")
        if not isinstance(expected_buffs, list):
            continue
        per_buff = account_buff_uptime.setdefault(entry["account"], {})
        for buff in expected_buffs:
            if not isinstance(buff, dict) or not isinstance(buff.get("id"), int):
                continue
            buff_data = buff.get("buffData")
            if (
                not isinstance(buff_data, list)
                or not buff_data
                or not isinstance(buff_data[0], dict)
            ):
                continue
            uptime = buff_data[0].get("uptime")
            if isinstance(uptime, int | float):
                per_buff[buff["id"]] = per_buff.get(buff["id"], 0.0) + uptime
    compared_players: dict[str, object] = {}
    # Split accounts repeat the same whole-fight buff diff on every slice
    # entry; report it once per (account, buff).
    reported_buff_diffs: set[tuple[str, int]] = set()

    for player in expected_players:
        if not isinstance(player, dict) or not isinstance(player.get("account"), str):
            continue
        account = player["account"]
        agent = select_player_agent(player, account)
        if agent is None:
            compared_players[account] = None
            differences[f"players[{account}]"] = {"expected": "present", "actual": None}
            results.append(
                _atomic_result(
                    f"players[{account}]",
                    False,
                    "present",
                    None,
                    "player-present",
                    {"account": account, "slice": player.get("firstAware")},
                )
            )
            continue
        slice_lo, slice_hi = _slice_bounds(player, origin)
        # Several EI entries can share an account; key the report by the
        # slice so their differences do not overwrite each other.
        prefix = (
            f"players[{account}]"
            if account_entry_count[account] < 2
            else f"players[{account}@{player.get('firstAware')}]"
        )
        player_dims: dict[str, object] = {"account": account, "slice": player.get("firstAware")}
        anonymous = agent.account_name is None
        agent_ids = agent_ids_by_instance.get(agent.instance_id, {agent.id})

        whole_fight_slice = slice_lo <= origin and slice_hi >= origin + duration_ms

        def in_slice(event: Event, _lo: int = slice_lo, _hi: int = slice_hi) -> bool:
            return _lo <= event.time_ms <= _hi

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
            "teamID": _team_for_entry(
                len(account_names[account]) > 1
                or player.get("firstAware") == account_last_slice.get(account),
                agent.team_id,
            ),
        }
        _compare_fields(
            prefix,
            player,
            values,
            differences,
            results=results,
            rule="player-field",
            dimensions=player_dims,
        )
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
            if event.source_agent_id in agent_ids
            and event.source_agent_id != event.target_agent_id
            and in_slice(event)
        ]
        actor_damage = [event for event in source_damage if event.src_master_instid == 0]
        source_interrupts = {
            event.skill_id
            for event in interrupt_events
            if event.source_agent_id in agent_ids and in_slice(event)
        }
        source_cc = [
            event for event in cc_events if event.source_agent_id in agent_ids and in_slice(event)
        ]

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
            _compare_fields(
                f"{prefix}.dpsAll",
                dps_all[0],
                dps_values,
                differences,
                results=results,
                rule="dpsAll-field",
                dimensions=player_dims,
            )

        defenses = player.get("defenses")
        if isinstance(defenses, list) and defenses and isinstance(defenses[0], dict):
            taken = [
                event
                for event in damage_events
                if event.target_agent_id in agent_ids and in_slice(event)
            ]
            downed = [
                event
                for event in indexed_events(down_events_by_source, agent_ids)
                if in_slice(event)
            ]
            outcome_downs = {
                event.time_ms
                for event in indexed_events(outcome_events_by_target, agent_ids)
                if event.outcome == "downed" and in_slice(event)
            }
            defense_values = {
                "damageTaken": sum(event.damage for event in taken),
                "damageTakenCount": sum(_defense_landed_hit(event) for event in taken),
                "conditionDamageTaken": sum(
                    _condition_damage(event, condition_skill_ids) for event in taken
                ),
                "powerDamageTaken": sum(
                    event.damage - _condition_damage(event, condition_skill_ids) for event in taken
                ),
                "blockedCount": block_count_by_source[agent.id]
                if whole_fight_slice
                else sum(1 for event in block_events_by_source[agent.id] if in_slice(event)),
                "evadedCount": dodge_count_by_source[agent.id]
                if whole_fight_slice
                else sum(1 for event in dodge_events_by_source[agent.id] if in_slice(event)),
                "downCount": (
                    len(outcome_downs)
                    if outcome_downs and not anonymous
                    else len(
                        {
                            time_ms
                            for agent_id in agent_ids
                            for time_ms in downed_buff_times_by_target[agent_id]
                            if slice_lo <= time_ms <= slice_hi
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
                    1
                    for event in indexed_events(death_events_by_source, agent_ids)
                    if in_slice(event)
                ),
            }
            values["defenses"] = defense_values
            _compare_fields(
                f"{prefix}.defenses",
                defenses[0],
                defense_values,
                differences,
                results=results,
                rule="defenses-field",
                dimensions=player_dims,
            )

        stats_all = player.get("statsAll")
        if isinstance(stats_all, list) and stats_all and isinstance(stats_all[0], dict):
            stats_values = _damage_stats(
                actor_damage,
                source_cc,
                (
                    down_by_source if whole_fight_slice else down_rows_for_slice(slice_lo, slice_hi)
                ).get(agent.id),
                noncritable_skill_ids,
                condition_skill_ids,
            )
            values["statsAll"] = stats_values
            _compare_fields(
                prefix + ".statsAll",
                stats_all[0],
                stats_values,
                differences,
                _STAT_FIELDS,
                results=results,
                rule="statsAll-field",
                dimensions=player_dims,
            )

        expected_buffs = player.get("buffUptimes")
        if isinstance(expected_buffs, list):
            # Each entry's buffUptimes is whole-fight in shape (not restricted
            # to the slice: windowing them measurably diverges), but a split
            # account's slices each carry the fraction of uptime they cover, so
            # the whole-fight expected value is their sum -- see
            # ``account_buff_uptime`` above.
            uptime = dict.fromkeys(TRACKED_BUFFS, 0.0)
            # Stop each alias's simulation at its own last-aware. A player
            # who drops off the log mid-fight keeps whatever boons were up
            # at that moment, and running them to the end of the fight adds
            # exactly the absence window to every one of them -- the
            # signature was several buffs on one actor all overcounting by
            # the identical amount.
            for alias_id in player_agent_ids(agent):
                alias_uptime = tracker.compute_player_uptimes(
                    alias_id,
                    duration_ms,
                    active_duration_ms=_awareness_bound(agent_awareness, alias_id, duration_ms),
                )
                for name, value in alias_uptime.items():
                    uptime[name] += value
            for name, value in uptime.items():
                if name not in MAX_STACKS:
                    uptime[name] = min(100.0, value)
            by_id = {buff_id: uptime[name] for name, buff_id in TRACKED_BUFFS.items()}
            compared_buffs: dict[int, float] = {}
            # Expected per buff = whole-fight value, i.e. the sum over the
            # account's split entries (see account_buff_uptime). A buff that
            # EI omitted from one slice still contributes its other slices.
            account_expected = account_buff_uptime.get(account, {})
            for expected_buff in expected_buffs:
                if not isinstance(expected_buff, dict) or not isinstance(
                    expected_buff.get("id"), int
                ):
                    continue
                buff_id = expected_buff["id"]
                if buff_id not in by_id:
                    continue
                compared_buffs[buff_id] = round(by_id[buff_id], 3)
                expected_uptime = account_expected.get(buff_id)
                if (account, buff_id) in reported_buff_diffs:
                    continue
                reported_buff_diffs.add((account, buff_id))
                matched = (
                    expected_uptime is not None
                    and abs(expected_uptime - compared_buffs[buff_id]) <= 0.005
                )
                if not matched:
                    differences[f"{prefix}.buffUptimes[{buff_id}].uptime"] = {
                        "expected": expected_uptime,
                        "actual": compared_buffs[buff_id],
                    }
                results.append(
                    _atomic_result(
                        f"{prefix}.buffUptimes[{buff_id}].uptime",
                        matched,
                        expected_uptime,
                        compared_buffs[buff_id],
                        "buff-uptime-tolerance",
                        {**player_dims, "buff_id": buff_id},
                    )
                )
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
            has_active_ranger_pets = player.get("activeRangerPets") is not None
            actual_casts = sorted(
                (
                    (cast.skill_id, cast.time_ms, cast.duration_ms)
                    for cast in rotation
                    if cast.source_agent_id in agent_ids
                    and (cast.skill_id != -28 or has_active_ranger_pets)
                    and (
                        (cast.time_ms + origin >= slice_lo and cast.time_ms + origin <= slice_hi)
                        or (
                            cast.time_ms < 0
                            and slice_lo <= cast.time_ms + cast.duration_ms + origin <= slice_hi
                        )
                        or (
                            cast.skill_id == -28
                            and cast.time_ms + origin <= slice_hi
                            and slice_lo - (cast.time_ms + origin) <= 2000
                        )
                    )
                ),
                key=lambda item: (item[1], item[0]),
            )
            values["rotation"] = actual_casts
            missing_casts, extra_casts = _rotation_unmatched(
                expected_casts,
                actual_casts,
                prefix=prefix,
                results=results,
                dimensions=player_dims,
            )
            if missing_casts or extra_casts:
                differences[f"{prefix}.rotation"] = {
                    "expected": missing_casts,
                    "actual": extra_casts,
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
                # Not sliced: consumables are pre-fight applications that EI
                # repeats on every entry of a split account, and a player whose
                # firstAware is later than the application would otherwise lose
                # them entirely.
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
                results.append(
                    _atomic_result(
                        f"{prefix}.consumables",
                        False,
                        expected_consumables,
                        actual_consumables,
                        "consumables-match",
                        player_dims,
                    )
                )
            else:
                results.append(
                    _atomic_result(
                        f"{prefix}.consumables",
                        True,
                        expected_consumables,
                        actual_consumables,
                        "consumables-match",
                        player_dims,
                    )
                )

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
                        for event in indexed_events(down_events_by_source, target_ids)
                        if in_slice(event)
                    ],
                    [
                        event
                        for event in indexed_events(death_events_by_source, target_ids)
                        if in_slice(event)
                    ],
                    duration_ms / 1000,
                    health_events=[
                        event
                        for event in indexed_events(health_events_by_source, target_ids)
                        if in_slice(event)
                    ],
                    up_events=[
                        event
                        for event in indexed_events(up_events_by_source, target_ids)
                        if in_slice(event)
                    ],
                    outcome_events=[
                        event
                        for event in indexed_events(outcome_events_by_target, target_ids)
                        if in_slice(event)
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
                        results=results,
                        rule="dpsTargets-field",
                        dimensions={
                            **player_dims,
                            "target_instance_id": target["instanceID"],
                        },
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
                        results=results,
                        rule="statsTargets-field",
                        dimensions={
                            **player_dims,
                            "target_instance_id": target["instanceID"],
                        },
                    )
            values["targets"] = compared_targets

        damage_dist = player.get("totalDamageDist")
        if isinstance(damage_dist, list) and damage_dist and isinstance(damage_dist[0], list):
            actual_skills = _skill_stats(actor_damage, source_interrupts)
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
                    results=results,
                    rule="totalDamageDist-field",
                    dimensions={**player_dims, "skill_id": skill_id},
                )

        compared_players[account] = values

    actual["players"] = compared_players
    return {
        "matches": not differences,
        "compared": actual,
        "differences": differences,
        "results": results,
    }


__all__ = ["compare_elite_insights"]
