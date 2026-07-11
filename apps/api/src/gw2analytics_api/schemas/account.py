from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AccountEnrichedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    world_id: int
    world_name: str
    world_population: str
