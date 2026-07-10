"""

Phase 7: per-target healing roll-ups from synthetic :class:`HealingEvent`
streams.

Phase 7 v1 ships aggregators over IN-MEMORY event lists because the
gw2_evtc_parser event block surfaces streams of ``HealingEvent``
records; the consumer-side filtering is the canonical discrimination
(route layer / service layer splits ``Iterable[Event]`` into separate
``Iterable[DamageEvent]`` / ``Iterable[HealingEvent]`` iterators
before invoking the appropriate aggregator).

This file is the strict parallel of :mod:`gw2_analytics.target_dps`
(``TargetDpsRow`` <-> ``TargetHealingRow``,
``TargetDpsAggregator`` <-> ``TargetHealingAggregator``);
see that module for the damage-roll-up counterpoint.

This file is the strict parallel of :mod:`gw2_analytics.target_dps`:
the schema, ordering, invariants, duration sentinel, and overall
shape mirror ``target_dps`` so the pair reads as one design.

Conventions
===========

- **Deterministic ordering.** Rows sorted by
  ``(-total_healing, target_agent_id)`` -- highest healing first;
  ties broken by ascending ``target_agent_id``. Two runs over the
  same input MUST yield byte-identical row output.
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **HPS = ``total_healing / duration_s`` when ``duration_s > 0``.**
  When ``duration_s == 0`` we emit ``hps=0.0`` (zero-duration is a
  sentinel "duration not provided" rather than a math singularity).
  The GW2 community standard term for the outgoing-heal rate is
  ``HPS`` (healing per second) -- documented inline so future
  readers do not have to grep the dashboard code to learn the
  abbreviation. Negative duration is rejected -- callers can guard
  at upstream sites where ``fight.duration`` is known.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- Sum of ``row.total_healing`` across all rows == sum of
  ``event.healing`` across input events (no event dropped, no
  double-counting).
- Rows monotonically non-increasing by ``total_healing``; ties
  broken by ascending ``target_agent_id``.
- Every row has ``heal_count >= 1``.

Forward compat
==============

The aggregator signature (``Iterable[HealingEvent]`` ->
``list[TargetHealingRow]``) is stable. A future in-parser switch
from synthetic event lists to ``gw2_evtc_parser.parse_events``
output only changes the upstream producer -- the aggregator body
reads only ``healing`` from each event and is unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gw2_analytics._per_target_base import PerTargetRollupBase, PerTargetRollupSpec
from gw2_core import HealingEvent


class TargetHealingRow(BaseModel):
    """One roll-up row: healing + HPS directed at a single target agent.

    The target_agent_id is the agent RECEIVING the heal (mirrors the
    semantics of :class:`~gw2_analytics.target_dps.TargetDpsRow`,
    which is also keyed on the receiving agent). For "top healers"
    (output grouped by source_agent_id), use a separate aggregator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent_id: int = Field(..., ge=0)
    total_healing: int = Field(..., ge=0)
    heal_count: int = Field(..., ge=1)
    hps: float = Field(..., ge=0.0)
    # Optional player-name denormalisation (v0.8.3). See
    # :class:`~gw2_analytics.target_dps.TargetDpsRow.name` for the
    # contract (None = unresolved; the route surfaces ``null`` on
    # the wire; the frontend falls back to the raw
    # ``target_agent_id``). Strict parallel of the DPS row so the
    # trio reads as one design.
    name: str | None = None


# HPS aggregator config: the 4 field-name slugs that specialise the
# shared :class:`PerTargetRollupBase` for healing roll-ups.
_HPS_SPEC = PerTargetRollupSpec(
    event_attr="healing",
    total_field="total_healing",
    count_field="heal_count",
    rate_field="hps",
)


class TargetHealingAggregator(PerTargetRollupBase[HealingEvent, TargetHealingRow]):
    """Stateless aggregator: events -> per-target healing roll-up rows.

    Instantiate once and reuse -- the class holds no state.

    This mirrors :class:`~gw2_analytics.target_dps.TargetDpsAggregator`
    exactly in shape; only the field names (``total_healing`` /
    ``heal_count`` / ``hps``) and the input event type
    (``HealingEvent`` instead of ``DamageEvent``) differ. Downstream
    callers that already split a heterogeneous ``Iterable[Event]``
    stream into per-kind iterators at the route layer can call both
    aggregators on the same ``duration_s`` to get one combined
    damage + healing per-target view without changing either
    aggregator's signature. The shared accumulate / rate / sort /
    invariant logic lives in
    :class:`~gw2_analytics._per_target_base.PerTargetRollupBase`; this
    subclass supplies only the healing-specific field names via
    :data:`_HPS_SPEC`.
    """

    def __init__(self) -> None:
        super().__init__(_HPS_SPEC, TargetHealingRow)


__all__ = ["TargetHealingAggregator", "TargetHealingRow"]
