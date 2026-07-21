# WAVE-8 B.1 — Skills DB source decision

**Date:** 2026-07-21
**Status:** Decided — Official GW2 v2 REST API chosen.

## Decision

The GW2 official v2 API (`api.guildwars2.com/v2/skills`) is the authoritative
Skills DB source for the `libs/gw2_skills` catalog.

## Alternatives considered

| Source | Pros | Cons | Verdict |
|--------|------|------|---------|
| **GW2 v2 API** | Authoritative (ArenaNet), free, stable, 3000+ skills, field-complete (id, name, icon, type, professions, facts) | ~15 requests per full refresh, needs periodic re-run (quarterly) | ✅ **Chosen** |
| wiki scrape | Human-curated descriptions, per-profession pages | Unstable HTML structure, no canonical IDs, scraping overhead | ❌ |
| dps.report / snowcrows | Raid/strike focused, curated | Incomplete (only meta skills), not canonical, stale risk | ❌ |
| Elite Insights dataset | Community-maintained, skill-ID-rich | C# source, not a data file, extraction cost | ❌ |

## Implementation plan (B.3–B.5)

1. **B.3 (`libs/gw2_skills/scripts/bootstrap_catalog.py`):** one-shot script that:
   - Fetches all skill IDs via `GET /v2/skills` (public, no auth)
   - Batch-fetches 200 skill objects per request via `?ids=...`
   - Maps API fields to `SkillEntry` Pydantic model
   - Writes `gw2_skills.ndjson` to the data directory
   - Rate-limit safety: 300ms delay between batch requests

2. **B.4:** Wire catalog loading into `apps/api` lifespan startup (import
   `SkillCatalog`, call `load_with_stats()`, expose freshness gauge).

3. **B.5:** `find_skill_by_id(id)` already implemented (`SkillCatalog.find_skill_by_id`).

## Maintenance cadence

Quarterly re-run after GW2 balance patches (per WAVE-8 plan §4 risk #1).
The `/healthz` freshness-days gauge surfaces staleness to operators.
