"""Per-skill roll-up -- the skill-by-skill impact view of a single fight.

Phase 7 v2 of analytics (v0.7.0 release). Walks the heterogeneous
:class:`Event` stream of one fight, buckets each event by the
``skill_id`` carried on the event record, and emits one
:class:`SkillUsageRow` per skill with the total damage / healing /
buff-removal the skill produced, plus the per-skill hit count.

Conventions
===========

- **Per-skill bucketing.** The key is the arcdps ``skill_id`` carried
  on every event. ``skill_id_to_name`` is the per-fight
  ``OrmFightSkill``-derived map of ``skill_id`` -> ``skill_name``;
  a skill not in the map (e.g. an event with an unknown skill id)
  is rendered as the empty string in the row -- we never synthesise
  a placeholder name.
- **All three event kinds contribute.** A single skill that
  dual-emits (heal + strip from the same cbtevent, corrupting /
  confusion) lands in BOTH ``total_healing`` AND
  ``total_buff_removal`` on the same row, plus a +1 in
  ``hit_count`` for each yielded event. Independent roll-ups on
  the same skill.
- **Deterministic ordering.** Rows sorted by
  ``(-total_damage, skill_id)`` -- highest damage first; ties
  broken by ascending ``skill_id`` (the natural arcdps order,
  mirrors the :class:`~gw2_analytics.target_dps.TargetDpsAggregator`
  sort contract).
- **No defaults invented.** Empty input yields ``[]``; we never
  synthesise a placeholder row.
- **No duration.** This aggregator does not compute per-second
  rates (skills don't have a "duration" the way fights do). The
  ``hit_count`` field carries the per-skill event frequency
  instead.

Cross-field invariants (validated post-construction; violations
raise ``ValueError``):

- Sum of ``row.total_damage`` across all rows == sum of
  ``event.damage`` across input damage events (no event dropped,
  no double-counting). Same for healing / buff-removal.
- Sum of ``row.hit_count`` across all rows == total number of
  events across all three input streams.
- Rows monotonically non-increasing by ``total_damage``; ties
  broken by ascending ``skill_id``.

Forward compat
==============

The aggregator signature is the paired-streams form
(``Iterable[DamageEvent]`` + ``Iterable[HealingEvent]`` +
``Iterable[BuffRemovalEvent]`` + ``skill_id_to_name``) so a future
v0.8.0 release that swaps the synthetic ``Iterable[Event]`` input
for a parser-sourced stream changes only the upstream producer.
The aggregator body still reads only ``damage`` / ``healing`` /
``buff_removal`` / ``skill_id`` from each event.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from gw2_core import BuffRemovalEvent, DamageEvent, HealingEvent


class SkillUsageRow(BaseModel):
    """One roll-up row: hit count + total damage + total healing + total strip for one skill.

    ``skill_name`` is the per-fight ``OrmFightSkill.name``; the empty
    string is a valid value for skills whose name is unknown.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: int = Field(..., ge=0)
    skill_name: str = Field(default="", max_length=256)
    hit_count: int = Field(..., ge=0)
    total_damage: int = Field(..., ge=0)
    total_healing: int = Field(..., ge=0)
    total_buff_removal: int = Field(..., ge=0)


@dataclass(slots=True)
class _SkillStats:
    """Mutable accumulator for one skill's combat contribution."""

    damage: int = 0
    healing: int = 0
    strip: int = 0
    hits: int = 0


class SkillUsageAggregator:
    """Stateless aggregator: events + skill-name map -> per-skill roll-up rows.

    Instantiate once and reuse -- the class holds no state.

    This is the strict parallel of
    :class:`~gw2_analytics.target_dps.TargetDpsAggregator` /
    :class:`~gw2_analytics.target_healing.TargetHealingAggregator`
    in spirit (per-actor roll-up) but groups by ``skill_id`` rather
    than by ``target_agent_id``. The schema is a strict superset
    of the per-target trio: it carries the three totals +
    ``hit_count`` + ``skill_name`` so the UI can render a single
    panel per skill.
    """

    def aggregate(
        self,
        damage_events: Iterable[DamageEvent],
        healing_events: Iterable[HealingEvent],
        strip_events: Iterable[BuffRemovalEvent],
        skill_id_to_name: Mapping[int, str],
    ) -> list[SkillUsageRow]:
        """Compute the per-skill roll-up.

        ``skill_id_to_name`` is the per-fight ``OrmFightSkill``-derived
        map of ``skill_id`` -> ``skill_name`` (empty string when the
        skill name is unknown / unset). Events with unknown
        ``skill_id`` are rendered as ``skill_id == <raw>`` +
        ``skill_name == ""`` rather than dropped.
        """
        stats: dict[int, _SkillStats] = defaultdict(_SkillStats)

        for dmg_ev in damage_events:
            st = stats[dmg_ev.skill_id]
            st.damage += dmg_ev.damage
            st.hits += 1

        for heal_ev in healing_events:
            st = stats[heal_ev.skill_id]
            st.healing += heal_ev.healing
            st.hits += 1

        for strip_ev in strip_events:
            st = stats[strip_ev.skill_id]
            st.strip += strip_ev.buff_removal
            st.hits += 1

        # Derive the grand totals from the accumulated per-skill
        # stats rather than tracking them inside the hot loops. This
        # saves four integer additions per input event.
        grand_damage = sum(st.damage for st in stats.values())
        grand_healing = sum(st.healing for st in stats.values())
        grand_strip = sum(st.strip for st in stats.values())
        grand_hits = sum(st.hits for st in stats.values())

        rows = [
            SkillUsageRow(
                skill_id=skill_id,
                skill_name=skill_id_to_name.get(skill_id, ""),
                hit_count=st.hits,
                total_damage=st.damage,
                total_healing=st.healing,
                total_buff_removal=st.strip,
            )
            for skill_id, st in stats.items()
        ]
        # Sort: highest total_damage first; ties broken by ascending skill_id.
        rows.sort(key=lambda r: (-r.total_damage, r.skill_id))

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
        rows: list[SkillUsageRow],
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
        # ascending skill_id tie-break. ``pairwise`` is the canonical
        # adjacent-pair idiom (ruff RUF007).
        for prev, curr in pairwise(rows):
            if prev.total_damage < curr.total_damage:
                msg = (
                    f"rows not ordered by (total_damage DESC, skill_id ASC): {prev!r} then {curr!r}"
                )
                raise ValueError(msg)
            if prev.total_damage == curr.total_damage and prev.skill_id >= curr.skill_id:
                msg = f"tie on total_damage not broken by skill_id ASC: {prev!r} then {curr!r}"
                raise ValueError(msg)


__all__ = ["SkillUsageAggregator", "SkillUsageRow"]
