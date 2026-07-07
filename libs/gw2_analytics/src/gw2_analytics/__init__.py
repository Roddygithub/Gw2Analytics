"""Multi-level analytics built on top of :mod:`gw2_core`.

Exposes six siblings (Phase 7 v1 added the healing roll-up):

- :class:`~gw2_analytics.aggregate.SingleFightAggregator` -- one parsed
  :class:`~gw2_core.Fight` -> one :class:`~gw2_analytics.aggregate.FightAggregate`.
- :class:`~gw2_analytics.multi_fight.MultiFightAggregator` -- an iterable
  of parsed ``Fight`` records -> one
  :class:`~gw2_analytics.multi_fight.MultiFightAggregate`.
- :class:`~gw2_analytics.target_dps.TargetDpsAggregator` -- a stream of
  :class:`~gw2_core.DamageEvent` -> per-target DPS roll-up rows.
- :class:`~gw2_analytics.target_healing.TargetHealingAggregator` -- a stream of
  :class:`~gw2_core.HealingEvent` -> per-target HPS (healing-per-second) roll-up rows
  (Phase 7 v1; strict parallel of
  :class:`~gw2_analytics.target_dps.TargetDpsAggregator`).
- :class:`~gw2_analytics.event_window.EventWindowAggregator` -- a stream of
  :class:`~gw2_core.Event` -> time-bucketed roll-ups.

The DPS + Healing aggregators accept single-typed streams
(``Iterable[DamageEvent]`` / ``Iterable[HealingEvent]``); consumers
with a heterogeneous ``Iterable[Event]`` stream (e.g. the API route
layer parsing the per-fight JSONL blob) split the stream by
``isinstance`` at the call site and invoke both aggregators on the
same ``duration_s`` -- each aggregator stays free of cross-kind
discrimination in its hot loop.
"""

from __future__ import annotations

from gw2_analytics.aggregate import (
    CombatantSummary,
    FightAggregate,
    GroupSummary,
    SingleFightAggregator,
    SkillCatalogEntry,
)
from gw2_analytics.event_window import EventBucket, EventWindowAggregator
from gw2_analytics.multi_fight import (
    CombatantRollup,
    MultiFightAggregate,
    MultiFightAggregator,
)
from gw2_analytics.target_dps import TargetDpsAggregator, TargetDpsRow
from gw2_analytics.target_healing import TargetHealingAggregator, TargetHealingRow

__version__ = "0.4.0"

__all__ = [
    "CombatantRollup",
    "CombatantSummary",
    "EventBucket",
    "EventWindowAggregator",
    "FightAggregate",
    "GroupSummary",
    "MultiFightAggregate",
    "MultiFightAggregator",
    "SingleFightAggregator",
    "SkillCatalogEntry",
    "TargetDpsAggregator",
    "TargetDpsRow",
    "TargetHealingAggregator",
    "TargetHealingRow",
    "__version__",
]
