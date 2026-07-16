"""Pydantic models for the GW2 skills catalog.

Schema reference: ``libs/gw2_core/src/gw2_core/models.py::Skill``
(the parser-side adapter layer writes the same ``id`` int that this
catalog enriches with human display names).
"""
from __future__ import annotations

from typing import Literal

from gw2_core import Profession
from pydantic import BaseModel, ConfigDict, Field

type SkillType = Literal[
    "weapon",
    "utility",
    "elite",
    "heal",
    "downed",
    "boon",
    "condition",
    "trait",
]


class SkillEntry(BaseModel):
    """One row in the GW2 skills catalog.

    Mirrors the parser-side :class:`gw2_core.Skill` in shape
    (``id`` int + ``name`` str) and extends it with the catalogue
    metadata (profession + is_elite + skill_type + icon + description).

    A ``Profession`` reference is imported from :mod:`gw2_core` so the
    catalog and the parser agree on the int enum values.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(
        ...,
        ge=0,
        description="arcdps skill id (matches fight.skills[i].id from the parser).",
    )
    name: str = Field(..., min_length=1, max_length=128, description="Human display name.")
    profession: Profession | None = Field(
        default=None,
        description="Owning profession -- None means the skill is multi-profession usable.",
    )
    is_elite: bool = Field(default=False)
    skill_type: SkillType = Field(default="utility")
    icon_url: str | None = Field(
        default=None,
        max_length=512,
        description="URL to the wiki icon (used by the web frontend).",
    )
    description: str | None = Field(default=None, max_length=512)


__all__ = ["SkillEntry", "SkillType"]
