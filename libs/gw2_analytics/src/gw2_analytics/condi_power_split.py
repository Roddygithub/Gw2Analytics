"""Condi power split aggregator (v0.10.5 plan 135).

Pure-Python splitting of incoming damage events into a ``(condi, power)``
total. The split depends on the arcdps build date:
 - new builds (>= 20240501) carry the condi portion in the raw cbtevent
   ``buff_dmg`` field (NOT in the v2 :class:`DamageEvent` model). The
   split function accepts a ``condi_portion_getter`` callback that the
   caller wires up to whatever side-table it has access to (the parser
   keeps ``buff_dmg`` separately from the discriminated union stream);
 - old builds (< 20240501) encode the condi portion implicitly via the
   skill name (arcdps recognises Bleeding, Burning, Confusion, Poisoned,
   Torment). If the skill is in :data:`KNOWN_CONDI_NAMES`, the entire
   hit is condi; otherwise it is power.

Pure function on the events stream (no IO, no DB). Returns pydantic-friendly
int totals.

Historical note (plan 135 calibration): a public GW2 community reference
implementation previously shipped with ``>= 20260501`` (a typo -- the
actual cutoff is mid-2024). The threshold is documented as
``20240501`` here so the next implementer does not repeat the typo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from gw2_core import DamageEvent

#: Arcdps build date threshold at which the ``buff_dmg`` field carries the
#: condi portion of a hit. The cutoff is calibrated against a public GW2
#: community reference implementation (29 .zevtc corpus, 4.47M events,
#: calibration 2025-12). Do NOT change the threshold without re-running
#: the calibration.
_BUILD_DATE_GATE: str = "20240501"

#: Canonical condition names the arcdps skill table recognises as
#: conditions rather than direct skills. Stable since 2020; safe to
#: hardcode as a frozenset. An env-driven override
#: (``GW2_CONDITION_NAMES=foo:frozen,...``) is documented in plan 135
#: for forward-compat but not implemented here.
KNOWN_CONDI_NAMES: frozenset[str] = frozenset(
    {"Bleeding", "Burning", "Confusion", "Poisoned", "Torment"},
)


def split_condi_power(
    events: Iterable[DamageEvent],
    *,
    build_date: str,
    skill_name_getter: Callable[[int], str | None],
    condi_portion_getter: Callable[[DamageEvent], int] | None = None,
) -> tuple[int, int]:
    """Split a stream of :class:`DamageEvent` into ``(condi, power)`` totals.

    Parameters
    ----------
    events:
        The damage events to split. May be any iterable (list, tuple,
        generator, ...). Each event's ``damage`` field is the magnitude
        used for the split.
    build_date:
        The arcdps build date as a string, e.g. ``"20250925"``. The string
        is validated with :meth:`str.isdigit` so non-numeric beta codes
        fall through to the old-build branch rather than raising.
    skill_name_getter:
        Resolves a ``skill_id`` to its display name. Returns ``None``
        if the skill is unknown. Centralised so the live route can pass
        the same lookup the parser used (low coupling).
    condi_portion_getter:
        Optional. Resolves the condi portion (a.k.a. ``buff_dmg``) of a
        given damage event. Required for new-build branches (where
        condi is encoded directly in the raw cbtevent); ignored under
        the old-build branch. Returns 0 if the event has no condi
        component. NOT stored on the v2 :class:`DamageEvent` model --
        the parser keeps ``buff_dmg`` in a side table (the side table's
        shape is opaque from the lib's perspective, so the live route
        closes over whatever it has).

    Returns
    -------
    ``(condi_damage, power_damage)`` as ints. Both are non-negative.
    For every event with non-negative damage under the NEW-build path,
    ``condi + power == event.damage``. Under the OLD-build path, the
    entirety of either ``condi`` or ``power`` is attributed to one
    bucket per event (no split within a hit).
    """
    condi_total = 0
    power_total = 0
    is_new_build = build_date.isdigit() and int(build_date) >= int(_BUILD_DATE_GATE)
    # Cache skill-name lookups so repeated damage events with the
    # same skill_id only pay the getter cost once. The cache is
    # local to this call; ``None`` is a valid cached value.
    skill_name_cache: dict[int, str | None] = {}
    # Hoist the frozenset to a local variable so the hot loop pays
    # local-variable lookup cost instead of global lookup cost.
    known_condi_names = KNOWN_CONDI_NAMES

    if is_new_build:
        # Fast path: new builds encode condi directly in the raw
        # cbtevent's ``buff_dmg`` field. Branching outside the loop
        # avoids re-evaluating ``is_new_build`` on every event.
        if condi_portion_getter is None:
            for event in events:
                power_total += event.damage
        else:
            for event in events:
                magnitude = event.damage
                buff_dmg = condi_portion_getter(event)
                condi = min(magnitude, max(0, buff_dmg))
                condi_total += condi
                power_total += magnitude - condi
    else:
        # Slow path: old builds encode condi implicitly via skill
        # name. If the resolved skill is one of the canonical
        # condition names, the entire hit is condi; otherwise power.
        for event in events:
            magnitude = event.damage
            skill_id = event.skill_id
            if skill_id not in skill_name_cache:
                skill_name_cache[skill_id] = skill_name_getter(skill_id)
            skill_name = skill_name_cache[skill_id]
            if skill_name in known_condi_names:
                condi_total += magnitude
            else:
                power_total += magnitude

    return condi_total, power_total


__all__ = ["KNOWN_CONDI_NAMES", "split_condi_power"]
