"""Canonical aggregation glue for apps/api.

The shared API-to-library aggregation-layer glue that 3 endpoints
on ``/fights/{id}/*`` (events, squads, skills) all use. Wraps the
library-side aggregators (the ``Target{Dps,Healing,BuffRemoval}Agg``
classes + the ``SquadRollupAggregator`` + the ``SkillUsageAggregator``
classes from the ``gw2_analytics`` library) + the per-target trio
dispatch table that picks the right aggregator + output-row-type
for each ``Event`` subclass.

Provenance
----------

Extracted in PR 2 sub-commit 2 of the A2 god-module refactor
(plan 021):

- PR 1 shipped the cache primitive to ``blob_cache.py``.
- PR 2 sub-commit 1 shipped the DB lookup + blob-cached decompress
  ``_load_fight_events`` to ``blob_loader.py`` + the 3 dict-builder
  ORM helpers to ``mappers.py``.
- PR 2 sub-commit 2 (this commit) factors the aggregation glue:
  the per-target trio helper ``_aggregate_per_target_rollup`` +
  the 2 dispatcher wrappers ``aggregate_squad_rollup`` +
  ``aggregate_skill_usage``.

The aggregation glue here is the API surface over the
``libs/gw2_analytics`` library; the actual rollup logic stays in
the library (no business logic moved here).

Public surface
==============

- :func:`_aggregate_per_target_rollup` -- the per-target trio helper
  (DamageEvent -> :class:`TargetDpsAggregator`; HealingEvent ->
  :class:`TargetHealingAggregator`; BuffRemovalEvent ->
  :class:`TargetBuffRemovalAggregator`; unknown event_cls ->
  ``ValueError``).
- :func:`aggregate_squad_rollup` -- the per-subgroup rollup
  dispatcher wrapping :class:`SquadRollupAggregator`.
- :func:`aggregate_skill_usage` -- the per-skill rollup dispatcher
  wrapping :class:`SkillUsageAggregator`.
- :func:`aggregate_combat_readout` -- the unified Combat readout
  dispatcher wrapping the 4 per-player aggregators + the
  Phase 6 v2 getter plumbing (see ``Getter hooks``
  section below).

Test monkeypatch contract (READ BEFORE PATCHING)
================================================

The aggregation helpers resolve the library-side aggregator classes
via THIS module's namespace (NOT via
``gw2analytics_api.routes.fights.__init__``'s). Tests MUST patch
``gw2analytics_api.routes.fights.aggregators.TargetDpsAggregator``
(or whichever class) directly when overriding the aggregator's
behaviour in isolation; patching via the production namespace won't
reach the call site. Mirrors the PR 1 contract established on
``routes.fights.blob_cache.get_events``.

Getter hooks (Phase 3 / Wave 6, live since v0.12.1)
===================================================

The 3 optional parameters on :func:`aggregate_combat_readout`
plumb the Phase 6 v2 parser-side getters through to the per-player
aggregators:

- ``dps_split_getter``: ``Callable[[DamageEvent], tuple[int, int]] | None``
  fed to :meth:`PlayerDamageAggregator.aggregate`. When ``None``
  (legacy path), the aggregator skips the split call and
  ``dps_power=dps_condi=0.0``.
- ``barrier_portion_getter``: ``Callable[[HealingEvent], int] | None``
  fed to :meth:`PlayerHealAggregator.aggregate`. When ``None``,
  the aggregator skips the barrier call. The DAMAGE-side
  ``barrier_portion_getter`` for :class:`PlayerDefenseAggregator`
  is hardcoded to ``None`` (the parser doesn't yet carry
  per-damage barrier).
- ``buff_removal_events``: ``Iterable[BuffRemovalEvent] | None``
  fed to :meth:`PlayerBoonsAggregator.aggregate`. When ``None``,
  ``strips_received_in`` defaults to 0.

Since v0.12.1, the production path always passes real getters via
``make_dps_split_getter`` / ``make_barrier_portion_getter``;
``None`` fallback is for legacy stream compatibility only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Final, cast

from gw2_analytics.condi_power_split import KNOWN_CONDI_NAMES
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
from gw2_analytics.down_contribution import (
    DownContributionAggregator,
    DownContributionRow,
)
from gw2_analytics.position_analysis import compute_position_metrics
from gw2_analytics.skill_usage import SkillUsageAggregator, SkillUsageRow
from gw2_analytics.squad_rollup import SquadRollupAggregator, SquadRollupRow
from gw2_analytics.target_buff_removal import (
    TargetBuffRemovalAggregator,
    TargetBuffRemovalRow,
)
from gw2_analytics.target_dps import TargetDpsAggregator, TargetDpsRow
from gw2_analytics.target_healing import TargetHealingAggregator, TargetHealingRow
from gw2_core import (
    BlockEvent,
    BoonApplyEvent,
    BuffRemovalEvent,
    CCEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    DownEvent,
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


def _split_three_event_streams(
    events: Iterable[Event],
) -> tuple[list[DamageEvent], list[HealingEvent], list[BuffRemovalEvent]]:
    """Split a heterogeneous event stream into the 3 core combat streams.

    Returns typed ``(damage_events, healing_events, buff_removal_events)``
    lists in a single O(N) pass. Unknown event subclasses are silently
    dropped. This helper is shared by :func:`aggregate_squad_rollup` and
    :func:`aggregate_skill_usage` so they avoid 3 repeated ``isinstance``
    list comprehensions over the same input.
    """
    damage_events: list[DamageEvent] = []
    healing_events: list[HealingEvent] = []
    buff_removal_events: list[BuffRemovalEvent] = []

    # Local bindings avoid repeated attribute lookups in the hot loop.
    append_damage = damage_events.append
    append_healing = healing_events.append
    append_buff_removal = buff_removal_events.append

    for event in events:
        if isinstance(event, DamageEvent):
            append_damage(event)
        elif isinstance(event, HealingEvent):
            append_healing(event)
        elif isinstance(event, BuffRemovalEvent):
            append_buff_removal(event)

    return damage_events, healing_events, buff_removal_events


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
    """Split a heterogeneous event stream into typed Combat-readout streams.

    Returns 10 typed event lists in the canonical order consumed by
    :func:`aggregate_combat_readout`. Unknown event subclasses are
    silently dropped.

    This is a single O(N) pass over ``events``; it replaces the 9
    repeated ``isinstance`` list comprehensions that previously lived
    in the route handler.
    """
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

    # Local bindings avoid repeated attribute lookups in the hot loop.
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


def _aggregate_per_target_rollup(
    events: list[Event],
    agent_id_to_name_map: dict[int, str | None],
    duration_s: float,
    event_cls: type[Event],
) -> Sequence[TargetDpsRow | TargetHealingRow | TargetBuffRemovalRow]:
    """Dispatch to the right per-target aggregator for ``event_cls``.

    The caller is responsible for filtering ``events`` to the
    matching event type; this helper only maps ``event_cls`` to
    the corresponding aggregator instance and forwards the
    pre-filtered stream. It remains the canonical dispatch table
    for the per-target trio and is exercised directly by the
    hermetic tests in ``apps/api/tests/routes/test_fights_per_target_helper.py``.
    """
    # Reviewer NICE-to-HAVE: defensive runtime assert enforcing the
    # "caller pre-filters events to event_cls" contract. Surfaces contract
    # violations at the helper boundary rather than letting the downstream
    # aggregator silently miscount non-matching event subclasses.
    assert all(isinstance(e, event_cls) for e in events), (  # noqa: S101
        f"_aggregate_per_target_rollup: caller must pre-filter events to "
        f"{event_cls.__name__}; got mixed event stream"
    )
    if event_cls is DamageEvent:
        return TargetDpsAggregator().aggregate(
            cast(Iterable[DamageEvent], events),
            duration_s,
            name_map=agent_id_to_name_map,
        )
    if event_cls is HealingEvent:
        return TargetHealingAggregator().aggregate(
            cast(Iterable[HealingEvent], events),
            duration_s,
            name_map=agent_id_to_name_map,
        )
    if event_cls is BuffRemovalEvent:
        return TargetBuffRemovalAggregator().aggregate(
            cast(Iterable[BuffRemovalEvent], events),
            duration_s,
            name_map=agent_id_to_name_map,
        )
    raise ValueError(
        f"_aggregate_per_target_rollup: unknown event_cls {event_cls!r}; "
        f"expected DamageEvent | HealingEvent | BuffRemovalEvent"
    )


def aggregate_squad_rollup(
    events: list[Event],
    agent_id_to_subgroup_map: dict[int, str],
    duration_s: float,
) -> list[SquadRollupRow]:
    """Aggregate per-subgroup rollup using :class:`SquadRollupAggregator`.

    Wraps the library-side :class:`SquadRollupAggregator` with the
    3-event-type fanout (damage, healing, buff-removal streams).
    Skips the per-subgroup fanout's 3 isinstance lists at the call
    site so the route handler can stay thin.

    The aggregator returns :class:`SquadRollupRow` instances
    (one per non-empty subgroup). The route handler annotates the
    return as ``list[SquadRollupRowOut]`` after filtering + mapping
    to the wire schema.
    """
    damage_events, healing_events, buff_removal_events = _split_three_event_streams(events)
    return SquadRollupAggregator().aggregate(
        damage_events,
        healing_events,
        buff_removal_events,
        agent_id_to_subgroup_map,
        duration_s,
    )


def aggregate_skill_usage(
    events: list[Event],
    skill_id_to_name_map: dict[int, str],
) -> list[SkillUsageRow]:
    """Aggregate per-skill rollup using :class:`SkillUsageAggregator`.

    Wraps the library-side :class:`SkillUsageAggregator` with the
    3-event-type fanout (damage + healing + buff-removal streams).
    No ``duration_s`` is passed (the skill-usage aggregator doesn't
    compute per-second rates; per-second rates are derived from the
    fight length by the v0.7.0 wire contract for the ``SkillUsageRow``
    shape -- only the ``total_damage/healing/buff_removal`` counts
    surface; per-second rates are NOT in the wire schema).
    """
    damage_events, healing_events, buff_removal_events = _split_three_event_streams(events)
    return SkillUsageAggregator().aggregate(
        damage_events,
        healing_events,
        buff_removal_events,
        skill_id_to_name_map,
    )


#: Module-level zero-default sentinels for the primitive-only aspect
#: rows used by :func:`_build_player_readout`. These models contain only
#: immutable scalar fields, so sharing a single instance is safe.
#: ``PlayerBoonsRow`` is intentionally excluded because its
#: ``other_boons_out`` field is a mutable dict.
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
    down_contrib: tuple[float, int] | None = None,
    time_downed_ms: int = 0,
    boon_uptimes: dict[str, float] | None = None,
    presence_pct: float | None = None,
    roles: list[str] | None = None,
) -> PlayerReadoutOut:
    """Build a single :class:`PlayerReadoutOut` from aspect rows + identity.

    Missing aspect rows are replaced with zero-default instances so a
    player present in only one aspect still gets a complete envelope.
    Primitive-only rows reuse module-level sentinels; ``PlayerBoonsRow``
    is always instantiated fresh because its ``other_boons_out`` dict
    is mutable and must not be shared.
    """
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
            down_contribution_dps=down_contrib[0] if down_contrib else 0.0,
            kills=down_contrib[1] if down_contrib else 0,
        ),
        heal=PlayerReadoutHealOut(
            heal_total=h_row.total_healing,
            hps=h_row.hps,
            barrier_total=h_row.barrier_total,
            barrier_ps=h_row.barrier_ps,
            cleanses=cleanses,
            # Tour 6 v0.10.24 close-out: stun_breaks populated
            # from the per-player row (actor-side attribution).
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
            # Plan 173: boon uptimes from OrmFightPlayerSummary.
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
            # Plan 173 Phase F: outgoing boon generation totals.
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
            # Plan 173 Phase E: presence percentage from event-window buckets.
            presence_pct=presence_pct,
        ),
    )


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
) -> FightReadoutOut:
    """Aggregate the Combat readout (4-table layout from design doc §3-6) for one fight.

    Wraps the 4 per-player
    aggregators (PlayerDamageAggregator / PlayerHealAggregator /
    PlayerBoonsAggregator / PlayerDefenseAggregator) + the
    per-player attribution map ``agent_id_to_name_map`` into the
    unified :class:`FightReadoutOut` envelope (per design doc
    §5.1).

    The dispatcher accepts the raw heterogeneous
    ``Iterable[Event]`` stream and splits it internally via
    :func:`_split_combat_readout_events`. This keeps the route
    handler thin and avoids duplicating the 9 ``isinstance``
    list comprehensions at the call site.

    Why a FightReadoutOut return (Option (a) per Wave 5 think):
    the wire-shape Pydantic IS the domain model after Wave 2
    The schema is ``ConfigDict(from_attributes=True)`` so ORM-style
    hydration works; defaults to ``0``/empty so a 0-player fight
    yields an empty ``players: []`` list cleanly.

    The 4 per-player roll-ups are independent (no cross-stream
    invariant); each aggregator runs in its own ``.aggregate(...)``
    call. Sort direction follows the per-player aggregator's
    primary sort key (Damage DESC + Heal DESC + Boons DESC +
    Defense ASC-most-targeted-first).

    Getter semantics (Phase 3 close-out, live since v0.12.1):

    - ``dps_split_getter``: forwarded to
      :meth:`PlayerDamageAggregator.aggregate`. When ``None``,
      the aggregator skips the split call.
    - ``barrier_portion_getter_heal``: forwarded to
      :meth:`PlayerHealAggregator.aggregate`. When ``None``,
      the aggregator skips the barrier call. Note: the
      DAMAGE-side barrier has its own parameter that defaults
      to ``None`` (parser doesn't yet carry per-damage barrier).
    - ``buff_removal_events``: forwarded to
      :meth:`PlayerBoonsAggregator.aggregate`. When ``None``,
      ``strips_received_in`` defaults to 0.
    """
    # Reviewer #2 fix: hoist the identity->name dict allocation to a
    # SINGLE intermediate so the 3 per-player aggregators share ONE
    # computed dict instead of rebuilding {aid: ident.name for ...}
    # at each call site. Saves one allocation per aggregator call
    # (3 -> 1) and eliminates the asymmetric dispatch pattern the
    # previous review flagged. The None fallback preserves the
    # legacy ``agent_id_to_name_map=None`` call site contract.
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
        # Tour 6 v0.10.24: the heal aggregator now keys on the
        # identity (name) map; fall back to the name-only map (the
        # legacy ``agent_id_to_name_map``) when callers haven't
        # adopted the identity-map contract yet.
        name_map=_identity_name_map,
        dps_split_getter=dps_split_getter,
    )
    heal_rows: list[PlayerHealRow] = PlayerHealAggregator().aggregate(
        healing_events,
        duration_s,
        # Tour 6 v0.10.24: heal-side chain to the identity-map's
        # ``name`` attribute (the same name only fallback as damage).
        name_map=_identity_name_map,
        barrier_portion_getter=barrier_portion_getter_heal,
        stun_break_events=stun_break_events,
    )
    boons_rows: list[PlayerBoonsRow] = PlayerBoonsAggregator().aggregate(
        boon_apply_events,
        duration_s,
        # Library-side PlayerBoonsAggregator.aggregate expects dict[int, str | None]
        # (invariant). aggregate_combat_readout accepts the covariant Mapping[int, str | None]
        # to let callers pass dict[int, str] (a Mapping subtype); we cast at the
        # aggregator boundary to honor the library's invariant contract.
        name_map=cast(dict[int, str | None], skill_id_to_name_map),
        buff_removal_events=buff_removal_events if buff_removal_events is not None else (),
    )
    # Defense consumes 6 streams (damage / CC / death / dodge / block
    # / interrupt). The barrier_portion_getter is None by default
    # (canonical v0.10.23 path; the parser doesn't yet emit the
    # per-damage ``barrier`` side table).
    defense_rows: list[PlayerDefenseRow] = PlayerDefenseAggregator().aggregate(
        damage_events,
        cc_events,
        death_events,
        dodge_events=dodge_events,
        block_events=block_events,
        interrupt_events=interrupt_events,
        barrier_portion_getter=None,
        # Tour 6 v0.10.24: defensive-side chain to the identity-map's
        # ``name`` attribute (the same name-only fallback as damage).
        name_map=_identity_name_map,
    )

    # v0.11.4: classify BuffRemovalEvent by buff_id using is_condition()
    # from gw2_core._buff_ids.  Condition cleanses (buff_id is a
    # condition like Bleeding=736) are counted per source_agent_id
    # and passed to _build_player_readout as the cleanses column.
    # Boon strips (buff_id is a boon like Might=740) remain as
    # generic BuffRemovalEvent and are NOT reclassified here.
    cleanses_counter: Counter[int] = Counter()
    strips_counter: Counter[int] = Counter()
    for event in events:
        if isinstance(event, BuffRemovalEvent):
            if is_condition(event.buff_id):
                cleanses_counter[event.source_agent_id] += 1
            else:
                # Boon strip (boon removal, not condition cleanse).
                strips_counter[event.source_agent_id] += 1

    # v0.14.4: count CC events per source_agent_id.
    cc_counter: Counter[int] = Counter()
    for event in events:
        if isinstance(event, CCEvent):
            cc_counter[event.source_agent_id] += 1

    # v0.12.0: sum DownEvent.downtime_ms per source_agent_id.
    # The parser currently emits downtime_ms=0 (down-state lifecycle
    # tracking is Phase 6 v2 parser work); the aggregation loop is
    # wired now so the column picks up real values automatically
    # when the parser computes per-event downtime.
    downtime_counter: Counter[int] = Counter()
    for de in down_events:
        if de.downtime_ms > 0:
            downtime_counter[de.source_agent_id] += de.downtime_ms

    # Build the per-agent_id -> per-aspect-row map. The 4
    # per-player aggregators all key on agent_id, so a single
    # dict comprehension per aspect merges cleanly. Agents that
    # appear in only some aspects get zero-defaults on the
    # missing aspects (the schema's ``Field(default=0)`` and
    # ``Field(default_factory=dict)`` carry the empty-state).
    damage_by_id: dict[int, PlayerDamageRow] = {r.source_agent_id: r for r in damage_rows}
    heal_by_id: dict[int, PlayerHealRow] = {r.source_agent_id: r for r in heal_rows}
    boons_by_id: dict[int, PlayerBoonsRow] = {r.agent_id: r for r in boons_rows}
    defense_by_id: dict[int, PlayerDefenseRow] = {r.agent_id: r for r in defense_rows}

    # Plan 173 Phase E: per-player presence percentage via event-window
    # buckets (5 s). For each player agent, count the number of buckets
    # in which they appear as source or target of any event, then
    # compute presence_pct = (active_buckets / total_buckets) * 100.
    identity_map = agent_id_to_identity_map or {}
    total_duration_ms = int(duration_s * 1000)
    bucket_count = max(1, (total_duration_ms // 5000) + (1 if total_duration_ms % 5000 else 0))
    active_buckets_by_agent: dict[int, set[int]] = {}
    for event in events:
        bucket = event.time_ms // 5000
        # Some event types may not carry target_agent_id (e.g. statechange
        # events without a target). Use getattr defensively.
        source_id = event.source_agent_id
        target_id = getattr(event, "target_agent_id", None)
        for agent_id in (source_id, target_id):
            if agent_id is not None and agent_id in identity_map:
                active_buckets_by_agent.setdefault(agent_id, set()).add(bucket)
    presence_by_agent: dict[int, float] = {
        aid: min(100.0, (len(buckets) / bucket_count) * 100.0)
        for aid, buckets in active_buckets_by_agent.items()
    }

    # v0.14.4: down-contribution DPS + kill attribution via the
    # library-side DownContributionAggregator (chronological processing
    # of DownEvent + DeathEvent + DamageEvent to track damage dealt
    # to downed targets). Wired since the aggregator already existed
    # in libs/gw2_analytics but was never called from the API layer.
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

    # v0.14.4: basic role detection — DPS / Heal / Support based on
    # heal share relative to the squad. If a player contributes >30%
    # of the squad's total healing, they're flagged as "Heal".
    # Boon-focused players (>2 boons/s out) are flagged as "Support".
    # Everyone else is "DPS". Iterates ALL player agents from the
    # identity map so every player gets a role.
    total_squad_healing = sum(r.total_healing for r in heal_rows)
    boons_lookup: dict[int, PlayerBoonsRow] = {r.agent_id: r for r in boons_rows}
    heal_lookup: dict[int, PlayerHealRow] = {r.source_agent_id: r for r in heal_rows}
    roles_by_agent: dict[int, list[str]] = {}
    for agent_id in identity_map:
        roles: list[str] = []
        hr = heal_lookup.get(agent_id)
        if hr and total_squad_healing > 0 and (hr.total_healing / total_squad_healing) > 0.30:
            roles.append("Heal")
        br = boons_lookup.get(agent_id)
        if br and br.boons_out_rate > 2.0:
            roles.append("Support")
        if not roles:
            roles.append("DPS")
        roles_by_agent[agent_id] = roles

    # Single pass to build the per-agent PlayerReadoutOut envelope.
    # The 5 shared identity columns (per design doc §2) hydrate
    # from the ``AgentIdentity`` map (Tour 6 v0.10.24 close-out of
    # the Wave 5 NIT placeholders). ``agent_id`` is the
    # dispatcher-set value (the key of the per-aspect aggregator
    # outputs); the remaining 5 columns + ``account_name`` come
    # from the OrmFightAgent-hydrated identity slice. ``roles``
    # stays at ``[]`` (role classifier is Blocker C deferred).
    identity_map = agent_id_to_identity_map or {}
    # Intersect the union of per-aspect rows with the identity
    # map keys so NPC targets (target_agent_id in defense row
    # set without an is_player=True agent row in the DB) are
    # silently dropped from the envelope. This keeps the wire
    # shape strictly player-only.
    # Use dict key views to avoid temporary set allocations.
    valid_agent_ids = (
        damage_by_id.keys() | heal_by_id.keys() | boons_by_id.keys() | defense_by_id.keys()
    ) & identity_map.keys()

    # Tour 6 v0.10.24-pre follow-up wire-contract widening: the
    # truthy ``or ""`` collapse is GONE. ``PlayerReadoutOut.account_name``
    # is now ``str | None`` (the schema widening completed in lockstep
    # with this commit) so the wire payload PRESERVES the arcdps
    # ``None``-vs-empty-string distinction. The web/ Tier-2 consumers
    # (PlayersGrid, CrossAccountTimelineChart, PerPlayerTimelineChart)
    # handle the null path explicitly. The pre-follow-up lossy transition
    # (every None-or-"" collapsing to "") ended with this commit. See
    # CHANGELOG.md [0.10.24-pre] follow-up sub-bullet for the breakage
    # framing (additive: the field was always nullable in the DB; the
    # wire schema now mirrors the DB).
    players: list[PlayerReadoutOut] = [
        _build_player_readout(
            agent_id,
            identity_map[agent_id],
            damage_by_id.get(agent_id),
            heal_by_id.get(agent_id),
            boons_by_id.get(agent_id),
            defense_by_id.get(agent_id),
            cleanses=cleanses_counter.get(agent_id, 0),
            strips=strips_counter.get(agent_id, 0),
            cc_applied=cc_counter.get(agent_id, 0),
            down_contrib=down_contrib_by_id.get(agent_id),
            time_downed_ms=downtime_counter.get(agent_id, 0),
            roles=roles_by_agent.get(agent_id, []),
            boon_uptimes=(
                boon_uptimes_by_account.get(identity_map[agent_id].account_name)
                if boon_uptimes_by_account and identity_map[agent_id].account_name
                else None
            ),
            presence_pct=presence_by_agent.get(agent_id),
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
    """Downsample position events to 1 per 500 ms, capped at 2000.

    Returns ``(samples, position_analysis_input)`` where each entry
    is a ``[time_ms, x, y]`` list. Integer math is used for the cap
    to avoid floating-point index drift.
    """
    evts_sorted = sorted(events, key=lambda e: e.time_ms)
    bucketed: dict[int, PositionEvent] = {}
    for e in evts_sorted:
        bucketed[e.time_ms // 500] = e
    selected = sorted(bucketed.values(), key=lambda e: e.time_ms)

    if len(selected) > 2000:
        selected = [selected[(len(selected) * i) // 2000] for i in range(2000)]

    samples = [
        # PositionEvent currently carries only x/y; z is reserved for a
        # future elevation-aware parser extension. Returning 0.0 keeps the
        # wire shape stable and matches the existing frontend contract.
        # TODO(parser-pos-z): wire real elevation when PositionEvent gains z.
        PositionSampleOut(x=e.x, y=e.y, z=0.0)
        for e in selected
    ]
    return samples, [[e.time_ms, e.x, e.y] for e in selected]


def aggregate_player_positions(
    events: Iterable[Event],
    agent_id_to_identity_map: dict[int, AgentIdentity],
) -> list[PlayerPositionOut]:
    """Aggregate per-player position metrics + downsampled traces.

    Phase C heatmap foundation: filters ``PositionEvent`` from the
    heterogeneous event stream, downsamples to at most 1 sample per
    500 ms per player (capped at 2000 samples), computes
    ``stack_dist`` / ``dist_to_com`` via
    :func:`gw2_analytics.position_analysis.compute_position_metrics`,
    and returns one :class:`PlayerPositionOut` per player agent.

    NPC agents are silently dropped (they have no entry in the
    ``agent_id_to_identity_map``). Player agents without an
    ``account_name`` are also dropped because the position-analysis
    key is the canonical account name.
    """
    if not agent_id_to_identity_map:
        return []

    # Collect PositionEvents for player agents only.
    raw_by_agent: dict[int, list[PositionEvent]] = {}
    for event in events:
        if not isinstance(event, PositionEvent):
            continue
        agent_id = event.source_agent_id
        if agent_id in agent_id_to_identity_map:
            raw_by_agent.setdefault(agent_id, []).append(event)

    if not raw_by_agent:
        return []

    # Downsample + build per-account samples and position-analysis input.
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

    if not player_samples:
        return []

    metrics = compute_position_metrics(player_samples)

    # v0.14.4: find the commander player and compute per-player
    # average distance to the commander's position at matching
    # timestamps. The commander is the player agent with
    # is_commander=True in the identity map.
    commander_account: str | None = None
    commander_samples: list[list[float]] = []
    for agent_id, identity in agent_id_to_identity_map.items():
        if identity.is_commander and identity.account_name:
            commander_account = identity.account_name
            commander_samples = player_samples.get(commander_account, [])
            break

    dist_to_commander_by_account: dict[str, float] = {}
    if commander_account and commander_samples:
        # Build a time_ms -> position lookup for the commander.
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

    result: list[PlayerPositionOut] = []
    # Sort by account_name for deterministic, user-friendly ordering.
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


#: Arcdps build-date gate for condi/power split.  Builds >= this date
#: carry the condi portion of a damage hit in the raw cbtevent's
#: ``buff_dmg`` field.  Older builds encode condi implicitly via skill
#: name lookup.  Calibrated against plan 135.
_BUILD_DATE_GATE: Final[str] = "20240501"


def make_dps_split_getter(
    build_date: str,
    skill_name_getter: Callable[[int], str | None],
) -> DpsSplitGetter:
    """Create a per-event ``(condi, power)`` splitter for the given fight.

    For new builds (>= :data:`_BUILD_DATE_GATE`), extracts the condi
    portion from ``DamageEvent.buff_dmg``.  For old builds, uses the
    skill name lookup against :data:`KNOWN_CONDI_NAMES`.

    Returns a :class:`DpsSplitGetter` suitable for passing to
    :meth:`PlayerDamageAggregator.aggregate`.
    """
    is_new = build_date.isdigit() and int(build_date) >= int(_BUILD_DATE_GATE)
    # Per-call cache: skill_id -> name lookup.  None is a valid
    # cached value (unknown skill).
    cache: dict[int, str | None] = {}
    known = KNOWN_CONDI_NAMES

    if is_new:
        def _new_splitter(e: DamageEvent) -> tuple[int, int]:
            condi = min(e.damage, max(0, e.buff_dmg))
            return (condi, e.damage - condi)

        return _new_splitter

    def _old_splitter(e: DamageEvent) -> tuple[int, int]:
        sid = e.skill_id
        if sid not in cache:
            cache[sid] = skill_name_getter(sid)
        if cache[sid] in known:
            return (e.damage, 0)  # all condi
        return (0, e.damage)  # all power

    return _old_splitter


def make_barrier_portion_getter() -> HealBarrierGetter:
    """Create a per-event barrier getter for heal-class events.

    Extracts ``HealingEvent.barrier`` — the arcdps ``buff_dmg`` field
    on heal records, which encodes the barrier/shield portion.

    Returns a :class:`HealBarrierGetter` suitable for passing to
    :meth:`PlayerHealAggregator.aggregate`.
    """
    return lambda e: e.barrier


__all__ = [
    "_BUILD_DATE_GATE",
    "_aggregate_per_target_rollup",
    "aggregate_combat_readout",
    "aggregate_player_positions",
    "aggregate_skill_usage",
    "aggregate_squad_rollup",
    "make_barrier_portion_getter",
    "make_dps_split_getter",
]
