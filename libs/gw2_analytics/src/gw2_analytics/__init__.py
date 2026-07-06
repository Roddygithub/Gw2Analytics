"""Multi-level analytics built on top of :mod:`gw2_core`.

Exposes:

- :class:`~gw2_analytics.aggregate.SingleFightAggregator` -- one
  parsed :class:`~gw2_core.Fight` -> one
  :class:`~gw2_analytics.aggregate.FightAggregate`.
- :class:`~gw2_analytics.multi_fight.MultiFightAggregator` --
  an iterable of parsed ``Fight`` records -> one
  :class:`~gw2_analytics.multi_fight.MultiFightAggregate`.

Event-derived aggregations (target DPS, damage taken, etc.) land in a
later phase as siblings to these aggregators, leaving this package
surface stable.
"""

from __future__ import annotations

from gw2_analytics.aggregate import (
    CombatantSummary,
    FightAggregate,
    GroupSummary,
    SingleFightAggregator,
    SkillCatalogEntry,
)
from gw2_analytics.multi_fight import (
    CombatantRollup,
    MultiFightAggregate,
    MultiFightAggregator,
)

__version__ = "0.2.0"

__all__ = [
    "CombatantRollup",
    "CombatantSummary",
    "FightAggregate",
    "GroupSummary",
    "MultiFightAggregate",
    "MultiFightAggregator",
    "SingleFightAggregator",
    "SkillCatalogEntry",
    "__version__",
]
