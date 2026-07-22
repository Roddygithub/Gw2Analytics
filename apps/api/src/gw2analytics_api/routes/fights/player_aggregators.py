"""Combat-readout and position aggregation glue for /fights endpoints.

Wraps the 4 per-player aggregators (Player{Damage,Heal,Boons,Defense}),
the DownContributionAggregator, and the position-analysis helpers.
Extracted from the pre-A2 god module ``aggregators.py`` (plan 021).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Final, cast

from gw2_analytics.down_contribution import (
    DownContributionAggregator,
    DownContributionRow,
)
from gw2_analytics.player_boons import PlayerBoonsAggregator, PlayerBoonsRow
from gw2_analytics.player_damage import (
    DpsSplitGetter,
    PlayerDamageAggregator,
    PlayerDamageRow,
)
from gw2_analytics.player_defense import PlayerDefenseAggregator, PlayerDefenseRow
from gw2_analytics.player_heal import (
    HealBarrierGetter,
    PlayerHealAggregator,
    PlayerHealRow,
)
from gw2_analytics.position_analysis import compute_position_metrics
from gw2_analytics.role_detection import detect_role_lite
from gw2_core import (
    BlockEvent,
    BoonApplyEvent,
    BuffRemovalEvent,
    CCEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    DownEvent,
    EliteSpec,
    Event,
    HealingEvent,
    InterruptEvent,
    PositionEvent,
    StunBreakEvent,
    is_condition,
)
from gw2analytics_api.routes.fights.mappers import AgentIdentity
from gw2analytics_api.schemas import (
    FightReadoutOut,
    PlayerPositionOut,
    PlayerReadoutBoonsOut,
    PlayerReadoutDamageOut,
    PlayerReadoutDefenseOut,
    PlayerReadoutHealOut,
    PlayerReadoutOut,
    PositionSampleOut,
)


def _split_combat_readout_events(
    events: Iterable[Event],
) -> tuple[
    list[DamageEvent],
    list[HealingEvent],
    list[BoonApplyEvent],
    list[CCEvent],
    list[DeathEvent],
    list[DodgeEvent],
    list[BlockEvent],
    list[InterruptEvent],
    list[StunBreakEvent],
    list[DownEvent],
]:
    damage_events: list[DamageEvent] = []
    healing_events: list[HealingEvent] = []
    boon_apply_events: list[BoonApplyEvent] = []
    cc_events: list[CCEvent] = []
    death_events: list[DeathEvent] = []
    dodge_events: list[DodgeEvent] = []
    block_events: list[BlockEvent] = []
    interrupt_events: list[InterruptEvent] = []
    stun_break_events: list[StunBreakEvent] = []
    down_events: list[DownEvent] = []

    append_damage = damage_events.append
    append_healing = healing_events.append
    append_boon_apply = boon_apply_events.append
    append_cc = cc_events.append
    append_death = death_events.append
    append_dodge = dodge_events.append
    append_block = block_events.append
    append_interrupt = interrupt_events.append
    append_stun_break = stun_break_events.append
    append_down = down_events.append

    for event in events:
        if isinstance(event, DamageEvent):
            append_damage(event)
        elif isinstance(event, HealingEvent):
            append_healing(event)
        elif isinstance(event, BoonApplyEvent):
            append_boon_apply(event)
        elif isinstance(event, CCEvent):
            append_cc(event)
        elif isinstance(event, DeathEvent):
            append_death(event)
        elif isinstance(event, DodgeEvent):
            append_dodge(event)
        elif isinstance(event, BlockEvent):
            append_block(event)
        elif isinstance(event, InterruptEvent):
            append_interrupt(event)
        elif isinstance(event, StunBreakEvent):
            append_stun_break(event)
        elif isinstance(event, DownEvent):
            append_down(event)

    return (
        damage_events,
        healing_events,
        boon_apply_events,
        cc_events,
        death_events,
        dodge_events,
        block_events,
        interrupt_events,
        stun_break_events,
        down_events,
    )


_ZERO_DAMAGE_ROW = PlayerDamageRow(
    source_agent_id=0,
    total_damage=0,
    attack_count=1,
    dps=0.0,
    dps_power=0.0,
    dps_condi=0.0,
)
_ZERO_HEAL_ROW = PlayerHealRow(
    source_agent_id=0,
    total_healing=0,
    heal_count=1,
    hps=0.0,
    barrier_total=0,
    barrier_ps=0.0,
    stun_breaks=0,
)
_ZERO_DEFENSE_ROW = PlayerDefenseRow(
    agent_id=0,
    damage_taken=0,
    cc_taken=0,
    deaths=0,
)

_DETECTED_ROLE_LABELS: Final[dict[str, str]] = {
    "HEAL": "Heal",
    "BOON": "Support",
    "STRIP": "Strip",
    "DPS": "DPS",
}


def _build_player_readout(
    agent_id: int,
    identity: AgentIdentity,
    damage_row: PlayerDamageRow | None,
    heal_row: PlayerHealRow | None,
    boons_row: PlayerBoonsRow | None,
    defense_row: PlayerDefenseRow | None,
    *,
    cleanses: int = 0,
    strips: int = 0,
    cc_applied: int = 0,
    cleave_targets: int = 0,
    kill_participation: int = 0,
    down_contrib: tuple[float, int] | None = None,
    time_downed_ms: int = 0,
    boon_uptimes: dict[str, float] | None = None,
    presence_pct: float | None = None,
    dist_to_commander: float | None = None,
    roles: list[str] | None = None,
) -> PlayerReadoutOut:
    _uptimes = boon_uptimes or {}
    d_row = damage_row or _ZERO_DAMAGE_ROW
    h_row = heal_row or _ZERO_HEAL_ROW
    b_row = boons_row or PlayerBoonsRow(
        agent_id=0,
        boons_out=0,
        boons_in=0,
        boons_out_rate=0.0,
        boons_in_rate=0.0,
        stability_out=0,
        alacrity_out=0,
        resistance_out=0,
        aegis_out=0,
        superspeed_out=0,
        stealth_out=0,
    )
    def_row = defense_row or _ZERO_DEFENSE_ROW

    return PlayerReadoutOut(
        agent_id=agent_id,
        subgroup=identity.subgroup,
        name=identity.name,
        account_name=identity.account_name,
        profession=identity.profession,
        elite_spec=identity.elite_spec,
        is_commander=identity.is_commander,
        roles=roles or [],
        damage=PlayerReadoutDamageOut(
            dps_total=d_row.dps,
            dps_power=d_row.dps_power,
            dps_condi=d_row.dps_condi,
            strips=strips,
            cc_applied=cc_applied,
            cleave_targets=cleave_targets,
            kill_participation=kill_participation,
            down_contribution_dps=down_contrib[0] if down_contrib else 0.0,
            kills=down_contrib[1] if down_contrib else 0,
        ),
        heal=PlayerReadoutHealOut(
            heal_total=h_row.total_healing,
            hps=h_row.hps,
            barrier_total=h_row.barrier_total,
            barrier_ps=h_row.barrier_ps,
            cleanses=cleanses,
            stun_breaks=h_row.stun_breaks,
        ),
        boons=PlayerReadoutBoonsOut(
            boons_out_rate=b_row.boons_out_rate,
            boons_in_rate=b_row.boons_in_rate,
            stability_out=b_row.stability_out,
            alacrity_out=b_row.alacrity_out,
            resistance_out=b_row.resistance_out,
            aegis_out=b_row.aegis_out,
            superspeed_out=b_row.superspeed_out,
            stealth_out=b_row.stealth_out,
            other_boons_out=dict(b_row.other_boons_out),
            might_uptime=_uptimes.get("might"),
            fury_uptime=_uptimes.get("fury"),
            quickness_uptime=_uptimes.get("quickness"),
            alacrity_uptime=_uptimes.get("alacrity"),
            protection_uptime=_uptimes.get("protection"),
            regeneration_uptime=_uptimes.get("regeneration"),
            vigor_uptime=_uptimes.get("vigor"),
            aegis_uptime=_uptimes.get("aegis"),
            stability_uptime=_uptimes.get("stability"),
            swiftness_uptime=_uptimes.get("swiftness"),
            resistance_uptime=_uptimes.get("resistance"),
            resolution_uptime=_uptimes.get("resolution"),
            superspeed_uptime=_uptimes.get("superspeed"),
            stealth_uptime=_uptimes.get("stealth"),
            outgoing_might=_uptimes.get("outgoing_might"),
            outgoing_fury=_uptimes.get("outgoing_fury"),
            outgoing_quickness=_uptimes.get("outgoing_quickness"),
            outgoing_alacrity=_uptimes.get("outgoing_alacrity"),
            outgoing_protection=_uptimes.get("outgoing_protection"),
            outgoing_regeneration=_uptimes.get("outgoing_regeneration"),
            outgoing_vigor=_uptimes.get("outgoing_vigor"),
            outgoing_aegis=_uptimes.get("outgoing_aegis"),
            outgoing_stability=_uptimes.get("outgoing_stability"),
            outgoing_swiftness=_uptimes.get("outgoing_swiftness"),
            outgoing_resistance=_uptimes.get("outgoing_resistance"),
            outgoing_resolution=_uptimes.get("outgoing_resolution"),
            outgoing_superspeed=_uptimes.get("outgoing_superspeed"),
            outgoing_stealth=_uptimes.get("outgoing_stealth"),
        ),
        defense=PlayerReadoutDefenseOut(
            damage_taken=def_row.damage_taken,
            cc_taken=def_row.cc_taken,
            deaths=def_row.deaths,
            time_downed_ms=time_downed_ms if time_downed_ms > 0 else def_row.time_downed_ms,
            dodges=def_row.dodges,
            blocks=def_row.blocks,
            interrupts=def_row.interrupts,
            barrier_absorbed=def_row.barrier_absorbed,
            presence_pct=presence_pct,
            dist_to_commander=dist_to_commander,
            kill_participation=kill_participation,
        ),
    )



class _CombatCounters:
    """Aggregated counters extracted from raw events."""

    __slots__ = (
        "cc",
        "cleanses",
        "cleave_targets",
        "downtime",
        "kill_participation",
        "strips",
    )

    def __init__(self) -> None:
        self.cleanses: Counter[int] = Counter()
        self.strips: Counter[int] = Counter()
        self.cleave_targets: dict[int, set[int]] = {}
        self.kill_participation: Counter[int] = Counter()
        self.cc: Counter[int] = Counter()
        self.downtime: Counter[int] = Counter()


def _compute_combat_counters(
    events: list[Event],
    damage_events: list[DamageEvent],
    death_events: list[DeathEvent],
    down_events: list[DownEvent],
) -> _CombatCounters:
    """Extract buff removal, cleave, kill participation, CC, and downtime counters."""
    counters = _CombatCounters()

    for event in events:
        if isinstance(event, BuffRemovalEvent):
            if is_condition(event.buff_id):
                counters.cleanses[event.source_agent_id] += 1
            else:
                counters.strips[event.source_agent_id] += 1
        elif isinstance(event, DamageEvent):
            counters.cleave_targets.setdefault(
                event.source_agent_id, set(),
            ).add(event.target_agent_id)
        elif isinstance(event, CCEvent):
            counters.cc[event.source_agent_id] += 1

    damage_sources_by_target: dict[int, set[int]] = {}
    for de in damage_events:
        damage_sources_by_target.setdefault(de.target_agent_id, set()).add(de.source_agent_id)
    for death in death_events:
        contributors = damage_sources_by_target.get(death.source_agent_id, set())
        for src in contributors:
            counters.kill_participation[src] += 1

    for de in down_events:
        if de.downtime_ms > 0:
            counters.downtime[de.source_agent_id] += de.downtime_ms

    return counters


def _compute_presence(
    events: list[Event],
    identity_map: dict[int, AgentIdentity],
    duration_s: float,
) -> dict[int, float]:
    """Compute per-agent presence percentage based on 5-second buckets."""
    total_duration_ms = int(duration_s * 1000)
    bucket_count = max(1, (total_duration_ms // 5000) + (1 if total_duration_ms % 5000 else 0))
    active_buckets_by_agent: dict[int, set[int]] = {}
    for event in events:
        bucket = event.time_ms // 5000
        source_id = event.source_agent_id
        target_id = getattr(event, "target_agent_id", None)
        for agent_id in (source_id, target_id):
            if agent_id is not None and agent_id in identity_map:
                active_buckets_by_agent.setdefault(agent_id, set()).add(bucket)
    return {
        aid: min(100.0, (len(buckets) / bucket_count) * 100.0)
        for aid, buckets in active_buckets_by_agent.items()
    }


def _detect_agent_roles(
    agent_id: int,
    identity: AgentIdentity,
    damage_by_id: dict[int, PlayerDamageRow],
    heal_lookup: dict[int, PlayerHealRow],
    strips_counter: Counter[int],
    cleanses_counter: Counter[int],
    cc_counter: Counter[int],
) -> list[str]:
    """Detect combat roles for a single agent."""
    prof_str = identity.profession
    if prof_str.startswith("PROF("):
        try:
            prof_int = int(prof_str[5:-1])
        except ValueError:
            prof_int = 0
    else:
        prof_int = 0
    elite_str = identity.elite_spec
    if elite_str == "BASE":
        elite_int = 0
    elif elite_str.startswith("ELITE("):
        try:
            elite_int = int(elite_str[6:-1])
        except ValueError:
            elite_int = 0
    else:
        try:
            elite_int = EliteSpec[elite_str.upper()].value
        except KeyError:
            elite_int = 0

    hr = heal_lookup.get(agent_id)
    dr = damage_by_id.get(agent_id)
    primary_role, _tags = detect_role_lite(
        total_damage=dr.total_damage if dr else 0,
        total_healing=hr.total_healing if hr else 0,
        total_buff_removal=strips_counter.get(agent_id, 0),
        profession_int=prof_int,
        elite_spec_int=elite_int,
    )
    roles: list[str] = []
    if primary_role in _DETECTED_ROLE_LABELS:
        roles.append(_DETECTED_ROLE_LABELS[primary_role])
    if cleanses_counter.get(agent_id, 0) > 10:
        roles.append("Cleanser")
    if cc_counter.get(agent_id, 0) > 3:
        roles.append("CC")
    if not roles:
        roles.append("DPS")
    return roles


def aggregate_combat_readout(
    events: list[Event],
    *,
    skill_id_to_name_map: Mapping[int, str | None] | None = None,
    agent_id_to_identity_map: dict[int, AgentIdentity] | None = None,
    duration_s: float = 0.0,
    fight_id: str = "",
    dps_split_getter: DpsSplitGetter | None = None,
    barrier_portion_getter_heal: HealBarrierGetter | None = None,
    buff_removal_events: Iterable[BuffRemovalEvent] | None = None,
    boon_uptimes_by_account: dict[str, dict[str, float]] | None = None,
    dist_to_commander_by_account: dict[str, float] | None = None,
) -> FightReadoutOut:
    (
        damage_events,
        healing_events,
        boon_apply_events,
        cc_events,
        death_events,
        dodge_events,
        block_events,
        interrupt_events,
        stun_break_events,
        down_events,
    ) = _split_combat_readout_events(events)
    _identity_name_map: dict[int, str | None] | None = (
        {aid: ident.name for aid, ident in (agent_id_to_identity_map or {}).items()}
        if agent_id_to_identity_map is not None
        else None
    )
    damage_rows: list[PlayerDamageRow] = PlayerDamageAggregator().aggregate(
        damage_events,
        duration_s,
        name_map=_identity_name_map,
        dps_split_getter=dps_split_getter,
    )
    heal_rows: list[PlayerHealRow] = PlayerHealAggregator().aggregate(
        healing_events,
        duration_s,
        name_map=_identity_name_map,
        barrier_portion_getter=barrier_portion_getter_heal,
        stun_break_events=stun_break_events,
    )
    boons_rows: list[PlayerBoonsRow] = PlayerBoonsAggregator().aggregate(
        boon_apply_events,
        duration_s,
        name_map=cast(dict[int, str | None], skill_id_to_name_map),
        buff_removal_events=buff_removal_events if buff_removal_events is not None else (),
    )
    defense_rows: list[PlayerDefenseRow] = PlayerDefenseAggregator().aggregate(
        damage_events,
        cc_events,
        death_events,
        dodge_events=dodge_events,
        block_events=block_events,
        interrupt_events=interrupt_events,
        barrier_portion_getter=None,
        name_map=_identity_name_map,
    )

    counters = _compute_combat_counters(events, damage_events, death_events, down_events)

    damage_by_id: dict[int, PlayerDamageRow] = {r.source_agent_id: r for r in damage_rows}
    heal_by_id: dict[int, PlayerHealRow] = {r.source_agent_id: r for r in heal_rows}
    boons_by_id: dict[int, PlayerBoonsRow] = {r.agent_id: r for r in boons_rows}
    defense_by_id: dict[int, PlayerDefenseRow] = {r.agent_id: r for r in defense_rows}

    identity_map = agent_id_to_identity_map or {}
    presence_by_agent = _compute_presence(events, identity_map, duration_s)

    down_contribution_rows: list[DownContributionRow] = DownContributionAggregator().aggregate(
        damage_events,
        down_events,
        death_events,
        duration_s,
    )
    down_contrib_by_id: dict[int, tuple[float, int]] = {
        r.source_agent_id: (r.down_contribution_dps, r.kills)
        for r in down_contribution_rows
    }

    heal_lookup: dict[int, PlayerHealRow] = {r.source_agent_id: r for r in heal_rows}
    roles_by_agent: dict[int, list[str]] = {
        agent_id: _detect_agent_roles(
            agent_id,
            identity_map[agent_id],
            damage_by_id,
            heal_lookup,
            counters.strips,
            counters.cleanses,
            counters.cc,
        )
        for agent_id in identity_map
    }

    # identity_map reused below — no reassignment needed
    valid_agent_ids = (
        damage_by_id.keys() | heal_by_id.keys() | boons_by_id.keys() | defense_by_id.keys()
    ) & identity_map.keys()

    players: list[PlayerReadoutOut] = [
        _build_player_readout(
            agent_id,
            identity_map[agent_id],
            damage_by_id.get(agent_id),
            heal_by_id.get(agent_id),
            boons_by_id.get(agent_id),
            defense_by_id.get(agent_id),
            cleanses=counters.cleanses.get(agent_id, 0),
            strips=counters.strips.get(agent_id, 0),
            cc_applied=counters.cc.get(agent_id, 0),
            cleave_targets=len(counters.cleave_targets.get(agent_id, set())),
            kill_participation=counters.kill_participation.get(agent_id, 0),
            down_contrib=down_contrib_by_id.get(agent_id),
            time_downed_ms=counters.downtime.get(agent_id, 0),
            roles=roles_by_agent.get(agent_id, []),
            boon_uptimes=(
                boon_uptimes_by_account.get(identity_map[agent_id].account_name)
                if boon_uptimes_by_account and identity_map[agent_id].account_name
                else None
            ),
            presence_pct=presence_by_agent.get(agent_id),
            dist_to_commander=(
                dist_to_commander_by_account.get(identity_map[agent_id].account_name)
                if dist_to_commander_by_account and identity_map[agent_id].account_name
                else None
            ),
        )
        for agent_id in sorted(valid_agent_ids)
    ]

    return FightReadoutOut(
        fight_id=fight_id,
        duration_s=duration_s,
        players=players,
    )


def _downsample_positions(
    events: list[PositionEvent],
) -> tuple[list[PositionSampleOut], list[list[float]]]:
    evts_sorted = sorted(events, key=lambda e: e.time_ms)
    bucketed: dict[int, PositionEvent] = {}
    for e in evts_sorted:
        bucketed[e.time_ms // 500] = e
    selected = sorted(bucketed.values(), key=lambda e: e.time_ms)

    if len(selected) > 2000:
        selected = [selected[(len(selected) * i) // 2000] for i in range(2000)]

    samples = [
        PositionSampleOut(x=e.x, y=e.y, z=0.0)
        for e in selected
    ]
    return samples, [[e.time_ms, e.x, e.y] for e in selected]


def _collect_position_samples(
    events: Iterable[Event],
    agent_id_to_identity_map: dict[int, AgentIdentity],
) -> tuple[
    dict[int, list[PositionEvent]],  # raw_by_agent
    dict[str, list[list[float]]],    # player_samples
    dict[str, list[PositionSampleOut]],  # samples_by_account
]:
    """Collect and downsample position events per account."""
    raw_by_agent: dict[int, list[PositionEvent]] = {}
    for event in events:
        if not isinstance(event, PositionEvent):
            continue
        agent_id = event.source_agent_id
        if agent_id in agent_id_to_identity_map:
            raw_by_agent.setdefault(agent_id, []).append(event)

    player_samples: dict[str, list[list[float]]] = {}
    samples_by_account: dict[str, list[PositionSampleOut]] = {}

    for agent_id, evts in raw_by_agent.items():
        identity = agent_id_to_identity_map[agent_id]
        account = identity.account_name
        if not account:
            continue
        samples, samples_for_analysis = _downsample_positions(evts)
        if not samples:
            continue
        samples_by_account[account] = samples
        player_samples[account] = samples_for_analysis

    return raw_by_agent, player_samples, samples_by_account


def _compute_commander_distances(
    player_samples: dict[str, list[list[float]]],
    agent_id_to_identity_map: dict[int, AgentIdentity],
) -> dict[str, float]:
    """Compute distance to commander for each account."""
    commander_account: str | None = None
    commander_samples: list[list[float]] = []
    for _agent_id, identity in agent_id_to_identity_map.items():
        if identity.is_commander and identity.account_name:
            commander_account = identity.account_name
            commander_samples = player_samples.get(commander_account, [])
            break

    dist_to_commander_by_account: dict[str, float] = {}
    if not commander_account or not commander_samples:
        return dist_to_commander_by_account

    cmd_pos_by_time: dict[int, tuple[float, float]] = {}
    for sample in commander_samples:
        t_ms = int(sample[0])
        cmd_pos_by_time[t_ms] = (sample[1], sample[2])

    for account, samples in player_samples.items():
        if account == commander_account:
            dist_to_commander_by_account[account] = 0.0
            continue
        total_dist = 0.0
        matched = 0
        for sample in samples:
            t_ms = int(sample[0])
            cmd_pos = cmd_pos_by_time.get(t_ms)
            if cmd_pos is not None:
                dx = sample[1] - cmd_pos[0]
                dy = sample[2] - cmd_pos[1]
                total_dist += (dx * dx + dy * dy) ** 0.5
                matched += 1
        if matched > 0:
            dist_to_commander_by_account[account] = total_dist / matched

    return dist_to_commander_by_account


def _build_position_results(
    raw_by_agent: dict[int, list[PositionEvent]],
    agent_id_to_identity_map: dict[int, AgentIdentity],
    metrics: dict[str, dict[str, float]],
    samples_by_account: dict[str, list[PositionSampleOut]],
    dist_to_commander_by_account: dict[str, float],
) -> list[PlayerPositionOut]:
    """Build the final PlayerPositionOut list from processed data."""
    result: list[PlayerPositionOut] = []
    for agent_id in sorted(
        raw_by_agent,
        key=lambda aid: agent_id_to_identity_map[aid].account_name or "",
    ):
        identity = agent_id_to_identity_map[agent_id]
        account = identity.account_name
        if not account:
            continue
        row_metrics = metrics.get(account, {})
        result.append(
            PlayerPositionOut(
                account_name=account,
                name=identity.name,
                profession=identity.profession,
                elite_spec=identity.elite_spec,
                stack_dist=row_metrics.get("stack_dist"),
                dist_to_com=row_metrics.get("dist_to_com"),
                dist_to_commander=dist_to_commander_by_account.get(account),
                samples=samples_by_account.get(account, []),
            ),
        )
    return result


def aggregate_player_positions(
    events: Iterable[Event],
    agent_id_to_identity_map: dict[int, AgentIdentity],
) -> list[PlayerPositionOut]:
    if not agent_id_to_identity_map:
        return []

    raw_by_agent, player_samples, samples_by_account = _collect_position_samples(
        events, agent_id_to_identity_map,
    )
    if not player_samples or not samples_by_account or not raw_by_agent:
        return []

    metrics = compute_position_metrics(player_samples)
    dist_to_commander_by_account = _compute_commander_distances(
        player_samples, agent_id_to_identity_map,
    )

    return _build_position_results(
        raw_by_agent,
        agent_id_to_identity_map,
        metrics,
        samples_by_account,
        dist_to_commander_by_account,
    )


__all__ = [
    "aggregate_combat_readout",
    "aggregate_player_positions",
]
