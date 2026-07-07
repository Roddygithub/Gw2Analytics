"""Per-subgroup (squad) roll-up -- the squad-performance view of a single fight.

Phase 7 v2 of analytics (v0.7.0 release). Walks the heterogeneous
:class:`Event` stream of one fight, buckets each event by the
``subgroup`` string of its source agent, and emits one
:class:`SquadRollupRow` per subgroup with the total damage / healing
/ buff-removal the subgroup produced, plus the per-second rates.

Conventions
===========

- **Source-side roll-up.** The subgroup is the actor's, not the
  target's. ``event.source_agent_id`` is looked up in the
  ``agent_id_to_subgroup`` map; a damage event from agent ``42`` in
  subgroup ``"Subgroup 1"`` is attributed to ``"Subgroup 1"``'s
  total. This matches the gw2-mists / arcdps convention where a
  "squad DPS" panel shows the squad's outgoing contribution rather
  than the damage they absorbed.
- **Unknown source_agent_id.** An event whose source agent is not
  in the map (e.g. an NPC without a subgroup, a gadget, a
  projectile owner whose id is stale) lands in the ``""``
  (empty-string) bucket. The empty string is a VALID subgroup
  label that mirrors the parser's lenient-parser WvW quirk
  convention -- an explicit empty bucket is preferred over a
  silent drop because the route layer can then surface a
  "Unattributed" line in the UI rather than a misleading
  under-count.
- **Deterministic ordering.** Rows sorted by
  ``(-total_damage, subgroup)`` -- highest damage first; ties
  broken by ascending ``subgroup`` (alphabetical, mirrors the
  :class:`~gw2_analytics.target_dps.TargetDpsAggregator` /
  :class:`~gw2_analytics.target_healing.TargetHealingAggregator`
  sort contract).
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **Rates = ``total / duration_s`` when ``duration_s > 0``.**
  When ``duration_s == 0`` we emit ``rate=0.0`` (zero-duration
  is a sentinel "duration not provided" rather than a math
  singularity). Negative duration is rejected -- callers can
  guard at upstream sites where ``fight.duration`` is known.

Cross-field invariants (validated post-construction; violations
raise ``ValueError``):

- Sum of ``row.total_damage`` across all rows == sum of
  ``event.damage`` across input damage events (no event dropped,
  no double-counting). Same for healing / buff-removal.
- Sum of ``row.hit_count`` across all rows == total number of
  events across all three input streams.
- Rows monotonically non-increasing by ``total_damage``; ties
  broken by ascending ``subgroup``.

Forward compat
==============

The aggregator signature is the paired-streams form
(``Iterable[DamageEvent]`` + ``Iterable[HealingEvent]`` +
``Iterable[BuffRemovalEvent]`` + ``agent_id_to_subgroup`` +
``duration_s``) so a future v0.8.0 release that swaps the
synthetic ``Iterable[Event]`` input for a parser-sourced stream
changes only the upstream producer. The aggregator body still
reads only ``damage`` / ``healing`` / ``buff_removal`` /
``source_agent_id`` from each event.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent

# Rate sentinel when ``duration_s <= 0``: invalid (zero/negative)
# duration collapses to 0.0 rather than raising -- the canonical
# ``Event`` stream from the parser will always pair with a known
# fight duration so the zero path is purely defensive.
_DEFAULT_RATE: Final[float] = 0.0


class SquadRollupRow(BaseModel):
    """One roll-up row: damage + healing + buff-removal + rates for one subgroup.

    ``subgroup`` is the source-side squad string. The empty string
    ``""`` is a valid label and gets its own row here, mirroring the
    parser's lenient-parser WvW quirk convention.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subgroup: str = Field(default="", max_length=128)
    total_damage: int = Field(..., ge=0)
    total_healing: int = Field(..., ge=0)
    total_buff_removal: int = Field(..., ge=0)
    hit_count: int = Field(..., ge=0)
    dps: float = Field(..., ge=0.0)
    hps: float = Field(..., ge=0.0)
    bps: float = Field(..., ge=0.0)


