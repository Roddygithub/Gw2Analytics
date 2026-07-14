"""Skills DB catalog (Plan 045 v0.9.0 Combat readout step 2).

The canonical source-of-truth for GW2 skill/buff/condition names +
IDs + the boon-vs-condition disambiguation. Wave 5 SCAFFOLD ships
the package skeleton + the 6 buff-ID entries that were previously
hard-coded as module constants in
:mod:`libs.gw2_analytics.player_boons`. Tour 6 will move the
full aggregation over (the ``KNOW_BOON_IDS`` + the buff-ID
``_DEFAULT_*`` constants become ``gw2_skills.SKILL_CATALOG``
lookups).

Scope (Wave 5 SCAFFOLD only)
----------------------------

- The catalog Pydantic model (:class:`Skill`) + the catalog
  dict lookup (:data:`SKILL_CATALOG` keyed on ``skill_id``).
- The 6 boon seed entries (replicated verbatim from
  :mod:`libs.gw2_analytics.player_boons` -- the same 6 IDs
  calibrated against Elemental Insight's ``Buff`` enum + GW2
  wiki + arcdps' 2024-05-01 build).
- The :data:`KNOWN_BOONS` convenience lookup that mirrors the
  per-player aggregator's ``KNOWN_BOON_IDS`` pattern at the
  cross-package level.

Out-of-scope for Wave 5 SCAFFOLD
--------------------------------

- The full ~1000-entry skills DB (gw2efficiency / discretize
  dataset) -- awaits v0.11.0.
- Boon-vs-condition wire disambiguation -- awaits the Skills DB
  catalog filling out.
- Per-skill effect intensity / hybrid / trait-mapped boons --
  awaits Phase 6 v2 parser-stream yields.

Forward-compat
==============

The package is importable as ``gw2_skills`` from the apps/api
backend once added to the workspace ``pyproject.toml`` chain.
Tour 6 will refactor ``libs/gw2_analytics.player_boons`` + the
``planner_skill_usage`` modules to import from this catalog.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# Re-export the canonical re-exportable names so downstream importers
# ``from gw2_skills import KNOWN_BOONS, SKILL_CATALOG, Skill``
# resolve in alphabetical-deterministic order.
__all__ = [
    "KNOWN_BOONS",
    "SKILL_CATALOG",
    "Skill",
    "SkillKind",
]


# ---------------------------------------------------------------------------
# Skill model (the canonical Pydantic shape for every catalog entry).
# ---------------------------------------------------------------------------


class SkillKind(StrEnum):
    """Skill / buff / condition classification.

    Wave 5 SCAFFOLD ships 3 categories; Tour 6 (v0.11.0 skills DB catalog)
    may extend to ``TRAIT`` / ``HYBRID`` / ``NPC_ONLY``. The cross-cutting
    classification (boon vs condition vs effect) is the canonical
    boon-vs-condition wire-distinction that the parser-stream switch +
    the Skills DB catalog unblock (per design doc §9 step 2 +
    ``advisor-plans/026-phase-9-conditions.md``).
    """

    BOON = "boon"
    CONDITION = "condition"
    EFFECT = "effect"


class Skill(BaseModel):
    """One canonical catalog entry.

    Attributes
    ----------
    skill_id:
        The GW2 buff / skill / condition ID (PK into the catalog).
        Stable since the arcdps 2024-05-01 build.
    name:
        Human-readable display name matching the GW2 wiki
        ``APIv2`` ``skills`` endpoint.
    kind:
        The classification (BOON / CONDITION / EFFECT; see
        :class:`SkillKind` for the enum).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: int = Field(..., ge=0)
    name: str = Field(..., min_length=1, max_length=128)
    kind: SkillKind


# ---------------------------------------------------------------------------
# Catalog constants (Wave 5 SCAFFOLD -- 6 buff-ID entries replicated
# from libs/gw2_analytics.player_boons; v0.11.0 fills out the full
# ~1000-entry catalog).
# ---------------------------------------------------------------------------


_STABILITY_BUFF_ID: Final[int] = 1122
_ALACRITY_BUFF_ID: Final[int] = 30328
_RESISTANCE_BUFF_ID: Final[int] = 894
_AEGIS_BUFF_ID: Final[int] = 743
_SUPERSPEED_BUFF_ID: Final[int] = 597
_STEALTH_BUFF_ID: Final[int] = 1305

#: The canonical 6-entry catalog SCAFFOLD (wave 5). Tour 6 (v0.11.0)
#: will replace with the full ~1000-entry catalog sourced from
#: gw2efficiency / discretize datasets. Mid-tour, the per-player
#: aggregators in :mod:`libs.gw2_analytics.player_boons` import from
#: this constant so the bookkeeping is centralised.
SKILL_CATALOG: Final[dict[int, Skill]] = {
    _STABILITY_BUFF_ID: Skill(
        skill_id=_STABILITY_BUFF_ID,
        name="Stability",
        kind=SkillKind.BOON,
    ),
    _ALACRITY_BUFF_ID: Skill(
        skill_id=_ALACRITY_BUFF_ID,
        name="Alacrity",
        kind=SkillKind.BOON,
    ),
    _RESISTANCE_BUFF_ID: Skill(
        skill_id=_RESISTANCE_BUFF_ID,
        name="Resistance",
        kind=SkillKind.BOON,
    ),
    _AEGIS_BUFF_ID: Skill(
        skill_id=_AEGIS_BUFF_ID,
        name="Aegis",
        kind=SkillKind.BOON,
    ),
    _SUPERSPEED_BUFF_ID: Skill(
        skill_id=_SUPERSPEED_BUFF_ID,
        name="Superspeed",
        kind=SkillKind.BOON,
    ),
    _STEALTH_BUFF_ID: Skill(
        skill_id=_STEALTH_BUFF_ID,
        name="Stealth",
        kind=SkillKind.BOON,
    ),
}

#: The :data:`SKILL_CATALOG` keys (mirrors
#: :data:`libs.gw2_analytics.player_boons.KNOWN_BOON_IDS` for
#: cross-package lookup parity).
KNOWN_BOONS: Final[frozenset[int]] = frozenset(SKILL_CATALOG)
