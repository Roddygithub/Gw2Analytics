"""Stable internal data model for GW2 WvW analytics.

This package is the SINGLE SOURCE OF TRUTH for battle data shapes AND
for the cross-cutting shapes returned by the official GW2 v2 REST API
(``AccountInfo`` / ``WorldInfo`` / ``Population``). All other packages
(parser, analytics, api-client, frontend) consume these models. It
MUST NOT import anyone else.
"""

from __future__ import annotations

from gw2_core.models import (
    AccountInfo,
    Agent,
    BaseEvent,
    DamageEvent,
    EliteSpec,
    Event,
    EventType,
    EvtcHeader,
    Fight,
    GameType,
    HealingEvent,
    Population,
    Profession,
    Skill,
    WorldInfo,
)

__version__ = "0.3.0"

__all__ = [
    "AccountInfo",
    "Agent",
    "BaseEvent",
    "DamageEvent",
    "EliteSpec",
    "Event",
    "EventType",
    "EvtcHeader",
    "Fight",
    "GameType",
    "HealingEvent",
    "Population",
    "Profession",
    "Skill",
    "WorldInfo",
    "__version__",
]
