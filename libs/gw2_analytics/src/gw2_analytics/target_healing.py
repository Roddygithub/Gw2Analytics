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

from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import HealingEvent

# HPS sentinel when ``duration_s <= 0``: invalid (zero/negative)
# duration collapses to 0.0 rather than raising -- the canonical
# ``HealingEvent`` stream from the parser will always pair with a
# known fight duration so the zero path is purely defensive.
_DEFAULT_HPS: Final[float] = 0.0


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


class TargetHealingAggregator:
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
    aggregator's signature.
    """

    def aggregate(
        self,
        events: Iterable[HealingEvent],
        duration_s: float,
        name_map: dict[int, str | None] | None = None,
    ) -> list[TargetHealingRow]:
        """Compute the roll-up from a stream of healing events.

        ``duration_s`` is the fight duration (the time-bucket the
        HPS rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.

        ``name_map`` is an OPTIONAL ``{agent_id: name}`` lookup for
        player-name denormalisation (v0.8.3). See
        :meth:`~gw2_analytics.target_dps.TargetDpsAggregator.aggregate`
        for the full contract; this method is a strict parallel.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        total_by_target: dict[int, int] = defaultdict(int)
        count_by_target: dict[int, int] = defaultdict(int)
        grand_total = 0
        for e in events:
            total_by_target[e.target_agent_id] += e.healing
            count_by_target[e.target_agent_id] += 1
            grand_total += e.healing

        hps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_HPS
        # ``name_map or {}`` -- see the parallel branch in
        # :meth:`~gw2_analytics.target_dps.TargetDpsAggregator.aggregate`
        # for the rationale (``dict.get`` returns ``None`` for missing
        # keys AND for explicit ``None`` values; both surface as the
        # ``name=None`` sentinel on the row).
        rows = [
            TargetHealingRow(
                target_agent_id=target,
                total_healing=total_by_target[target],
                heal_count=count_by_target[target],
                hps=total_by_target[target] * hps_factor,
                name=(name_map or {}).get(target),
            )
            for target in total_by_target
        ]
        # Sort: highest total_healing first; ties broken by ascending target_agent_id.
        rows.sort(key=lambda r: (-r.total_healing, r.target_agent_id))

        self._check_invariants(rows, grand_total)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[TargetHealingRow],
        expected_sum: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        actual_sum = sum(r.total_healing for r in rows)
        if actual_sum != expected_sum:
            msg = (
                f"sum of row.total_healing ({actual_sum}) != sum of event.healing ({expected_sum})"
            )
            raise ValueError(msg)
        for r in rows:
            if r.heal_count < 1:
                msg = (
                    f"TargetHealingRow({r.target_agent_id}).heal_count "
                    f"({r.heal_count}) must be >= 1"
                )
                raise ValueError(msg)
        # Pydantic field constraints already guarantee ``ge=0`` for total_healing;
        # the cross-row ordering invariant is the only ordering contract.
        # ``pairwise`` pairs each row with its immediate successor;
        # equivalent to ``zip(rows, rows[1:], strict=False)`` but
        # the canonical idiom for adjacent-pair iteration (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.total_healing < curr.total_healing:
                msg = (
                    f"rows not ordered by (total_healing DESC, "
                    f"target_agent_id ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if (
                prev.total_healing == curr.total_healing
                and prev.target_agent_id >= curr.target_agent_id
            ):
                msg = (
                    f"tie on total_healing not broken by "
                    f"target_agent_id ASC: {prev!r} then {curr!r}"
                )
                raise ValueError(msg)


__all__ = ["TargetHealingAggregator", "TargetHealingRow"]
