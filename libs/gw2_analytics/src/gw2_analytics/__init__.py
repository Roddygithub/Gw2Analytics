"""Multi-level analytics built on top of :mod:`gw2_core`.

Exposes ten siblings across five phases (Phase 7 v1 added the healing
roll-up; Phase 8 added the buff-removal roll-up; v0.7.0 added the
player-profile, squad-rollup, and skill-usage aggregators):

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
- :class:`~gw2_analytics.player_profile.PlayerProfileAggregator` --
  an iterable of :class:`~gw2_analytics.player_profile.FightContribution`
  -> per-account cross-fight player profiles (v0.7.0; the
  player-centric view of the dataset, keying on ``account_name``).
- :class:`~gw2_analytics.squad_rollup.SquadRollupAggregator` --
  paired damage + healing + buff-removal streams + a
  ``agent_id -> subgroup`` map -> per-subgroup roll-up rows
  (v0.7.0; the squad-performance view of a single fight, source-side).
- :class:`~gw2_analytics.skill_usage.SkillUsageAggregator` --
  paired damage + healing + buff-removal streams + a
  ``skill_id -> skill_name`` map -> per-skill roll-up rows
  (v0.7.0; the skill-by-skill impact view of a single fight).

The DPS + Healing + BuffRemoval aggregators accept single-typed streams
(``Iterable[DamageEvent]`` / ``Iterable[HealingEvent]`` /
``Iterable[BuffRemovalEvent]``); consumers with a heterogeneous
``Iterable[Event]`` stream (e.g. the API route layer parsing the
per-fight JSONL blob) split the stream by ``isinstance`` at the call
site and invoke all three aggregators on the same ``duration_s`` --
each aggregator stays free of cross-kind discrimination in its hot
loop.

The v0.7.0 SquadRollup + SkillUsage aggregators accept the same
paired-streams form (three single-typed streams) so the route layer
can invoke all three per-target aggregators AND both per-fight
rollups from a single ``isinstance``-split pass.
"""

from __future__ import annotations

__version__ = "0.8.0"
