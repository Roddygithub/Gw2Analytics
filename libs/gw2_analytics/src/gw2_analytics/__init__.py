"""Multi-level analytics built on top of :mod:`gw2_core`.

Exposes seven siblings (Phase 7 v1 added the healing roll-up; Phase 8
added the buff-removal roll-up):

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
- :class:`~gw2_analytics.target_buff_removal.TargetBuffRemovalAggregator`
  -- a stream of :class:`~gw2_core.BuffRemovalEvent` -> per-target BPS
  (buff-removal-per-second) roll-up rows (Phase 8; strict parallel of
  the DPS + Healing aggregators).
- :class:`~gw2_analytics.event_window.EventWindowAggregator` -- a stream of
  :class:`~gw2_core.Event` -> time-bucketed roll-ups.

The DPS + Healing + BuffRemoval aggregators accept single-typed streams
(``Iterable[DamageEvent]`` / ``Iterable[HealingEvent]`` /
``Iterable[BuffRemovalEvent]``); consumers with a heterogeneous
``Iterable[Event]`` stream (e.g. the API route layer parsing the
per-fight JSONL blob) split the stream by ``isinstance`` at the call
site and invoke all three aggregators on the same ``duration_s`` --
each aggregator stays free of cross-kind discrimination in its hot
loop.
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
from gw2_analytics.target_buff_removal import (
    TargetBuffRemovalAggregator,
    TargetBuffRemovalRow,
)
from gw2_analytics.target_dps import TargetDpsAggregator, TargetDpsRow
from gw2_analytics.target_healing import TargetHealingAggregator, TargetHealingRow

__version__ = "0.5.0"

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
    "TargetBuffRemovalAggregator",
    "TargetBuffRemovalRow",
    "TargetDpsAggregator",
    "TargetDpsRow",
    "TargetHealingAggregator",
    "TargetHealingRow",
    "__version__",
]
