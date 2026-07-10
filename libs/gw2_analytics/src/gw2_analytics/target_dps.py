"""

Phase 6: per-target damage roll-ups from synthetic :class:`DamageEvent`
streams.

Phase 6 v1 ships aggregators over IN-MEMORY event lists because the
gw2_evtc_parser does not yet surface the event block. Forward-compat
notes (Phase 6 v2) live in the module docstring.

Conventions
===========

- **Deterministic ordering.** Rows sorted by
  ``(-total_damage, target_agent_id)`` -- highest damage first; ties
  broken by ascending ``target_agent_id``. Two runs over the same input
  MUST yield byte-identical row output.
- This file is the strict parallel of :mod:`gw2_analytics.target_healing`
  (``TargetDpsRow`` <-> ``TargetHealingRow``,
  ``TargetDpsAggregator`` <-> ``TargetHealingAggregator``);
  see that module for the healing-roll-up counterpoint (added in
  Phase 7 v1).
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **DPS = ``total_damage / duration_s`` when ``duration_s > 0``.**
  When ``duration_s == 0`` we emit ``dps=0.0`` (zero-duration is a
  sentinel "duration not provided" rather than a math singularity).
  Negative duration is rejected -- callers can guard at upstream sites
  where ``fight.duration`` is known.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- Sum of ``row.total_damage`` across all rows == sum of ``event.damage``
  across input events (no event dropped, no double-counting).
- Rows monotonically non-increasing by ``total_damage``; ties broken
  by ascending ``target_agent_id``.
- Every row has ``attack_count >= 1``.

Forward compat
==============

Phase 6 v2 will swap ``Iterable[DamageEvent]`` for
``Iterable[Event]`` (the discriminated union) at the aggregator
boundary -- callers that already produce a stream of damage events
are unchanged; the aggregator continues to read only ``damage`` from
the input. The :class:`TargetDpsRow` schema stays unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._per_target_base import PerTargetRollupBase, PerTargetRollupSpec
from gw2_core import DamageEvent


class TargetDpsRow(BaseModel):
    """One roll-up row: damage + DPS directed at a single target agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent_id: int = Field(..., ge=0)
    total_damage: int = Field(..., ge=0)
    attack_count: int = Field(..., ge=1)
    dps: float = Field(..., ge=0.0)
    # Optional player-name denormalisation (v0.8.3). ``None`` when the
    # aggregator was called without a ``name_map`` (the canonical
    # backward-compat case -- existing tests / callers don't care
    # about target resolution) OR when the agent id has no name in
    # the map (an NPC without a registered arcdps char-name -- the
    # route surfaces it as ``null`` on the wire). The schema is
    # additive: existing wire consumers ignore the new field.
    name: str | None = None


# DPS aggregator config: the 4 field-name slugs that specialise the
# shared :class:`PerTargetRollupBase` for damage roll-ups.
_DPS_SPEC = PerTargetRollupSpec(
    event_attr="damage",
    total_field="total_damage",
    count_field="attack_count",
    rate_field="dps",
)


class TargetDpsAggregator(PerTargetRollupBase[DamageEvent, TargetDpsRow]):
    """Stateless aggregator: events -> per-target DPS roll-up rows.

    Instantiate once and reuse -- the class holds no state. The
    accumulate / rate / sort / invariant logic lives in
    :class:`~gw2_analytics._per_target_base.PerTargetRollupBase`; this
    subclass supplies only the damage-specific field names via
    :data:`_DPS_SPEC`.
    """

    def __init__(self) -> None:
        super().__init__(_DPS_SPEC, TargetDpsRow)


__all__ = ["TargetDpsAggregator", "TargetDpsRow"]
