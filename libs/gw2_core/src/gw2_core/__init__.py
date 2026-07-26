"""Stable internal data model for GW2 combat events + REST API shapes.

This package is the SINGLE SOURCE OF TRUTH for battle data shapes (the
arcdps ``.zevtc`` discriminated union of ``DamageEvent`` /
``BuffRemovalEvent`` / ``HealingEvent``) AND for the cross-cutting
shapes returned by the official GW2 v2 REST API (``AccountInfo`` /
``WorldInfo`` / ``Population``). All other packages (parser,
analytics, api-client, frontend) consume these models. It MUST NOT
import anyone else.


"""

from __future__ import annotations

from gw2_core.models import (
    _EVENT_MAP,
    BUFF_CATEGORY_MAP,
    AccountInfo,
    ActivationType,
    Agent,
    BarrierEvent,
    BaseEvent,
    BlockEvent,
    BoonApplyEvent,
    BuffApplyEvent,
    BuffCategory,
    BuffRemovalEvent,
    CCEvent,
    ConditionRemoveEvent,
    DamageEvent,
    DeathEvent,
    DodgeEvent,
    DownEvent,
    EffectEvent,
    EliteSpec,
    Event,
    EventType,
    EvtcHeader,
    Fight,
    GameType,
    HealingEvent,
    InterruptEvent,
    Population,
    PositionEvent,
    Profession,
    Skill,
    SkillActivationEvent,
    StunBreakEvent,
    WeaponSwapEvent,
    WorldInfo,
    _dispatch_event,
    classify_buff,
    is_condition,
)

__version__ = "0.6.0"


__all__ = [
    "BUFF_CATEGORY_MAP",
    "_EVENT_MAP",
    "AccountInfo",
    "ActivationType",
    "Agent",
    "BarrierEvent",
    "BaseEvent",
    "BlockEvent",
    "BoonApplyEvent",
    "BuffApplyEvent",
    "BuffCategory",
    "BuffRemovalEvent",
    "CCEvent",
    "ConditionRemoveEvent",
    "DamageEvent",
    "DeathEvent",
    "DodgeEvent",
    "DownEvent",
    "EffectEvent",
    "EliteSpec",
    "Event",
    "EventType",
    "EvtcHeader",
    "Fight",
    "GameType",
    "HealingEvent",
    "InterruptEvent",
    "Population",
    "PositionEvent",
    "Profession",
    "Skill",
    "SkillActivationEvent",
    "StunBreakEvent",
    "WeaponSwapEvent",
    "WorldInfo",
    "__version__",
    "_dispatch_event",
    "classify_buff",
    "is_condition",
]
