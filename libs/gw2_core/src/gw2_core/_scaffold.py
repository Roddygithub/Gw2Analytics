"""Wave 6 SCAFFOLD side-table defaults (PHASE 3).

Single source of truth for the Phase 6 v2 forward-compat STARTERS that
provide safe 0 / identity fallbacks for the side-table getter
plumbing wired through the per-player aggregators
(:mod:`gw2_analytics.player_damage` / `player_defense` /
`player_heal` / `player_boons`) + the apps/api glue layer
(:func:`gw2analytics_api.routes.fights.aggregators.aggregate_combat_readout`).

Convention
==========

Every function here is the **identity / zero fallback** for ONE
side-table getter that the future Phase 6 v2 parser-stream switch
will materialise. The canonical Contract: "if the future
side-table wiring fails, these defaults ensure the wire-shape
never crashes on a missing field."

The 5 canonical scaffolds (one per stub side-table):

- :func:`default_dps_split` --- ``(condi, power)`` per
  :class:`~gw2_core.DamageEvent`. Default: ``(0, damage)`` (the
  full hit is power under SCAFFOLD -- matches the pre-Phase-6-v2
  `condi_portion_getter is None` path on
  :func:`gw2_analytics.condi_power_split.split_condi_power`).
- :func:`default_barrier_portion_from_damage` --- barrier absorbed
  per :class:`~gw2_core.DamageEvent`. Default: ``0`` (the
  pre-Phase-6-v2 `barrier_portion_getter is None` path on
  :meth:`gw2_analytics.player_defense.PlayerDefenseAggregator.aggregate`).
- :func:`default_barrier_portion_from_healing` --- barrier applied
  per :class:`~gw2_core.HealingEvent`. Default: ``0`` (mirror of
  the damage-side SCAFFOLD).
- :func:`default_zero` --- identity-zero getter for any
  ``Callable[[X], int]`` shape; canonical SCAFFOLD for the strip
  count + cleance count stubs until Phase 6 v2 wires the
  `BuffRemovalEvent` / `ConditionRemoveEvent` cross-walk.
- :func:`default_full_power_split` --- power-only DPS split
  (``(0, damage)``) -- explicit alias for the now-canonical
  `default_dps_split` so callers that need the "power-only"
  semantics get a self-documenting symbol.

Design rationale (the WHY behind the SCAFFOLD pattern)
======================================================

The Phase 6 v2 forward-compat discipline is: plumb the
side-table getter through the aggregator signature, plumb the
NEW wire-shape column through the Pydantic schema, but provide
safe fallbacks that keep the v0.10.23 wire contract stable.

Pre-Phase-6-v2 streams (the canonical streamed today):
``dps_split_getter=None`` -> the aggregator initialises the
``dps_split_getter`` slot to :func:`default_dps_split` -> the row
``dps_power=0.0 + dps_condi=dps * duration_s`` etc collapse to
the canonical pre-Phase-6-v2 wire shape -- "everything is
power" semantics preserved, ZERO behavioural change for
existing fixtures.

Phase-6-v2 streams (the post-tour upgrade path):
``dps_split_getter=make_side_table_split_from_parser(...)`` ->
the same aggregator signature yields the
power+condi split values; ONE-line upgrade, no schema bump.

The pattern repeats for the barrier + cleance + strip getters;
the Wire-shape column + the aggregator column + the
`Callable | None` plumbing all land in the SAME vertical slice
so a future Phase 6 v2 PR is just "wire the parser callback".

Cross-references
================

- ``models.py::_EVENT_MAP`` + ``_dispatch_event`` -- the dispatch
  table that makes Event#13+ a 1-line addition (parallel SCAFFOLD
  pattern: forward-compat PLUMBING lands BEFORE the parser
  side-table is real).
- ``apps/api/src/gw2analytics_api/routes/fights/aggregators.py``
  -- the glue layer that threads these defaults through
  ``aggregate_combat_readout``.
- ``libs/gw2_analytics/src/gw2_analytics/condi_power_split.py``
  -- the canonical pre-Python-3.12 condi-power splitter that
  calibrates the new ``dps_split_getter`` shape against the
  existing ``condi_portion_getter`` contract.
"""

from __future__ import annotations

from typing import Any, Final

from gw2_core.models import DamageEvent, HealingEvent

# Canonical SCAFFOLD default: every damage hit's condi portion is
# 0; power = damage (the "everything is power" SCAFFOLD semantics
# that matches `condi_portion_getter is None` on
# :func:`split_condi_power`). Returned as ``(condi, power)`` -- the
# same tuple shape as ``split_condi_power`` so the value flows
# through the post-Phase-6-v2 getter interface unchanged.
_ZERO: Final[int] = 0


