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
