"""Multi-level analytics built on top of :mod:`gw2_core`.

Exposes :class:`~gw2_analytics.aggregate.SingleFightAggregator` which
builds a :class:`~gw2_analytics.aggregate.FightAggregate` from a parsed
:class:`~gw2_core.Fight`. Event-derived aggregations (target DPS,
damage taken, etc.) land in a later phase as siblings to
:class:`SingleFightAggregator`, leaving this package surface stable.
"""

from __future__ import annotations

from gw2_analytics.aggregate import (
    CombatantSummary,
    FightAggregate,
    GroupSummary,
    SingleFightAggregator,
    SkillCatalogEntry,
)

__version__ = "0.1.0"

__all__ = [
    "CombatantSummary",
    "FightAggregate",
    "GroupSummary",
    "SingleFightAggregator",
    "SkillCatalogEntry",
    "__version__",
]
