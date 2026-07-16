"""Pydantic models for the GW2 skills catalog.

Schema reference: ``libs/gw2_core/src/gw2_core/models.py::Skill``
(the parser-side adapter layer writes the same ``id`` int that this
catalog enriches with human display names).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gw2_core import (
    Profession,
)  # re-exported via field_validator (SkillEntry._accept_profession_aliases)

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

    @field_validator("profession", mode="before")
    @classmethod
    def _accept_profession_aliases(cls, v: object) -> object:
        """Accept Profession (canonical), int (arcdps bytes), str (catalog fixture), or None.

        v0.10.26-pre: gw2_core.Profession is IntEnum, not StrEnum, so Pydantic
        v2's default validation ONLY accepts integer values. NDJSON fixtures
        ship human-readable profession names ("Elementalist", "Guardian").
        This validator resolves those to the matching IntEnum MEMBER NAME.
        Unknown strings raise ValueError so the catalog loader's
        ``except (json.JSONDecodeError, ValueError)`` can silently skip them
        with a logger WARNING.
        """
        if v is None or isinstance(v, Profession):
            return v
        if isinstance(v, bool):
            raise ValueError(f"profession must not be bool (got {v!r})")
        if isinstance(v, int):
            try:
                return Profession(v)
            except ValueError as e:
                raise ValueError(f"Unknown profession int: {v!r}") from e
        if isinstance(v, str):
            try:
                return Profession[v.upper()]
            except KeyError as e:
                raise ValueError(f"Unknown profession name: {v!r}") from e
        raise ValueError(
            f"profession must be Profession | int | str | None (got {type(v).__name__})"
        )


__all__ = ["SkillEntry", "SkillType"]
