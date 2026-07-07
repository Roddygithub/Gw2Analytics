# Plan 003 — Auto-regenerate `schema.d.ts` on `pnpm dev`

## Context

`web/scripts/dump_openapi.py` writes the FastAPI `app.openapi()` JSON to stdout; `pnpm generate:api` shells out to dump it + run `openapi-typescript` on the output + write `web/src/lib/api/schema.d.ts`. This codegen runs **manually** today.

**Gap:** developers who clone the repo + `pnpm dev` against a current API may have a stale or absent `schema.d.ts`, leading to type errors in `web/src/lib/api.ts` that don't match the gateway's actual response shapes. This becomes worse as the API evolves (e.g., a v0.8.x that adds a field) — the web app keeps using the old type until someone remembers to run `pnpm generate:api`.

This plan auto-regenerates the schema on every `pnpm dev` invocation.

## Goal

`pnpm dev` always regenerates `web/src/lib/api/schema.d.ts` before starting the Next.js dev server, so the web app is always typed against the current API surface — no manual `pnpm generate:api` step needed.

## Files in scope

- **Update:** `web/package.json` — change `"dev": "next dev"` to `"dev": "pnpm generate:api && next dev"` (or `"predev": "pnpm generate:api"`, depending on pnpm version support for `pre*` hooks).
- **No new files** required (the codegen is already wired; just needs to run automatically).

## Files explicitly out of scope

- `web/scripts/dump_openapi.py` — already correct
- `web/scripts/screenshots.mjs` — unrelated
- The web app's actual API consumption (`web/src/lib/api.ts`) — no runtime change needed

## Steps

1. **Read `web/package.json` to confirm the current `dev` script value.** (Earlier read showed: `"dev": "next dev"`.)
2. **Update the `dev` script to chain the codegen first:**
   ```json
   "dev": "pnpm generate:api && next dev"
   ```
   This way every `pnpm dev` invocation regenerates `schema.d.ts` BEFORE Next.js boots; the web app types see the current API surface from the first render.

3. **Verify the boot still works:**
   ```bash
   cd web
   pnpm dev  # → should: dump openapi, run openapi-typescript, write schema.d.ts, then start Next.js
   ```
   Expected: schema.d.ts is regenerated (timestamp updated); server starts on :3000 no errors. `pnpm typecheck` still passes.

4. **No CI changes needed** — this only affects `pnpm dev`. CI runs `pnpm build` + `pnpm typecheck` + `pnpm test:unit` which don't depend on auto-codegen.

## Test plan

- No new tests required. The existing `pnpm typecheck` is the safety net — if auto-codegen corrupts `schema.d.ts`, typecheck fails.
- Manual: confirm a developer who clones fresh + `pnpm dev` gets a fresh `schema.d.ts` without any prior `pnpm generate:api` invocation.

## Done criteria

- `pnpm dev` regenerates `schema.d.ts` deterministically (same content if the API hasn't changed; different content if it has).
- `pnpm typecheck` exits 0.
- `pnpm build` exits 0.
- The change is a 1-line package.json edit + a Conventional Commits entry.

## Maintenance note

- If `pnpm generate:api` ever becomes slow (>2s), consider adding it as a `predev` hook so error messages are visible BEFORE Next.js starts — but with current timing (sub-second), the inline `&&` chain is fine.
- If FastAPI ever ships a breaking OpenAPI change (rename a route), the first `pnpm dev` after the API update will produce a different `schema.d.ts` + potentially surface type errors in `web/src/lib/api.ts`. That's the desired outcome — fail loudly early.

## Escape hatch

If `pnpm generate:api` fails on first run (e.g., `dump_openapi.py` can't import the FastAPI app due to a missing env var), STOP — the error must be fixed in `dump_openapi.py`'s `_REQUIRED_ENV` list before chaining. Do not silently swallow the error.
