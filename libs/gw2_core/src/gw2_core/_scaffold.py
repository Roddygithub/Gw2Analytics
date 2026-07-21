"""Wave 6 legacy fallback defaults.

Single source of truth for the v0.11.0+ fallback getters that
provide safe 0 / identity defaults when the parser-side wiring
is not available (legacy pre-v0.12.x streams, or defensive
fallback when a getter factory returns ``None``).

These are threaded through the per-player aggregators
(:mod:`gw2_analytics.player_damage` / `player_defense` /
`player_heal` / `player_boons`) + the apps/api glue layer
(:func:`gw2analytics_api.routes.fights.aggregators.aggregate_combat_readout`).

Convention
==========

Every function here is the **identity / zero fallback** for ONE
side-table getter. The canonical contract: "if the parser-side
wiring is unavailable, these defaults keep the wire-shape stable."

The 5 canonical fallbacks:

- :func:`default_dps_split` --- ``(condi, power)`` per
  :class:`~gw2_core.DamageEvent`. Default: ``(0, 0)``.
- :func:`default_barrier_portion_from_damage` --- barrier absorbed
  per :class:`~gw2_core.DamageEvent`. Default: ``0``.
- :func:`default_barrier_portion_from_healing` --- barrier applied
  per :class:`~gw2_core.HealingEvent`. Default: ``0``.
- :func:`default_zero` --- identity-zero getter for any
  ``Callable[[X], int]`` shape.
- :func:`default_full_power_split` --- power-only DPS split
  (``(0, 0)``) -- explicit alias for
  :func:`default_dps_split`.

Design rationale
================

Phase 6 v2 shipped in v0.12.0-v0.12.3; the parser-side getters
are now live. These fallback functions remain as the defensive
default when constructing aggregators without parser-side
wiring (e.g. tests, replay, or legacy stream handlers).

Legacy (pre-v0.12.x) streams:
``dps_split_getter=None`` → the aggregator skips the split call
and ``dps_power=dps_condi=0.0`` is preserved byte-for-byte.

v0.12.1+ streams:
``dps_split_getter=make_side_table_split_from_parser(...)`` →
the aggregator yields real power+condi split values.

Cross-references
================

- ``models.py::_EVENT_MAP`` + ``_dispatch_event`` -- the dispatch
  table for parser events.
- ``apps/api/src/gw2analytics_api/routes/fights/aggregators.py``
  -- the glue layer that threads these defaults through
  ``aggregate_combat_readout``.
- ``libs/gw2_analytics/src/gw2_analytics/condi_power_split.py``
  -- the canonical condi-power splitter.
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


def default_dps_split(e: DamageEvent) -> tuple[int, int]:  # noqa: ARG001  -- Fallback getter contract; ``e`` is required by the canonical ``Callable[[DamageEvent], tuple[int, int]]`` shape so the per-player aggregator can substitute this default without an if/else branch. The return is a constant ``(0, 0)`` so the parameter is unused at runtime.
    """Legacy fallback: ``(condi, power)`` split per damage event.

    Returns ``(0, 0)`` -- the **wire-shape-fidelity** default that
    preserves the legacy wire shape ``dps_power=0.0 +
    dps_condi=0.0`` byte-for-byte. Used as the defensive fallback
    when no parser-side getter factory is available.

    v0.12.1+ replaces this default with the parser-supplied condi
    portion via the ``Callable | None`` plumbing on
    :meth:`PlayerDamageAggregator.aggregate`.

    Parameters
    ----------
    e:
        The damage event to "split" -- the damage field is
        unused (returns ``(0, 0)`` regardless). The parameter
        is kept to satisfy the canonical
        ``Callable[[DamageEvent], tuple[int, int]]`` contract
        so the per-player aggregator's hot loop can substitute
        this default without an if/else branch.

    Returns
    -------
    ``(0, 0)``
    """
    return (_ZERO, _ZERO)


# Explicit alias: power-only DPS split is the canonical
# SCAFFOLD for the pre-Phase-6-v2 wire shape. Same implementation
# as :func:`default_dps_split`; exposed under a self-documenting
# name so the apps/api glue layer's per-bucket intent reads
# cleanly.
default_full_power_split = default_dps_split


def default_barrier_portion_from_damage(e: DamageEvent) -> int:  # noqa: ARG001  -- Fallback getter contract; see ``default_dps_split`` for the rationale (per-player aggregator substitutes this default without an if/else branch).
    """Legacy fallback: ``barrier absorbed`` per damage event.

    Returns ``0`` -- the canonical legacy default. The
    ``barrier_portion_getter`` slot on
    :meth:`PlayerDefenseAggregator.aggregate` defaults to this
    lambda when ``None`` is passed.

    v0.12.1+ wires the parser-side barrier lookup directly.

    Parameters
    ----------
    e:
        The damage event to query. Fields are unused at the
        fallback tier.

    Returns
    -------
    ``0``
    """
    return _ZERO


def default_barrier_portion_from_healing(e: HealingEvent) -> int:  # noqa: ARG001  -- Fallback getter contract; see ``default_dps_split`` for the rationale (per-player aggregator substitutes this default without an if/else branch).
    """Legacy fallback: ``barrier applied`` per healing event.

    Mirror of :func:`default_barrier_portion_from_damage` for
    the heal-side columns in :class:`PlayerHealRow` (``barrier_total``
    + ``barrier_ps``). Default: ``0``.

    v0.12.1+ wires the parser-side barrier lookup directly.

    Parameters
    ----------
    e:
        The healing event to query. Fields are unused at the
        fallback tier.

    Returns
    -------
    ``0``
    """
    return _ZERO


def default_zero(_e: Any) -> int:
    """Legacy fallback: identity-zero getter for any ``Callable[[X], int]`` shape.

    Universal zero-getter used as the defensive default for strips,
    cleanses, and side-bucket getters. v0.12.1+ wires the
    parser-side streams directly, replacing this fallback.

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
