# Plan 026 — OpenAPI schema drift sync (CI gate blocker)

**Stamped at:** `5cfd962` (origin/main HEAD at audit time)
**Severity:** HIGH (CI gate blocker)
**Category:** CI, DX
**Addresses finding:** `apps/web/src/lib/api/schema.d.ts` last modified 2026-07-09; PR 3.2 (commit `5cfd962`) changed the `GET /api/v1/fights` wire shape from a bare `list[FightOut]` to the new `FightsPageOut` object wrapper. The v0.9.1 plan-008 `Detect API client drift` CI step (`git diff --exit-code -- web/src/lib/api/schema.d.ts`) will fail on the next CI run unless the schema is regenerated.

---

## Finding

Evidence:

```
$ stat web/src/lib/api/schema.d.ts | grep Modify
Modify: 2026-07-09 ...

$ git log --oneline -1 5cfd962
5cfd962 refactor(api): A2 PR 3.2 -- FightsPageOut wrapper for GET /api/v1/fights
```

PR 3.2 changed the response shape of `GET /api/v1/fights` from `list[FightOut]` to `FightsPageOut` (an object wrapper with `fights: list[FightOut]`, `total: int`, `limit: int`, `offset: int`). The TypeScript schema contract (`web/src/lib/api/schema.d.ts`) still reflects the old bare-list shape. The CI `Detect API client drift` step will fail on the next push.

### Why this is a CI gate blocker

The `lint-and-test` workflow runs `git diff --exit-code -- web/src/lib/api/schema.d.ts` after `pnpm generate:api`. If the committed file differs from the regenerated output, the step exits non-zero and blocks the PR. Every future push to `main` will fail until this is resolved.

---

## Fix

### Step 1 — Regenerate the schema

```bash
cd /home/roddy/Gw2Analytics/web && pnpm generate:api
```

This runs `uv run python scripts/dump_openapi.py > openapi.json` then `pnpm exec openapi-typescript openapi.json -o ./src/lib/api/schema.d.ts` then removes `openapi.json`.

### Step 2 — Commit the regenerated file

```bash
git add web/src/lib/api/schema.d.ts
git commit -m "fix(web): regenerate OpenAPI schema.d.ts after FightsPageOut (plan 026)"
```

Single atomic commit. The regenerated file is the ONLY change.

---

## Tests

- `cd web && pnpm generate:api && git diff --exit-code -- src/lib/api/schema.d.ts` — exits 0 (no further drift).
- `cd web && pnpm typecheck` — TypeScript compiles with the new schema shapes.
- `cd web && pnpm vitest run` — no regressions from the schema change.

---

## Rejected alternatives

- **Skip the regen and accept the drift gate failure**: the v0.9.1 plan-008 work was deliberate — the gate is the operator's defense against silent schema drift. Bypassing it would unwind the entire v0.9.1 hardening posture.
- **Revert PR 3.2 (FightsPageOut) to unblock the gate**: the wrapper is the architecturally correct shape; reverting it would unwind the deferred closing piece of plan 021.
- **Add `schema.d.ts` to `.gitignore`**: defeats the purpose of the drift gate — the committed file IS the contract.

---

## Dependency graph

- **Standalone.** No plan depends on this one; this plan doesn't depend on any.

---

## Notes for executors

- This is the most-urgent CI gate blocker. Ship IMMEDIATELY.
- The `pnpm generate:api` script requires `uv` (Python) + `openapi-typescript` (pnpm) to be installed. Run `uv sync` and `cd web && pnpm install` first if needed.
- The regenerated file should be committed as-is. Do NOT hand-edit `schema.d.ts` — it is a generated artifact.
