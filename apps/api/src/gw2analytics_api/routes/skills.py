"""GET /api/v1/skills -- expose the GW2 skills catalog to the frontend."""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from gw2_core import Profession
from gw2analytics_api.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

_SKILLS_DATA_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "data" / "gw2_skills.ndjson"
)


class SkillOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    name: str
    profession: str | None
    is_elite: bool
    skill_type: str
    icon_url: str | None
    description: str | None


def load_skills() -> dict[int, dict[str, Any]]:
    skills: dict[int, dict[str, Any]] = {}
    path = _SKILLS_DATA_PATH
    if not path.exists():
        return skills
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                skills[data["id"]] = data
            except (json.JSONDecodeError, ValueError):
                continue
    return skills


def _to_wire(entry: dict[str, Any]) -> SkillOut:
    raw_profession = entry.get("profession")
    profession: str | None = None
    if raw_profession is not None:
        if isinstance(raw_profession, int):
            with suppress(ValueError):
                profession = Profession(raw_profession).name
        else:
            profession = str(raw_profession)
    return SkillOut(
        id=entry["id"],
        name=entry["name"],
        profession=profession,
        is_elite=entry.get("is_elite", False),
        skill_type=entry.get("skill_type", "utility"),
        icon_url=entry.get("icon_url"),
        description=entry.get("description"),
    )


@router.get("", response_model=list[SkillOut])
@limiter.limit("30/minute")
async def list_skills(request: Request) -> list[SkillOut]:
    catalog: dict[int, dict[str, Any]] | None = getattr(request.app.state, "skill_catalog", None)
    if catalog is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "skills catalog not loaded",
                "error_code": "SKILLS_UNAVAILABLE",
            },
        )
    return [_to_wire(entry) for entry in catalog.values()]


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(skill_id: int, request: Request) -> SkillOut:
    catalog: dict[int, dict[str, Any]] | None = getattr(request.app.state, "skill_catalog", None)
    if catalog is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "skills catalog not loaded",
                "error_code": "SKILLS_UNAVAILABLE",
            },
        )
    entry = catalog.get(skill_id)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "detail": f"skill {skill_id} not found",
                "error_code": "SKILL_NOT_FOUND",
            },
        )
    return _to_wire(entry)


__all__ = ["_SKILLS_DATA_PATH", "SkillOut", "get_skill", "list_skills", "load_skills", "router"]
