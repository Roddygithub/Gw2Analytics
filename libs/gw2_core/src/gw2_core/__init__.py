"""Stable internal data model for GW2 combat events + REST API shapes.

This package is the SINGLE SOURCE OF TRUTH for battle data shapes (the
arcdps ``.zevtc`` discriminated union of ``DamageEvent`` /
``BuffRemovalEvent`` / ``HealingEvent``) AND for the cross-cutting
shapes returned by the official GW2 v2 REST API (``AccountInfo`` /
``WorldInfo`` / ``Population``). All other packages (parser,
analytics, api-client, frontend) consume these models. It MUST NOT
import anyone else.

Wave 6 SCAFFOLD surface
=======================

The 5 NEW package-level names exported from
:mod:`gw2_core._scaffold` (``default_dps_split`` /
``default_full_power_split`` / ``default_barrier_portion_from_damage`` /
``default_barrier_portion_from_healing`` / ``default_zero``) are the
single source of truth for the Phase 6 v2 SCAFFOLD-getter
defaults. They are re-exported at the package level so the
per-player aggregators (in :mod:`gw2_analytics.player_damage` /
``player_heal`` / ``player_boons``) can import them with the
canonical ``from gw2_core import default_dps_split`` path
without depending on a leaky private module import.

The SCAFFOLD-getter pattern is documented inline on each
function in :mod:`gw2_core._scaffold`.
"""

from __future__ import annotations

from gw2_core._scaffold import (
    default_barrier_portion_from_damage,
    default_barrier_portion_from_healing,
    default_dps_split,
    default_full_power_split,
    default_zero,
)
from gw2_core.models import (
    _EVENT_MAP,
    AccountInfo,
    Agent,
    BarrierEvent,
    BaseEvent,
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    BuffRemovalEvent,
    CCEvent,
    ConditionRemoveEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    DownEvent,
    EliteSpec,
    Event,
    EventType,
    EvtcHeader,
    Fight,
    GameType,
    HealingEvent,
    InterruptEvent,
    Population,
    Profession,
    Skill,
    StunBreakEvent,
    WorldInfo,
    _dispatch_event,
)

__version__ = "0.6.0"

# Wave 6 patch (Phase 3 close-out):
#   1. Re-export the 5 SCAFFOLD defaults from gw2_core._scaffold:
#      default_dps_split / default_full_power_split /
#      default_barrier_portion_from_damage /
#      default_barrier_portion_from_healing / default_zero.
#   2. Sort the 30 existing __all__ names with strict-ASCII ASC;
#      `_`-prefixed + dunder transition lives at position 28+.
# Order derivation: uppercase A-Z < `_` (0x5F) < `__` (0x5F, 0x5F) <
# `_dispatch_event` (`d` 0x64) < lowercase (`d` 0x64). Within the
# `_`-prefixed group: '_E...' < '__' < '_d...' (E=0x45 < `_`=0x5F
# < d=0x64).
__all__ = [
    "_EVENT_MAP",
    "AccountInfo",
    "Agent",
    "BarrierEvent",
    "BaseEvent",
    "BlockEvent",
    "BoonApplyEvent",
    "BuffApplyEvent",
    "BuffRemovalEvent",
    "CCEvent",
    "ConditionRemoveEvent",
    "DamageEvent",
    "DeathEvent",
    "DodgeEvent",
    "DownEvent",
    "EliteSpec",
    "Event",
    "EventType",
    "EvtcHeader",
    "Fight",
    "GameType",
    "HealingEvent",
    "InterruptEvent",
    "Population",
    "Profession",
    "Skill",
    "StunBreakEvent",
    "WorldInfo",
    "__version__",
    "_dispatch_event",
    "default_barrier_portion_from_damage",
    "default_barrier_portion_from_healing",
    "default_dps_split",
    "default_full_power_split",
    "default_zero",
]
