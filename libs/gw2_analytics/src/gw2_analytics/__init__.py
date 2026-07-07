"""Multi-level analytics built on top of :mod:`gw2_core`.

Exposes four siblings:

- :class:`~gw2_analytics.aggregate.SingleFightAggregator` -- one parsed
  :class:`~gw2_core.Fight` -> one :class:`~gw2_analytics.aggregate.FightAggregate`.
- :class:`~gw2_analytics.multi_fight.MultiFightAggregator` -- an iterable
  of parsed ``Fight`` records -> one
  :class:`~gw2_analytics.multi_fight.MultiFightAggregate`.
- :class:`~gw2_analytics.target_dps.TargetDpsAggregator` -- a stream of
  :class:`~gw2_core.DamageEvent` -> per-target DPS roll-up rows
  (Phase 6 v1; input is synthetic until the parser surfaces events).
- :class:`~gw2_analytics.event_window.EventWindowAggregator` -- a stream of
  :class:`~gw2_core.Event` -> time-bucketed roll-ups
  (Phase 6 v1; same parser-forward-compat note).
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

__version__ = "0.3.0"

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
    "__version__",
]
