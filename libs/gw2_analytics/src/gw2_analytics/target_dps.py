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

from collections import defaultdict
from collections.abc import Iterable
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import DamageEvent

# DPS sentinel when ``duration_s <= 0``: invalid (zero/negative) duration
# collapses to 0.0 rather than raising -- the canonical ``DamageEvent``
# stream from the parser will always pair with a known fight duration
# so the zero path is purely defensive.
_DEFAULT_DPS: Final[float] = 0.0


class TargetDpsRow(BaseModel):
    """One roll-up row: damage + DPS directed at a single target agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_agent_id: int = Field(..., ge=0)
    total_damage: int = Field(..., ge=0)
    attack_count: int = Field(..., ge=1)
    dps: float = Field(..., ge=0.0)


class TargetDpsAggregator:
    """Stateless aggregator: events -> per-target DPS roll-up rows.

    Instantiate once and reuse -- the class holds no state.
    """

    def aggregate(
        self,
        events: Iterable[DamageEvent],
        duration_s: float,
    ) -> list[TargetDpsRow]:
        """Compute the roll-up from a stream of damage events.

        ``duration_s`` is the fight duration (the time-bucket the DPS
        rate is measured against). Passed by the caller so the
        aggregator stays free of cross-source metadata.
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        total_by_target: dict[int, int] = defaultdict(int)
        count_by_target: dict[int, int] = defaultdict(int)
        grand_total = 0
        for e in events:
            total_by_target[e.target_agent_id] += e.damage
            count_by_target[e.target_agent_id] += 1
            grand_total += e.damage

        dps_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_DPS
        rows = [
            TargetDpsRow(
                target_agent_id=target,
                total_damage=total_by_target[target],
                attack_count=count_by_target[target],
                dps=total_by_target[target] * dps_factor,
            )
            for target in total_by_target
        ]
        # Sort: highest total_damage first; ties broken by ascending target_agent_id.
        rows.sort(key=lambda r: (-r.total_damage, r.target_agent_id))

        self._check_invariants(rows, grand_total)
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[TargetDpsRow],
        expected_sum: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        actual_sum = sum(r.total_damage for r in rows)
        if actual_sum != expected_sum:
            msg = f"sum of row.total_damage ({actual_sum}) != sum of event.damage ({expected_sum})"
            raise ValueError(msg)
        for r in rows:
            if r.attack_count < 1:
                msg = (
                    f"TargetDpsRow({r.target_agent_id}).attack_count "
                    f"({r.attack_count}) must be >= 1"
                )
                raise ValueError(msg)
        # Pydantic field constraints already guarantee ``ge=0`` for total_damage;
        # the cross-row ordering invariant is the only ordering contract.
        # ``pairwise`` pairs each row with its immediate successor;
        # equivalent to ``zip(rows, rows[1:], strict=False)`` but
        # the canonical idiom for adjacent-pair iteration (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.total_damage < curr.total_damage:
                msg = (
                    f"rows not ordered by (total_damage DESC, "
                    f"target_agent_id ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if (
                prev.total_damage == curr.total_damage
                and prev.target_agent_id >= curr.target_agent_id
            ):
                msg = (
                    f"tie on total_damage not broken by target_agent_id ASC: {prev!r} then {curr!r}"
                )
                raise ValueError(msg)


__all__ = ["TargetDpsAggregator", "TargetDpsRow"]
