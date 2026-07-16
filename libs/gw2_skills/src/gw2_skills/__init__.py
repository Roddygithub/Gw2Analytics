"""gw2-skills -- GW2 skills catalog library.

Public surface:
  - SkillEntry (Pydantic model: one skill row)
  - SkillCatalog (in-memory catalog with lookups)
  - find_skill_by_id (top-level convenience)
  - find_skills_by_profession (top-level convenience)

Empty-catalog invariant: a catalog with zero entries returns None /
[] for all lookup methods -- callers can rely on this without
wrapping their access in if/else.
"""
from gw2_skills.catalog import SkillCatalog, find_skill_by_id, find_skills_by_profession
from gw2_skills.models import SkillEntry, SkillType

__all__ = [
    "SkillCatalog",
    "SkillEntry",
    "SkillType",
    "find_skill_by_id",
    "find_skills_by_profession",
]
__version__ = "0.1.0"
