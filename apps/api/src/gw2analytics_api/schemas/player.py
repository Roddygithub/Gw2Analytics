from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PlayerListRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_name: str
    name: str
    profession: str
    elite_spec: str
    fights_attended: int
    total_damage: int
    total_healing: int
    total_buff_removal: int


class PerFightBreakdownRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    started_at: datetime
    total_damage: int
    total_healing: int
    total_buff_removal: int
    detected_role: str | None = None
    detected_tags: list[str] | None = None
    # Phase 1 (AI-CONTINUATION-PLAN): boon uptimes + outgoing boons.
    might_uptime: float | None = None
    fury_uptime: float | None = None
    quickness_uptime: float | None = None
    alacrity_uptime: float | None = None
    protection_uptime: float | None = None
    regeneration_uptime: float | None = None
    vigor_uptime: float | None = None
    aegis_uptime: float | None = None
    stability_uptime: float | None = None
    swiftness_uptime: float | None = None
    resistance_uptime: float | None = None
    resolution_uptime: float | None = None
    superspeed_uptime: float | None = None
    stealth_uptime: float | None = None
    outgoing_might: int | None = None
    outgoing_fury: int | None = None
    outgoing_quickness: int | None = None
    outgoing_alacrity: int | None = None
    outgoing_protection: int | None = None
    outgoing_regeneration: int | None = None
    outgoing_vigor: int | None = None
    outgoing_aegis: int | None = None
    outgoing_stability: int | None = None
    outgoing_swiftness: int | None = None
    outgoing_resistance: int | None = None
    outgoing_resolution: int | None = None
    outgoing_superspeed: int | None = None
    outgoing_stealth: int | None = None


class PlayerTimelinePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fight_id: str
    started_at: datetime
    total_damage: int
    total_healing: int
    total_buff_removal: int


class PlayerTimelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_name: str
    total: int
    limit: int
    offset: int
    bucket: Literal["fight", "day"] = "fight"
    tz: str = "UTC"
    points: list[PlayerTimelinePointOut] = []


class PlayerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_name: str
    name: str
    profession: str
    elite_spec: str
    fights_attended: int
    total_damage: int
    total_healing: int
    total_buff_removal: int
    attended_fight_ids: list[str] = []
    per_fight_breakdown: list[PerFightBreakdownRowOut] = []
