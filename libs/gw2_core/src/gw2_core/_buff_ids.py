"""GW2 buff/effect ID → category lookup table.

This module maps the well-known GW2 buff/effect IDs (as used by arcdps
in the ``ev.buff`` field of cbtevent records) to a semantic category
(boon, damage condition, or control condition).  The mapping is the
prerequisite for :class:`~gw2_core.ConditionRemoveEvent` dispatch:
when a :class:`~gw2_core.BuffRemovalEvent` carries a condition buff ID
(e.g. 736 = Bleeding), the aggregator layer can classify the removal
as a *cleanse* rather than a generic boon strip.

Source
======

The buff IDs are derived from the GW2 wiki's effect tables and verified
against the arcdps community's well-known mappings.  Every ID and its
category is documented inline.  Unknown / future buff IDs return
``None`` from :func:`classify_buff` so the caller can decide the
fallback policy (conservative default: treat as boon strip).

Maintenance
===========

When ArenaNet adds new boons or conditions in a balance patch, add the
new ID(s) to the appropriate category set below.  The table is
intentionally hand-maintained (not auto-fetched) because the GW2 API
does not expose a ``/v2/buffs`` endpoint — the skill catalog
(``libs/gw2_skills``) contains skill IDs, not buff/effect IDs, so the
classification cannot be derived automatically.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class BuffCategory(Enum):
    """Semantic category of a GW2 buff/effect."""

    BOON = "boon"
    CONDITION_DAMAGE = "condition_damage"
    CONDITION_CONTROL = "condition_control"


# ---------------------------------------------------------------------------
# Boons (positive effects shared to allies)
# ---------------------------------------------------------------------------

_BOON_IDS: Final[frozenset[int]] = frozenset(
    {
        740,  # Might (+power, +condi damage per stack)
        725,  # Fury (+20% critical chance)
        717,  # Protection (-33% incoming strike damage)
        718,  # Regeneration (heal over time)
        719,  # Swiftness (+33% movement speed)
        726,  # Vigor (+50% endurance regeneration)
        743,  # Aegis (block the next incoming attack)
        1122,  # Alacrity (+25% skill recharge rate)
        1187,  # Quickness (+50% action speed)
        873,  # Resistance (immune to non-damaging conditions)
        5974,  # Stability (immune to control effects; modern ID)
        30336,  # Superspeed (+100% movement speed, max 5s cap)
        13017,  # Stealth (invisible to enemies)
        26980,  # Resolution (-33% incoming condition damage; EoD 2022)
    }
)

# ---------------------------------------------------------------------------
# Damage conditions (deal damage over time or on trigger)
# ---------------------------------------------------------------------------

_CONDITION_DAMAGE_IDS: Final[frozenset[int]] = frozenset(
    {
        736,  # Bleeding (physical damage over time)
        737,  # Burning (fire damage over time, high stack cap)
        721,  # Poison (-33% incoming healing + damage over time)
        722,  # Confusion (damage on skill activation)
        723,  # Torment (damage over time, doubled while moving)
    }
)

# ---------------------------------------------------------------------------
# Control conditions (impair movement or actions, no direct damage)
# ---------------------------------------------------------------------------

_CONDITION_CONTROL_IDS: Final[frozenset[int]] = frozenset(
    {
        727,  # Chilled (-66% movement speed, -40% skill recharge)
        728,  # Blind (next outgoing attack misses)
        730,  # Weakness (-50% endurance regen, 50% chance to glance)
        731,  # Vulnerability (+1% incoming strike/condi damage per stack)
        732,  # Crippled (-50% movement speed)
        733,  # Fear (forced movement away from source; counts as CC)
        734,  # Taunt (forced movement toward source; counts as CC)
        735,  # Slow (-50% action speed)
        742,  # Immobilize (cannot move; can still act)
    }
)

#: Complete buff ID → category mapping.  Constructed once at import time
#: by merging the three frozensets into a single dict via dict.fromkeys.
#: O(1) lookup.  Unknown IDs return None from :func:`classify_buff`.
BUFF_CATEGORY_MAP: Final[dict[int, BuffCategory]] = {
    **dict.fromkeys(_BOON_IDS, BuffCategory.BOON),
    **dict.fromkeys(_CONDITION_DAMAGE_IDS, BuffCategory.CONDITION_DAMAGE),
    **dict.fromkeys(_CONDITION_CONTROL_IDS, BuffCategory.CONDITION_CONTROL),
}


def classify_buff(buff_id: int) -> BuffCategory | None:
    """Return the semantic category of a GW2 buff/effect ID.

    Returns ``None`` for unknown IDs so the caller can decide the
    fallback (conservative default: treat as a boon strip).

    >>> classify_buff(740)
    <BuffCategory.BOON: 'boon'>
    >>> classify_buff(736)
    <BuffCategory.CONDITION_DAMAGE: 'condition_damage'>
    >>> classify_buff(727)
    <BuffCategory.CONDITION_CONTROL: 'condition_control'>
    >>> classify_buff(999999) is None
    True
    """
    return BUFF_CATEGORY_MAP.get(buff_id)


def is_condition(buff_id: int) -> bool:
    """Return True if the buff ID is a condition (damage or control).

    Convenience predicate for aggregator-level cleanse classification:
    a ``BuffRemovalEvent`` whose ``skill_id`` is a condition buff ID
    should be counted as a cleanse rather than a strip.

    >>> is_condition(736)  # Bleeding
    True
    >>> is_condition(740)  # Might
    False
    """
    cat = BUFF_CATEGORY_MAP.get(buff_id)
    return cat in (BuffCategory.CONDITION_DAMAGE, BuffCategory.CONDITION_CONTROL)


__all__ = [
    "BUFF_CATEGORY_MAP",
    "BuffCategory",
    "classify_buff",
    "is_condition",
]
