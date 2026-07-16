# Data directory

Holds the GW2 skills catalog seed data. Today: empty placeholder.

## How to populate

Coming in a downstream catalog-seed cycle. Plan candidates:
- scrape GW2 wiki category pages (skill list per profession)
- cross-reference dps.report / snowcrows / discretize databases
- reconcile with id from in-game API via gw2-api-client

Each seeded entry should be one JSON object per line (NDJSON format).
Schema is documented in :class:`gw2_skills.models.SkillEntry`.
