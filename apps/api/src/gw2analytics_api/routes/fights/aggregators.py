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
  Phase 6 v2 SCAFFOLD-getter plumbing (see ``SCAFFOLD hooks``
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

SCAFFOLD hooks (Phase 3 / Wave 6)
=================================

The 3 NEW optional parameters on
:func:`aggregate_combat_readout` plumb the Phase 6 v2 parser-side
side-table getters through to the per-player aggregators WITHOUT
mutating the wire shape:

- ``dps_split_getter``: ``Callable[[DamageEvent], tuple[int, int]] | None``
  fed to :meth:`PlayerDamageAggregator.aggregate`. When ``None``
  (the canonical v0.10.23 SCAFFOLD path), the per-player
  aggregator substitutes
  :func:`gw2_core.default_dps_split` -- the "everything is power"
  fallback that keeps the wire-shape ``dps_power=0.0 +
  dps_condi=dps`` for pre-Phase-6-v2 streams.
- ``barrier_portion_getter``: ``Callable[[HealingEvent], int] | None``
  fed to :meth:`PlayerHealAggregator.aggregate`. When ``None``, the
  per-player aggregator substitutes
  :func:`gw2_core.default_barrier_portion_from_healing`. Note: this
  is the HEAL-side barrier getter; the DAMAGE-side
  ``barrier_portion_getter`` for :class:`PlayerDefenseAggregator`
  is hardcoded to ``None`` in the v0.10.23 path (the parser
  doesn't yet carry per-damage barrier) and feeds
  :meth:`PlayerDefenseAggregator.aggregate` via the existing
  parameter.
- ``buff_removal_events``: ``Iterable[BuffRemovalEvent] | None``
  fed to :meth:`PlayerBoonsAggregator.aggregate`. When ``None``,
  no buff-removal events flow through; the row's
  ``strips_received_in`` column defaults to 0 (the SCAFFOLD path).

A future Phase 6 v2 PR constructs each getter from the parser-side
side table; the SCAFFOLD absorbs the swap via one constructor
change. Pre-Phase-6-v2 streams: all 3 SCAFFOLD params default to
``None`` and the per-player aggregators substitute their
SCAFFOLD defaults -- ZERO behavioural change for existing
fixtures.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

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
    Event,
    HealingEvent,
    InterruptEvent,
    StunBreakEvent,
)
from gw2analytics_api.routes.fights.mappers import AgentIdentity
from gw2analytics_api.schemas import (
    FightReadoutOut,
    PlayerReadoutBoonsOut,
    PlayerReadoutDamageOut,
    PlayerReadoutDefenseOut,
    PlayerReadoutHealOut,
    PlayerReadoutOut,
)


def _aggregate_per_target_rollup(
    events: list[Event],
    agent_id_to_name_map: dict[int, str | None],
    duration_s: float,
    event_cls: type[Event],
) -> list[TargetDpsRow | TargetHealingRow | TargetBuffRemovalRow]:
    """Compute one per-target roll-up branch (DPS / healing / buff-removal).

    Centralises the 3 sibling roll-up branches in
    :func:`get_fight_events` (the one structural change introduced
    by Phase 8 v0.8.0 + v0.8.3 + v0.10.2 hotfix #12). Each branch was
    3 lines: an ``isinstance`` filter, an aggregator call with
    ``(events, duration_s, name_map=...)``, and a schema-validation
    list comprehension. The helper picks the aggregator +
    output-row-type by ``event_cls`` so the route layer wraps
    schema validation in a thin comprehension with the right
    ``RowOut`` subclass.

    Mapping
    -------
    ``DamageEvent`` -> :class:`TargetDpsAggregator`
    ``HealingEvent`` -> :class:`TargetHealingAggregator`
    ``BuffRemovalEvent`` -> :class:`TargetBuffRemovalAggregator`

    Any other ``event_cls`` (e.g. a Phase 9 ``ConditionDamageEvent``)
    raises ``ValueError`` -- the dispatch table is explicitly
    closed-form so a future addition is a single-line edit here.

    Performance
    ----------
    The ``isinstance`` filter is one pass over ``events``.
    For a multi-million-event fight (rare but possible in WvW)
    the filter is still O(N) -- the cost is amortised across the
    3 calls because the same event is filtered 3 times. The
    aggregated shape (a few hundred rows) is small by comparison.
    """
    if event_cls is DamageEvent:
        aggregator: TargetDpsAggregator | TargetHealingAggregator | TargetBuffRemovalAggregator = (
            TargetDpsAggregator()
        )
    elif event_cls is HealingEvent:
        aggregator = TargetHealingAggregator()
    elif event_cls is BuffRemovalEvent:
        aggregator = TargetBuffRemovalAggregator()
    else:
        raise ValueError(
            f"_aggregate_per_target_rollup: unknown event_cls {event_cls!r}; "
            f"expected DamageEvent | HealingEvent | BuffRemovalEvent"
        )
    return cast(
        list[TargetDpsRow | TargetHealingRow | TargetBuffRemovalRow],
        aggregator.aggregate(
            [e for e in events if isinstance(e, event_cls)],  # type: ignore[misc]
            duration_s,
            name_map=agent_id_to_name_map,
        ),
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
    return SquadRollupAggregator().aggregate(
        [e for e in events if isinstance(e, DamageEvent)],
        [e for e in events if isinstance(e, HealingEvent)],
        [e for e in events if isinstance(e, BuffRemovalEvent)],
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
    return SkillUsageAggregator().aggregate(
        [e for e in events if isinstance(e, DamageEvent)],
        [e for e in events if isinstance(e, HealingEvent)],
        [e for e in events if isinstance(e, BuffRemovalEvent)],
        skill_id_to_name_map,
    )


def aggregate_combat_readout(
    damage_events: Iterable[DamageEvent],
    healing_events: Iterable[HealingEvent],
    boon_apply_events: Iterable[BoonApplyEvent],
    cc_events: Iterable[CCEvent],
    death_events: Iterable[DeathEvent],
    dodge_events: Iterable[DodgeEvent],
    block_events: Iterable[BlockEvent],
    interrupt_events: Iterable[InterruptEvent],
    stun_break_events: Iterable[StunBreakEvent] = (),
    skill_id_to_name_map: dict[int, str | None] | None = None,
    agent_id_to_identity_map: dict[int, AgentIdentity] | None = None,
    duration_s: float = 0.0,
    fight_id: str = "",
    dps_split_getter: DpsSplitGetter | None = None,
    barrier_portion_getter_heal: HealBarrierGetter | None = None,
    buff_removal_events: Iterable[BuffRemovalEvent] | None = None,
) -> FightReadoutOut:
    """Aggregate the Combat readout (4-table layout from design doc §3-6) for one fight.

    Wave 5 SCAFFOLD + Workstream D-extension bridge + Wave 6
    Phase 3 SCAFFOLD-getter plumbing. Wraps the 4 per-player
    aggregators (PlayerDamageAggregator / PlayerHealAggregator /
    PlayerBoonsAggregator / PlayerDefenseAggregator) + the
    per-player attribution map ``agent_id_to_name_map`` into the
    unified :class:`FightReadoutOut` envelope (per design doc
    §5.1).

    Why explicit pre-split streams (Option (b) per Wave 5 think):
    the route handler splits the heterogeneous ``Iterable[Event]``
    stream via isinstance at the call site; the dispatcher
    accepts the 8 typed streams (damage + healing + boon-apply +
    CC + death + dodge + block + interrupt) directly. The
    per-player aggregators each accept their input as a single
    typed iterable so the wire contract is uniform.

    Why a FightReadoutOut return (Option (a) per Wave 5 think):
    the wire-shape Pydantic IS the domain model after Wave 2
    SCAFFOLD shipped (the schema is
    ``ConfigDict(from_attributes=True)`` so ORM-style hydration
    works; the schema defaults to ``0``/empty so a 0-player
    fight yields an empty ``players: []`` list cleanly).

    The 4 per-player roll-ups are independent (no cross-stream
    invariant); each aggregator runs in its own ``.aggregate(...)``
    call. Sort direction follows the per-player aggregator's
    primary sort key (Damage DESC + Heal DESC + Boons DESC +
    Defense ASC-most-targeted-first).

    SCAFFOLD-getter semantics (Phase 3 close-out):

    - ``dps_split_getter``: forwarded to
      :meth:`PlayerDamageAggregator.aggregate`. When ``None``, the
      per-player aggregator substitutes
      :func:`gw2_core.default_dps_split` -- the wire-shape
      ``dps_power=0.0 + dps_condi=dps`` path.
    - ``barrier_portion_getter_heal``: forwarded to
      :meth:`PlayerHealAggregator.aggregate`. When ``None``, the
      per-player aggregator substitutes
      :func:`gw2_core.default_barrier_portion_from_healing` --
      the wire-shape ``barrier_total=0 + barrier_ps=0.0`` path.
      Note: the DAMAGE-side barrier (``PlayerDefenseAggregator``)
      has its own ``barrier_portion_getter`` parameter that
      defaults to ``None`` here (the parser doesn't yet carry
      per-damage barrier). A future Phase 6 v2 PR opens a
      corresponding ``barrier_portion_getter_damage`` parameter.
    - ``buff_removal_events``: forwarded to
      :meth:`PlayerBoonsAggregator.aggregate`. When ``None``, the
      per-player aggregator substitutes an empty iterable -- the
      wire-shape ``strips_received_in=0`` path. (Phase 6 v2 will
      materialise the parser-side :class:`BuffRemovalEvent`
      stream here.)
    """
    # Reviewer #2 fix: hoist the identity->name dict allocation to a
    # SINGLE intermediate so the 3 per-player aggregators share ONE
    # computed dict instead of rebuilding {aid: ident.name for ...}
    # at each call site. Saves one allocation per aggregator call
    # (3 -> 1) and eliminates the asymmetric dispatch pattern the
    # previous review flagged. The None fallback preserves the
    # legacy ``agent_id_to_name_map=None`` call site contract.
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
        # Phase 3 SCAFFOLD: forward the optional dps-split getter.
        # When ``None``, the per-player aggregator substitutes
        # :func:`gw2_core.default_dps_split` -- the canonical
        # "everything is power" wireshape.
        dps_split_getter=dps_split_getter,
    )
    heal_rows: list[PlayerHealRow] = PlayerHealAggregator().aggregate(
        healing_events,
        duration_s,
        # Tour 6 v0.10.24: heal-side chain to the identity-map's
        # ``name`` attribute (the same name only fallback as damage).
        name_map=_identity_name_map,
        # Phase 3 SCAFFOLD: forward the optional heal-side barrier
        # getter. When ``None``, the per-player aggregator
        # substitutes
        # :func:`gw2_core.default_barrier_portion_from_healing` --
        # the canonical no-barrier wireshape.
        barrier_portion_getter=barrier_portion_getter_heal,
        # Tour 6 v0.10.24 close-out: forward the optional
        # StunBreakEvent stream for the ``stun_breaks`` column.
        # When empty (canonical pre-Tour-6 SCAFFOLD path), every
        # row has ``stun_breaks=0``.
        stun_break_events=stun_break_events,
    )
    boons_rows: list[PlayerBoonsRow] = PlayerBoonsAggregator().aggregate(
        boon_apply_events,
        duration_s,
        name_map=skill_id_to_name_map,
        # Phase 3 SCAFFOLD: forward the optional buff-removal
        # stream. When ``None``, the per-player aggregator treats
        # it as an empty iterable -- the canonical
        # ``strips_received_in=0`` wireshape.
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
    # The union of all observed agent_ids in any aspect --
    # union (not intersection) so an NPC that appeared only in
    # the damage stream still surfaces (with empty Heal /
    # Boons / Defense aspect blocks).
    all_agent_ids = set(damage_by_id) | set(heal_by_id) | set(boons_by_id) | set(defense_by_id)

    # Single pass to build the per-agent PlayerReadoutOut envelope.
    # The 5 shared identity columns (per design doc §2) hydrate
    # from the ``AgentIdentity`` map (Tour 6 v0.10.24 close-out of
    # the Wave 5 SCAFFOLD NIT placeholders). ``agent_id`` is the
    # dispatcher-set value (the key of the per-aspect aggregator
    # outputs); the remaining 5 columns + ``account_name`` come
    # from the OrmFightAgent-hydrated identity slice. ``roles``
    # stays at ``[]`` (canonical Wave 2 SCAFFOLD default -- the
    # role classifier is Blocker C deferred to a future cycle).
    identity_map = agent_id_to_identity_map or {}
    # Intersect the union of per-aspect rows with the identity
    # map keys so NPC targets (target_agent_id in defense row
    # set without an is_player=True agent row in the DB) are
    # silently dropped from the envelope. This keeps the wire
    # shape strictly player-only.
    all_agent_ids = (
        set(damage_by_id) | set(heal_by_id) | set(boons_by_id) | set(defense_by_id)
    ) & set(identity_map)
    # Compose the per-aspect zero-row sentinels ONCE before the
    # per-agent loop so a player present in ONE aspect (e.g.
    # damage) but missing from ANOTHER (e.g. he never healed
    # anyone) does NOT crash with a ``KeyError`` on the missing-
    # aspect dict access. The zero-row ssoTiming is the canonical
    # Wave 2 SCAFFOLD default. The row-builders accept the
    # ``default`` argument directly via :func:`dict.get` -- no
    # intermediate float / int default values need to be inline.
    _zero_damage: PlayerDamageRow = PlayerDamageRow(
        source_agent_id=0,
        total_damage=0,
        attack_count=1,
        dps=0.0,
        dps_power=0.0,
        dps_condi=0.0,
    )
    _zero_heal: PlayerHealRow = PlayerHealRow(
        source_agent_id=0,
        total_healing=0,
        heal_count=1,
        hps=0.0,
        barrier_total=0,
        barrier_ps=0.0,
        stun_breaks=0,
    )
    _zero_boons: PlayerBoonsRow = PlayerBoonsRow(
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
    _zero_defense: PlayerDefenseRow = PlayerDefenseRow(
        agent_id=0,
        damage_taken=0,
        cc_taken=0,
        deaths=0,
    )
    # Reviewer #3 fix: TODO(v0.11.0) -- the truthy `or ""` collapse
    # on the ``account_name`` line below drops the distinction
    # between a None and an empty-string arcdps account-name; the
    # next cycle widens PlayerReadoutOut.account_name to
    # ``str | None`` (wire-contract migration) and removes the
    # coercion. The runtime behaviour still matches the
    # PlayerReadoutOut schema (``account_name: str``) so callers
    # see an empty string for an absent account -- documented at
    # the route module docstring to surface the lossy transition.
    players: list[PlayerReadoutOut] = [
        PlayerReadoutOut(
            agent_id=agent_id,
            subgroup=identity_map[agent_id].subgroup,
            name=identity_map[agent_id].name,
            account_name=identity_map[agent_id].account_name or "",
            profession=identity_map[agent_id].profession,
            elite_spec=identity_map[agent_id].elite_spec,
            is_commander=identity_map[agent_id].is_commander,
            roles=[],  # canonical Wave 2 SCAFFOLD default -- Blocker C deferred.
            damage=PlayerReadoutDamageOut(
                dps_total=damage_by_id.get(agent_id, _zero_damage).dps,
                # Phase 3 SCAFFOLD: power/condi split driven from
                # the per-player row's rate columns. Pre-Phase-6-v2
                # wireshape: ``dps_power=0.0 + dps_condi=dps``
                # (because :func:`gw2_core.default_dps_split`
                # returns ``(0, damage)`` -- the canonical
                # "everything is power" SCAFFOLD fallback).
                dps_power=damage_by_id.get(agent_id, _zero_damage).dps_power,
                dps_condi=damage_by_id.get(agent_id, _zero_damage).dps_condi,
                strips=0,  # awaits Phase 9 BuffRemovalEvent strip classification.
                cc_applied=0,  # awaits CCEvent source attribution (Phase 9 v2 yields).
                down_contribution_dps=0.0,  # awaits Phase 9 v2 'is target down' attribution.
                kills=0,  # awaits DeathEvent + DPS stream cross-walk (Phase 9 v2).
            ),
            heal=PlayerReadoutHealOut(
                heal_total=heal_by_id.get(agent_id, _zero_heal).total_healing,
                hps=heal_by_id.get(agent_id, _zero_heal).hps,
                # Phase 3 SCAFFOLD: heal-side barrier columns driven
                # from the per-player row. Pre-Phase-6-v2 wireshape:
                # ``barrier_total=0 + barrier_ps=0.0`` (because
                # :func:`gw2_core.default_barrier_portion_from_healing`
                # returns ``0`` -- the canonical no-barrier SCAFFOLD
                # fallback).
                barrier_total=heal_by_id.get(agent_id, _zero_heal).barrier_total,
                barrier_ps=heal_by_id.get(agent_id, _zero_heal).barrier_ps,
                cleanses=0,  # awaits ConditionRemoveEvent stream (Phase 6 v2 yields).
                # Tour 6 v0.10.24 close-out: stun_breaks populated
                # from the per-player row (actor-side attribution).
                stun_breaks=heal_by_id.get(agent_id, _zero_heal).stun_breaks,
            ),
            boons=PlayerReadoutBoonsOut(
                boons_out_rate=boons_by_id.get(agent_id, _zero_boons).boons_out_rate,
                boons_in_rate=boons_by_id.get(agent_id, _zero_boons).boons_in_rate,
                stability_out=boons_by_id.get(agent_id, _zero_boons).stability_out,
                alacrity_out=boons_by_id.get(agent_id, _zero_boons).alacrity_out,
                resistance_out=boons_by_id.get(agent_id, _zero_boons).resistance_out,
                aegis_out=boons_by_id.get(agent_id, _zero_boons).aegis_out,
                superspeed_out=boons_by_id.get(agent_id, _zero_boons).superspeed_out,
                stealth_out=boons_by_id.get(agent_id, _zero_boons).stealth_out,
                other_boons_out=dict(boons_by_id.get(agent_id, _zero_boons).other_boons_out),
            ),
            defense=PlayerReadoutDefenseOut(
                damage_taken=defense_by_id.get(agent_id, _zero_defense).damage_taken,
                cc_taken=defense_by_id.get(agent_id, _zero_defense).cc_taken,
                deaths=defense_by_id.get(agent_id, _zero_defense).deaths,
                time_downed_ms=defense_by_id.get(agent_id, _zero_defense).time_downed_ms,
                dodges=defense_by_id.get(agent_id, _zero_defense).dodges,
                blocks=defense_by_id.get(agent_id, _zero_defense).blocks,
                interrupts=defense_by_id.get(agent_id, _zero_defense).interrupts,
                barrier_absorbed=defense_by_id.get(agent_id, _zero_defense).barrier_absorbed,
            ),
        )
        for agent_id in sorted(all_agent_ids)
    ]

    return FightReadoutOut(
        fight_id=fight_id,
        duration_s=duration_s,
        players=players,
    )


__all__ = [
    "_aggregate_per_target_rollup",
    "aggregate_combat_readout",
    "aggregate_skill_usage",
    "aggregate_squad_rollup",
]