class SquadRollupAggregator:
    """Stateless aggregator: events + agent map -> per-subgroup roll-up rows.

    Instantiate once and reuse -- the class holds no state.

    This is the strict parallel of
    :class:`~gw2_analytics.target_dps.TargetDpsAggregator` /
    :class:`~gw2_analytics.target_healing.TargetHealingAggregator`
    in spirit (per-actor roll-up) but groups by ``subgroup`` rather
    than by ``target_agent_id`` (per-target) or by ``source_agent_id``
    (per-actor). The schema is a strict superset of the per-target
    trio: it carries the three totals + the per-second rates +
    ``hit_count`` so the UI can render a single panel per squad.
    """

    def aggregate(
        self,
        damage_events: Iterable[DamageEvent],
        healing_events: Iterable[HealingEvent],
        strip_events: Iterable[BuffRemovalEvent],
        agent_id_to_subgroup: Mapping[int, str],
        duration_s: float,
    ) -> list[SquadRollupRow]:
        """Compute the per-subgroup roll-up.

        ``agent_id_to_subgroup`` is the per-fight ``OrmFightAgent``-derived
        map of ``agent_id`` -> ``subgroup`` (empty string when the
        agent has no subgroup assigned). Events whose
        ``source_agent_id`` is not in the map land in the empty-string
        bucket (the canonical "Unattributed" label).

        ``duration_s`` is the fight duration (the time-bucket the
        DPS / HPS / BPS rates are measured against).
        """
        if duration_s < 0:
            msg = f"duration_s must be >= 0, got {duration_s!r}"
            raise ValueError(msg)

        total_damage: dict[str, int] = defaultdict(int)
        total_healing: dict[str, int] = defaultdict(int)
        total_strip: dict[str, int] = defaultdict(int)
        hit_count: dict[str, int] = defaultdict(int)
        grand_damage = 0
        grand_healing = 0
        grand_strip = 0
        grand_hits = 0

        for dmg in damage_events:
            subgroup = agent_id_to_subgroup.get(dmg.source_agent_id, "")
            total_damage[subgroup] += dmg.damage
            hit_count[subgroup] += 1
            grand_damage += dmg.damage
            grand_hits += 1
        for heal in healing_events:
            subgroup = agent_id_to_subgroup.get(heal.source_agent_id, "")
            total_healing[subgroup] += heal.healing
            hit_count[subgroup] += 1
            grand_healing += heal.healing
            grand_hits += 1
        for strip in strip_events:
            subgroup = agent_id_to_subgroup.get(strip.source_agent_id, "")
            total_strip[subgroup] += strip.buff_removal
            hit_count[subgroup] += 1
            grand_strip += strip.buff_removal
            grand_hits += 1

        rate_factor = 1.0 / duration_s if duration_s > 0 else _DEFAULT_RATE
        rows = [
            SquadRollupRow(
                subgroup=subgroup,
                total_damage=total_damage[subgroup],
                total_healing=total_healing[subgroup],
                total_buff_removal=total_strip[subgroup],
                hit_count=hit_count[subgroup],
                dps=total_damage[subgroup] * rate_factor,
                hps=total_healing[subgroup] * rate_factor,
                bps=total_strip[subgroup] * rate_factor,
            )
            for subgroup in set(total_damage) | set(total_healing) | set(total_strip)
        ]
        # Sort: highest total_damage first; ties broken by ascending subgroup.
        rows.sort(key=lambda r: (-r.total_damage, r.subgroup))

        self._check_invariants(
            rows,
            grand_damage,
            grand_healing,
            grand_strip,
            grand_hits,
        )
        return rows

    @staticmethod
    def _check_invariants(
        rows: list[SquadRollupRow],
        expected_damage: int,
        expected_healing: int,
        expected_strip: int,
        expected_hits: int,
    ) -> None:
        """Raise ``ValueError`` if any cross-field invariant is violated."""
        actual_damage = sum(r.total_damage for r in rows)
        if actual_damage != expected_damage:
            msg = (
                f"sum of row.total_damage ({actual_damage}) "
                f"!= sum of event.damage ({expected_damage})"
            )
            raise ValueError(msg)
        actual_healing = sum(r.total_healing for r in rows)
        if actual_healing != expected_healing:
            msg = (
                f"sum of row.total_healing ({actual_healing}) "
                f"!= sum of event.healing ({expected_healing})"
            )
            raise ValueError(msg)
        actual_strip = sum(r.total_buff_removal for r in rows)
        if actual_strip != expected_strip:
            msg = (
                f"sum of row.total_buff_removal ({actual_strip}) "
                f"!= sum of event.buff_removal ({expected_strip})"
            )
            raise ValueError(msg)
        actual_hits = sum(r.hit_count for r in rows)
        if actual_hits != expected_hits:
            msg = (
                f"sum of row.hit_count ({actual_hits}) "
                f"!= total events across streams ({expected_hits})"
            )
            raise ValueError(msg)
        # Cross-row ordering contract: descending total_damage with
        # ascending subgroup tie-break. ``pairwise`` is the canonical
        # adjacent-pair idiom (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.total_damage < curr.total_damage:
                msg = (
                    f"rows not ordered by (total_damage DESC, subgroup ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if prev.total_damage == curr.total_damage and prev.subgroup >= curr.subgroup:
                msg = f"tie on total_damage not broken by subgroup ASC: {prev!r} then {curr!r}"
                raise ValueError(msg)


__all__ = ["SquadRollupAggregator", "SquadRollupRow"]