def default_dps_split(e: DamageEvent) -> tuple[int, int]:  # noqa: ARG001  -- SCAFFOLD-getter contract; ``e`` is required by the canonical ``Callable[[DamageEvent], tuple[int, int]]`` shape so the per-player aggregator can substitute this default without an if/else branch. The return is a constant ``(0, 0)`` so the parameter is unused at runtime.
    """SCAFFOLD: pre-Phase-6-v2 ``(condi, power)`` split per damage event.

    Returns ``(0, 0)`` -- the **wire-shape-fidelity** SCAFFOLD that
    preserves the pre-Phase-6-v2 wire shape ``dps_power=0.0 +
    dps_condi=0.0`` byte-for-byte. The canonical pre-Phase-6-v2
    streams do NOT carry per-event condi side tables, so the
    SCAFFOLD surfaces ``(0, 0)`` on both columns of the wire --
    the wire-schema contract requires BOTH fields to be ``0``
    when the parser hasn't yielded the side table. Phase 6 v2
    (the parser-stream switch + the per-event side table)
    replaces this default with the parser-supplied condi
    portion; the ``Callable | None`` plumbing on
    :meth:`PlayerDamageAggregator.aggregate` + the
    ``dps_power``/``dps_condi`` columns on
    :class:`PlayerDamageRow` absorb the swap with ZERO
    schema-mutation cost. The post-Phase-6-v2 explicit getter
    is responsible for returning ``(condi, power)`` tuples
    where ``condi + power == e.damage``; the aggregator does
    NOT enforce that conservation contract (dropped as part of
    Phase 3's wire-shape-fidelity fix to keep the SCAFFOLD
    path trivial).

    Parameters
    ----------
    e:
        The damage event to "split" -- the damage field is
        unused at the SCAFFOLD tier (the SCAFFOLD returns
        ``(0, 0)`` regardless of event.damage). The parameter
        is kept to satisfy the canonical
        ``Callable[[DamageEvent], tuple[int, int]]`` contract
        so the per-player aggregator's hot loop can substitute
        this default without an if/else branch.

    Returns
    -------
    ``(0, 0)`` -- wire-shape-fidelity invariant: SCAFFOLD
    ``dps_power + dps_condi == 0`` for every pre-Phase-6-v2
    stream (matches the pre-Phase-3 hardcoded ``0.0`` wire
    shape byte-for-byte).
    """
    return (_ZERO, _ZERO)


# Explicit alias: power-only DPS split is the canonical
# SCAFFOLD for the pre-Phase-6-v2 wire shape. Same implementation
# as :func:`default_dps_split`; exposed under a self-documenting
# name so the apps/api glue layer's per-bucket intent reads
# cleanly.
default_full_power_split = default_dps_split


def default_barrier_portion_from_damage(e: DamageEvent) -> int:  # noqa: ARG001  -- SCAFFOLD-getter contract; see ``default_dps_split`` for the rationale (per-player aggregator substitutes this default without an if/else branch).
    """SCAFFOLD: pre-Phase-6-v2 ``barrier absorbed`` per damage event.

    Returns ``0`` -- the canonical pre-Phase-6-v2 drop (the
    parser doesn't yet emit per-damage barrier portions; the
    side table that maps ``cbtevent`` -> ``barrier`` is
    Phase-6-v2-only). The ``barrier_portion_getter`` slot on
    :meth:`PlayerDefenseAggregator.aggregate` defaults to this
    lambda when ``None`` is passed -- mirroring the
    ``dps_split_getter`` SCAFFOLD pattern on the damage-side.

    Parameters
    ----------
    e:
        The damage event to query. The fields are unused at the
        SCAFFOLD tier; the future Phase-6-v2 implementation will
        read this event's id (``(time_ms, source_agent_id,
        skill_id)`` triple) against the parser-side table.

    Returns
    -------
    ``0`` -- invariant: a SCAFFOLD ``barrier_absorbed`` row
    matches ``sum(row.barrier_absorbed) == 0`` for every pre-
    Phase-6-v2 stream.
    """
    return _ZERO


def default_barrier_portion_from_healing(e: HealingEvent) -> int:  # noqa: ARG001  -- SCAFFOLD-getter contract; see ``default_dps_split`` for the rationale (per-player aggregator substitutes this default without an if/else branch).
    """SCAFFOLD: pre-Phase-6-v2 ``barrier applied`` per healing event.

    Mirror of :func:`default_barrier_portion_from_damage` for
    the heal-side stubs in :class:`PlayerHealRow` (``barrier_total``
    + ``barrier_ps`` columns). Default: ``0`` -- the parser doesn't
    yet carry a per-heal ``barrier`` field (the canonical
    :class:`HealingEvent` model has no ``barrier`` attribute); the
    side table that maps ``cbtevent`` -> ``barrier_for_heal`` is
    Phase-6-v2-only.

    Parameters
    ----------
    e:
        The healing event to query. The fields are unused at the
        SCAFFOLD tier.

    Returns
    -------
    ``0``
    """
    return _ZERO


def default_zero(_e: Any) -> int:
    """SCAFFOLD: identity-zero getter for any ``Callable[[X], int]`` shape.

    Universal zero-getter used for the strips + cleance + side-bucket
    SCAFFOLDs that don't need a per-event signature (the wave 6 SCAFFOLD
    branches are SCAFFOLD-ONLY stubs). Re-exported in the glue layer
    so the `BuffRemovalEvent`-driven `strips` count + the
    `ConditionRemoveEvent`-driven `cleanses` count both fall back to 0
    under pre-Phase-6-v2 streams.

    Parameters
    ----------
    _e:
        The event to "query". Unused -- the parameter is positional
        only so the callable satisfies the canonical
        ``Callable[[DamageEvent], int]`` / ``Callable[[HealingEvent], int]``
        / ``Callable[[BoonApplyEvent], int]`` etc contract shapes
        without per-kind overloads.

    Returns
    -------
    ``0``
    """
    return _ZERO


__all__ = [
    "default_barrier_portion_from_damage",
    "default_barrier_portion_from_healing",
    "default_dps_split",
    "default_full_power_split",
    "default_zero",
]
