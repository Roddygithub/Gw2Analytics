"""Pydantic models for GW2 combat data.

Phase 0 stub: only `Fight` identity + enums. Phase 1 will add
`Player`, `PlayerMetrics`, `BuffUptime`, `ConditionUptime`, etc.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Profession(StrEnum):
    """GW2 core professions (9 base classes)."""

    WARRIOR = "Warrior"
    GUARDIAN = "Guardian"
    REVENANT = "Revenant"
    THIEF = "Thief"
    ENGINEER = "Engineer"
    RANGER = "Ranger"
    ELEMENTALIST = "Elementalist"
    NECROMANCER = "Necromancer"
    MESMER = "Mesmer"


class GameType(StrEnum):
    """Combat context.

    Phase 0+1 only ever produce WVW. The enum is generalized so
    future analyzer ingests (PvE raids, PvP) don'ê require schema breakup.
    """

    WVW = "wvw"
    PVE = "pve"
    PVP = "pvp"


class Fight(BaseModel):
    """One combat encounter.

    Stub: only the identity fields. Phase 1 will add duration_ms,
    map_id, fight_participants (per-player metrics).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(..., description="Stable identifier (SHA-256 of the source blob).")
    started_at: datetime = Field(..., description="UTC timestamp at fight start.")
    game_type: GameType = Field(default=GameType.WVW)


__all__ = ["Fight", "GameType", "Profession"]
