"""GET /api/v1/skills -- expose the GW2 skills catalog to the frontend.

The catalog (``libs.gw2_skills.catalog.SkillCatalog``) is eagerly loaded
at API startup via the lifespan handler in :mod:`main` and exposed on
``request.app.state.skill_catalog``. This route returns the catalog as
a JSON array of :class:`SkillOut`; clients build a client-side lookup
dictionary (one round-trip -> thousands of ``BuffApplyEvent`` rows
mapped to a UI-side Skill entity, NO N+1 amplification).

SCAFFOLD-zero detail: the catalog may be EMPTY if the startup load
returned no entries (e.g. NDJSON file shipped as the placeholder,
missing). The endpoint returns an empty array in that case, NOT a
5xx -- the empty-catalog invariant (libs/gw2_skills SLO-014) is part
of the public contract.

v0.10.26-pre wire contract: ``SkillOut.profession`` is a ``str | None``
(not IntEnum int value) so the auto-generated ``schema.d.ts`` matches
the string contract the frontend already expects for the NDJSON fixture.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from gw2_skills.catalog import SkillCatalog
from gw2_skills.models import SkillEntry
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


class SkillOut(BaseModel):
    """API wire shape of one catalog entry.

    Mirrors :class:`SkillEntry` minus the ``__init__``/``__contains__``
    overhead. The ``profession`` field is typed as ``str | None``; the
    IntEnum-to-string mapping happens in :func:`_to_wire` via
    ``entry.profession.name``. Pydantic v2 ``model_dump`` on a plain
    ``str | None`` field serialises the string as-is (no separate
    field_serializer needed -- removed in v0.10.26-pre review #7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    name: str
    profession: str | None
    is_elite: bool
    skill_type: str
    icon_url: str | None
    description: str | None


def _to_wire(entry: SkillEntry) -> SkillOut:
    """Construct a :class:`SkillOut` from a :class:`SkillEntry` catalog row.

    Profession is mapped via ``.name`` to a plain ``str`` -- the catalog
    stores IntEnum, but the wire format is string (per ``schema.d.ts``
    contract for the frontend's ``string | null`` expectation).
    """
    return SkillOut(
        id=entry.id,
        name=entry.name,
        profession=entry.profession.name if entry.profession is not None else None,
        is_elite=entry.is_elite,
        skill_type=entry.skill_type,
        icon_url=entry.icon_url,
        description=entry.description,
    )


@router.get("", response_model=list[SkillOut])
async def list_skills(request: Request) -> list[SkillOut]:
    """Return the FULL catalog. The frontend caches this once.

    Empty catalog (lifespan loaded 0 entries) returns ``[]`` per the
    public contract. App-level state missing (lifespan startup
    failure) returns ``503 SKILLS_UNAVAILABLE``.
    """
    catalog: SkillCatalog | None = getattr(request.app.state, "skill_catalog", None)
    if catalog is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "skills catalog not loaded",
                "error_code": "SKILLS_UNAVAILABLE",
            },
        )
    return [_to_wire(entry) for entry in catalog._skills_by_id.values()]


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(skill_id: int, request: Request) -> SkillOut:
    """Return ONE catalog entry by arcdps skill id. 404 on unknown id."""
    catalog: SkillCatalog | None = getattr(request.app.state, "skill_catalog", None)
    if catalog is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "skills catalog not loaded",
                "error_code": "SKILLS_UNAVAILABLE",
            },
        )
    entry = catalog.find_skill_by_id(skill_id)
    if entry is None:
        # v0.10.26-pre review #2: 404 detail is a DICT (matches the
        # 503 SKILLS_UNAVAILABLE contract + the frontend's fetchCached
        # ApiError.error_code lookup at web/src/lib/fetchCached.ts:60-73).
        # A flat-string detail would NOT propagate ``error_code`` to TS.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={
                "detail": f"skill {skill_id} not found",
                "error_code": "SKILL_NOT_FOUND",
            },
        )
    return _to_wire(entry)


__all__ = ["SkillOut", "get_skill", "list_skills", "router"]
