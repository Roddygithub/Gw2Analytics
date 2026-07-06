"""Pydantic v2 schemas for the API surface (request + response).

These are HTTP-only contracts; they are NOT the domain models. Domain
lives in ``gw2_core``. We deliberately translate between the two at the
route boundary to keep persistence independent of API evolution.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    name: str
    profession: str
    elite_spec: str
    is_player: bool
    account_name: str | None = None
    subgroup: str | None = None


class FightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    build_version: str
    encounter_id: int
    agent_count: int
    started_at: datetime
    game_type: int
    agents: list[AgentOut] = []


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sha256: str
    original_filename: str
    size_bytes: int
    uploaded_at: datetime
    status: str
    error_message: str | None = None
    parser_version: str
    fight_id: str | None = None


class UploadCreatedResponse(BaseModel):
    """Returned from POST /uploads before parsing is finalised."""

    id: uuid.UUID
    sha256: str
    status: str
