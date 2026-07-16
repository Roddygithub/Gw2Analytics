# gw2-skills

GW2 skills catalog: lookup by skill_id, by profession, name resolution.

Used by WAVE-8 A.4 (BuffApplyEvent parser extension) to enrich parser-emitted `skill_id` integers with human-readable names.

## Surfaces

- `SkillEntry` — Pydantic v2 model for one skill row
- `SkillCatalog` — in-memory catalog with `find_skill_by_id()` + `find_skills_by_profession()` lookup
- `load(path)` — populates the catalog from an NDJSON file

## Run

```bash
uv pip install -e libs/gw2_skills
python -m gw2_skills.cli  # placeholder (no CLI yet)
```

## Status

The base library supports an empty catalog (no skills). Population comes from a downstream seed script (out of scope today).
