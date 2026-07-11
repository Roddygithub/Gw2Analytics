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
"""

from __future__ import annotations

from typing import cast

from gw2_analytics.skill_usage import SkillUsageAggregator, SkillUsageRow
from gw2_analytics.squad_rollup import SquadRollupAggregator, SquadRollupRow
from gw2_analytics.target_buff_removal import (
    TargetBuffRemovalAggregator,
    TargetBuffRemovalRow,
)
from gw2_analytics.target_dps import TargetDpsAggregator, TargetDpsRow
from gw2_analytics.target_healing import TargetHealingAggregator, TargetHealingRow
from gw2_core import BuffRemovalEvent, DamageEvent, Event, HealingEvent


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
    -----------
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


__all__ = [
    "_aggregate_per_target_rollup",
    "aggregate_skill_usage",
    "aggregate_squad_rollup",
]
