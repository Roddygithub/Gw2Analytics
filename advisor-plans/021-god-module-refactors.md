# Plan 021 — Split 3 god modules: `services.py`, `api.ts`, `schemas.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f0249ef..HEAD -- apps/api/src/ web/src/lib/api.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 019 (mypy strict — catches refactor mistakes)
- **Category**: tech-debt
- **Planned at**: commit `f0249ef`, 2026-07-11

## Why this matters

Three files have grown well beyond the repo's median module size and mix unrelated concerns:

1. `services.py` (708 lines): orchestration + ORM write + event analytics + MinIO upload
2. `api.ts` (1007 lines): 12 API fetchers + all TypeScript interfaces + error handling + CSV download
3. `schemas.py` (764 lines): 20+ Pydantic response/request models for 7 route modules

This makes testing harder (god modules cannot be tested in isolation), creates single-file bottlenecks (any API change touches `api.ts`), and reduces tree-shaking (barrel imports from `api.ts` cannot eliminate unused exports).

## Current state

### `services.py` (apps/api/src/gw2analytics_api/services.py)

Three concerns in one file:
- `process_parse` (lines 58-138) — orchestration
- `_save_fight` (lines 141-290) — ORM write for fights/agents/skills
- `_persist_event_blob` (lines 359-458) — MinIO upload + summary materialization
- `_persist_player_summaries` (lines 461-708) — per-account rollup analytics

### `api.ts` (web/src/lib/api.ts)

Everything in one file:
- 12 `fetch*` functions
- All TypeScript interfaces (`FightRow`, `PlayerProfile`, `SkillUsageRow`, etc.)
- `ApiError` class + `formatApiError`
- `downloadCsv` helper
- All imports from `./env`

### `schemas.py` (apps/api/src/gw2analytics_api/schemas.py)

20+ classes: `AgentOut`, `SkillOut`, `FightOut`, `UploadOut`, `FightEventsSummaryOut`, `SquadRollupRowOut`, `PlayerListRowOut`, `PlayerProfileOut`, `PlayerTimelineOut`, `PerFightTimelineOut`, `PerPlayerTimelineOut`, `WebhookSubscriptionCreate`, `WebhookDeliveryOut`, `WebhookDeliveryReplayOut`, `EventBucketOut`, `SkillUsageRowOut`, `TargetDpsRowOut`, `TargetHealingRowOut`, `TargetBuffRemovalRowOut`, `PerPlayerTimelineSeriesOut`, `PerFightTimelinePointOut`, etc.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `uv sync` + `pnpm install` | exit 0 |
| Backend tests | `uv run pytest apps/api/tests/ -x -q` | all pass |
| Backend lint | `uv run ruff check apps/api/` | exit 0 |
| Backend typecheck | `uv run mypy apps/api/src/` | exit 0 |
| Frontend typecheck | `pnpm typecheck` | exit 0 |
| Frontend tests | `pnpm test:unit` | all pass |
| Frontend lint | `pnpm lint` | exit 0 |

## Scope

**In scope**:
- `apps/api/src/gw2analytics_api/services.py`
- `apps/api/src/gw2analytics_api/schemas.py`
- `web/src/lib/api.ts`
- NEW files created by the splits (see Steps)

**Out of scope**:
- Route handler logic changes
- Response shape changes
- Public API surface changes

## Steps

### Step 1: Split `services.py` → `services/` package

Replace `services.py` with a `services/` package:

```
services/
  __init__.py        ← re-exports public API: process_parse
  parse.py           ← process_parse (orchestration)
  fight_persistence.py  ← _save_fight, _sanitize_name, helpers
  player_summaries.py   ← _persist_player_summaries
  event_blob.py         ← _persist_event_blob
```

Move each top-level function to its module. Keep `_sanitize_name` in `fight_persistence.py` and import it where needed. Update imports in `routes/` and `workers/` to import from `services/` instead of `services`.

**Verify**: `uv run pytest apps/api/tests/ -x -q` → all pass

### Step 2: Split `schemas.py` → `schemas/` package

Replace `schemas.py` with a `schemas/` package:

```
schemas/
  __init__.py    ← re-exports all public classes (backward compat)
  fights.py     ← FightOut, AgentOut, SkillOut, EventBucketOut, etc.
  players.py    ← PlayerListRowOut, PlayerProfileOut, PlayerTimelineOut, etc.
  webhooks.py   ← WebhookSubscriptionCreate, WebhookDeliveryOut, etc.
  account.py    ← AccountEnrichedRow (if present)
  uploads.py    ← UploadOut, UploadCreatedResponse
```

Each route module imports only its domain's schemas (e.g. `routes/fights.py` imports `from gw2analytics_api.schemas.fights import ...`). The `__init__.py` barrel keeps backward compat for any external importers.

**Verify**: `uv run pytest apps/api/tests/ -x -q` → all pass

### Step 3: Split `api.ts` → `api/` package

Replace `web/src/lib/api.ts` with `web/src/lib/api/` directory:

```
api/
  index.ts       ← re-exports public surface (backward compat)
  types.ts       ← all TypeScript interfaces (FightRow, PlayerProfile, etc.)
  errors.ts      ← ApiError class + formatApiError
  fights.ts      ← fetchFights, fetchFightEvents, fetchFightSquads, fetchFightSkills, fetchFightTimeline, fetchFightPlayerTimeline
  players.ts     ← fetchPlayers, fetchPlayerProfile, fetchPlayerTimeline, fetchPlayerCompareTimeline
  uploads.ts     ← fetchUpload, createUpload
  webhooks.ts    ← fetchWebhooks, createWebhook, revokeWebhook, replayDlq
  account.ts     ← resolveAccount
  csv.ts         ← downloadCsv, csvEscape
  env.ts         ← API_BASE_URL import (or keep as separate env.ts)
```

Update all ~22 import sites across `web/src/` to import from `@/lib/api` (the barrel) or specific sub-modules. The barrel index re-exports everything so existing imports keep working.

**Verify**: `pnpm typecheck` → exit 0; `pnpm test:unit` → all pass

## Test plan

No new tests needed — the existing test suite is the regression gate. Focus on:
- `uv run pytest apps/api/tests/ -x -q` (backend)
- `pnpm test:unit` (frontend)
- `pnpm typecheck` (frontend type safety)

## Done criteria

- [ ] `services.py` replaced with `services/` package; all imports updated
- [ ] `schemas.py` replaced with `schemas/` package; all imports updated
- [ ] `api.ts` replaced with `api/` directory; all ~22 import sites updated
- [ ] All backend and frontend tests pass
- [ ] `ruff check` and `mypy` pass
- [ ] `pnpm typecheck` passes
- [ ] No files outside in-scope list are modified

## STOP conditions

Stop and report if:
- A circular import emerges in the backend splits (check `import` chains).
- More than 30 import sites need updating in the frontend (indicates the barrel pattern won't scale).
- A route module requires schemas from multiple domains (cross-domain dependency — might need shared schemas).

## Maintenance notes

The `schemas/__init__.py` barrel provides backward compat. New route modules should import from the specific schema module. The `api/` barrel means existing component imports keep working. New API functions go in the domain-specific module.
