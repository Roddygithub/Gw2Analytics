"""

Phase 8: per-target buff-removal roll-ups from synthetic
:class:`BuffRemovalEvent` streams.

Phase 8 ships the third ``Event`` discriminated union member + a
third per-target aggregator to consume it. This file is the strict
parallel of :mod:`gw2_analytics.target_healing` and the trio with
:mod:`gw2_analytics.target_dps` -- the schema, ordering, invariants,
duration sentinel, and overall shape mirror ``target_dps`` /
``target_healing`` so the three modules read as one design.

Why BPS (buffs-per-second), not just total_buff_removal
=======================================================

The damage / healing aggregators expose a rate (DPS / HPS) so the
analyst can spot a spike at a glance. The buff-removal roll-up
mirrors that choice: ``bps = total_buff_removal / duration_s``
when ``duration_s > 0``, ``bps = 0.0`` otherwise. Negative duration
is rejected at the call site. The unit name ("buffs per second")
is intentionally unitless in the schema: ``total_buff_removal`` is
the integer ``buff_dmg`` value summed across the target's
``BuffRemovalEvent`` stream and is not strictly a count of boons
stripped (one corrupting skill on a target with 3 stacked boons
can write ``buff_dmg = 1500``).

Conventions
===========

- **Deterministic ordering.** Rows sorted by
  ``(-total_buff_removal, target_agent_id)`` -- highest removal
  first; ties broken by ascending ``target_agent_id``. Two runs
  over the same input MUST yield byte-identical row output.
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **BPS = ``total_buff_removal / duration_s`` when ``duration_s > 0``.**
  When ``duration_s == 0`` we emit ``bps=0.0`` (zero-duration is a
  sentinel "duration not provided" rather than a math singularity).
  Negative duration is rejected -- callers can guard at upstream
  sites where ``fight.duration`` is known.

Cross-field invariants (validated post-construction; violations raise
``ValueError``):

- Sum of ``row.total_buff_removal`` across all rows == sum of
  ``event.buff_removal`` across input events (no event dropped, no
  double-counting).
- Rows monotonically non-increasing by ``total_buff_removal``; ties
  broken by ascending ``target_agent_id``.
- Every row has ``strip_count >= 1``.

Forward compat
==============

The aggregator signature (``Iterable[BuffRemovalEvent]`` ->
``list[TargetBuffRemovalRow]``) is stable. A future in-parser
switch from synthetic event lists to ``gw2_evtc_parser.parse_events``
output only changes the upstream producer -- the aggregator body
reads only ``buff_removal`` from each event and is unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BuffRemovalEvent

# BPS sentinel when ``duration_s <= 0``: invalid (zero/negative)
# duration collapses to 0.0 rather than raising -- the canonical
# ``BuffRemovalEvent`` stream from the parser will always pair with a
# known fight duration so the zero path is purely defensive.
_DEFAULT_BPS: Final[float] = 0.0


class TargetBuffRemovalRow(BaseModel):
    """One roll-up row: buff-removal + BPS directed at a single target agent.

    The target_agent_id is the agent FROM WHOM the boon is being
    stripped (i.e. the receiving end of the strip). This mirrors the
    semantics of :class:`~gw2_analytics.target_dps.TargetDpsRow` and
    :class:`~gw2_analytics.target_healing.TargetHealingRow`, which
    are also keyed on the receiving agent. For "top strippers"
    (output grouped by source_agent_id), use a separate aggregator.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent_id: int = Field(..., ge=0)
    total_buff_removal: int = Field(..., ge=0)
    strip_count: int = Field(..., ge=1)
    bps: float = Field(..., ge=0.0)


class TargetBuffRemovalAggregator:
    """Stateless aggregator: events -> per-target buff-removal roll-up rows.

    Instantiate once and reuse -- the class holds no state.

    This mirrors :class:`~gw2_analytics.target_dps.TargetDpsAggregator`
    and :class:`~gw2_analytics.target_healing.TargetHealingAggregator`
    exactly in shape; only the field names (``total_buff_removal`` /
    ``strip_count`` / ``bps``) and the input event type
    (``BuffRemovalEvent`` instead of ``DamageEvent`` /
    ``HealingEvent``) differ. Downstream callers that already split
    a heterogeneous ``Iterable[Event]`` stream into per-kind iterators
    at the route layer can call all three aggregators on the same
    ``duration_s`` to get one combined damage + healing +
    buff-removal per-target view without changing any aggregator's
    signature.
    """

    def aggregate(
        self,
        events: Iterable[BuffRemovalEvent],
        duration_s: float,
    ) -> list[TargetBuffRemovalRow]:
        """Compute the roll-up from a stream of buff-removal events.

        ``duration_s`` is the fight duration (the time-bucket the
        BPS rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        total_by_target: dict[int, int] = defaultdict(int)
        count_by_target: dict[int, int] = defaultdict(int)
        grand_total = 0
        for e in events:
            total_by_target[e.target_agent_id] += e.buff_removal
            count_by_target[e.target_agent_id] += 1
            grand_total += e.buff_removal

        bps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_BPS
        rows = [
            TargetBuffRemovalRow(
                target_agent_id=target,
                total_buff_removal=total_by_target[target],
                strip_count=count_by_target[target],
                bps=total_by_target[target] * bps_factor,
            )
            for target in total_by_target
        ]
        # Sort: highest total_buff_removal first; ties broken by ascending target_agent_id.
        rows.sort(key=lambda r: (-r.total_buff_removal, r.target_agent_id))

        self._check_invariants(rows, grand_total)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[TargetBuffRemovalRow],
        expected_sum: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        actual_sum = sum(r.total_buff_removal for r in rows)
        if actual_sum != expected_sum:
            msg = (
                f"sum of row.total_buff_removal ({actual_sum}) != "
                f"sum of event.buff_removal ({expected_sum})"
            )
            raise ValueError(msg)
        for r in rows:
            if r.strip_count < 1:
                msg = (
                    f"TargetBuffRemovalRow({r.target_agent_id}).strip_count "
                    f"({r.strip_count}) must be >= 1"
                )
                raise ValueError(msg)
        # Pydantic field constraints already guarantee ``ge=0`` for
        # total_buff_removal; the cross-row ordering invariant is the
        # only ordering contract. ``pairwise`` pairs each row with its
        # immediate successor; equivalent to
        # ``zip(rows, rows[1:], strict=False)`` but the canonical
        # idiom for adjacent-pair iteration (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.total_buff_removal < curr.total_buff_removal:
                msg = (
                    f"rows not ordered by (total_buff_removal DESC, "
                    f"target_agent_id ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if (
                prev.total_buff_removal == curr.total_buff_removal
                and prev.target_agent_id >= curr.target_agent_id
            ):
                msg = (
                    f"tie on total_buff_removal not broken by "
                    f"target_agent_id ASC: {prev!r} then {curr!r}"
                )
                raise ValueError(msg)


__all__ = ["TargetBuffRemovalAggregator", "TargetBuffRemovalRow"]
