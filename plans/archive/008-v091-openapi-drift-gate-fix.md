# 008-v091-openapi-drift-gate-fix

**Status**: DONE (shipped in v0.9.1 hardening slice)
**Date**: 2026-07-08 (executed as part of H1 + H2 followups)
**Drift-detection base**: `ef5e4f3`
**Addresses finding**: #5 — CI workflow claims schema drift detection (`git diff --exit-code` on `web/src/lib/api/schema.d.ts`) but the file is in `web/.gitignore`, so the gate never has anything to diff against.

## Context

The `apps/api` FastAPI app exposes an OpenAPI spec; the
`web/src/lib/api/schema.d.ts` file is the TypeScript contract consumed by the web
tier. The CI workflow (`.github/workflows/ci.yml`) at the `--exit-code` step claims
to enforce schema-drift detection after running `pnpm generate:api`. However
`web/.gitignore` excludes `web/src/lib/api/schema.d.ts` from version control, so
the file is regenerated locally by `pnpm generate:api` but never committed. The
CI gate never has anything to diff against, and a divergent API schema can
silently ship to production without triggering the gate.

## Files in scope

- `web/.gitignore` (remove the `src/lib/api/schema.d.ts` exclusion line ~31)
- `web/src/lib/api/schema.d.ts` (the baseline file — generated then committed in this PR)
- `.github/workflows/ci.yml` (the drift-gate step)
- `apps/api/dump_openapi.py` (read-only — the Python codegen script the workflow calls via Poetry/pnpm; verify it produces the right shape)
- `web/package.json` (read-only — verify a `generate:api` or `codegen:api` script exists)

## Files explicitly out of scope

- `apps/api/src/gw2analytics_api/main.py` (the FastAPI app itself — read-only)
- `apps/api/src/gw2analytics_api/routes/*` (any route should not change in this plan)
- `web/src/lib/api/client.ts` (the auto-generated TS client; the gate protects it but does not modify it)

## Steps

1. **Generate the baseline `schema.d.ts`**.
   - Verify command: `cd web && pnpm generate:api` (or whichever script key exists; check `web/package.json` for `"generate:api"` or `"codegen:api"`).
   - Expected: file `web/src/lib/api/schema.d.ts` is present with non-trivial size (>1 KB, depends on endpoint count).

2. **Capture the file\'s current state and remove the `.gitignore` exclusion**.
   - Verify command pre-edit: `grep -n 'schema.d.ts' web/.gitignore` (expected: hits the exclusion line).
   - Edit: remove the matching line via `str_replace` (the rest of `.gitignore` stays put).
   - Verify command post-edit: `grep -n 'schema.d.ts' web/.gitignore` (expected: empty / no hit).

3. **`git add` the baseline**.
   - Verify command: `git status --short web/src/lib/api/schema.d.ts` (expected: shows as `A web/src/lib/api/schema.d.ts`).

4. **Update the CI workflow**.
   - Find the existing `Detect API client drift`-shaped step (or the closest equivalent). Add / amend:
     ```yaml
     - name: Detect API client drift
       run: git diff --exit-code -- web/src/lib/api/schema.d.ts
     ```
   - Place AFTER `pnpm generate:api` (or whatever codegen step exists), BEFORE the `pnpm test` / `pytest` steps.
   - Verify command: `grep -B 1 -A 4 'Detect API client drift' .github/workflows/ci.yml` (expected: the new step is present and ordered correctly).

5. **Document the manual regeneration ritual** (no automated pre-commit hook in this plan — see escape hatch).
   - Add a one-line note to `CONTRIBUTING.md` (in a new `## Regenerating the web TypeScript client` subsection) explaining that any backend PR touching `apps/api/src/gw2analytics_api/routes/*` MUST regenerate + commit the updated `schema.d.ts`.
   - Verify command: `grep -B 1 -A 6 'Regenerating the web TypeScript client' CONTRIBUTING.md` (expected: section present).

## Test plan

- No new automated test required — the gate is enforced by the CI step itself.
- Manual smoke test (in the PR description):
  1. Edit `apps/api/src/gw2analytics_api/routes/health.py` to add a new response field.
  2. Run `cd web && pnpm generate:api`.
  3. Verify `web/src/lib/api/schema.d.ts` shows the new field.
  4. Commit the regenerated `schema.d.ts`.
  5. CI `git diff --exit-code -- web/src/lib/api/schema.d.ts` should pass because the committed baseline matches the regenerated content.

## Maintenance note

- The baseline is durable until a new endpoint is added or an existing one changes shape.
- The `apps/api/dump_openapi.py` (if present) is the operational entry point to update the baseline post-merge (most teams rely on `pnpm`, not raw Python).
- Any backend PR that touches `routes/*` MUST regenerate + commit the updated `schema.d.ts`. If a PR slips through with a stale schema, the CI gate will catch it on the next CI run after the gate starts working.
- Consider rotating the comment in `web/.gitignore` so future contributors see *why* the exclusion was removed (audit-trail / archeology).

## Escape hatches

- **STOP** if `pnpm generate:api` errors on a fresh install (deps missing). Verify by running `pnpm install --frozen-lockfile && pnpm generate:api` cleanly first; if Node-side deps are missing, escalate to a dep-bump plan.
- **STOP** if the regenerated `schema.d.ts` is unexpectedly large (>10 MB). Investigate whether some decorator is dumping the entire app object into the schema (e.g. FastAPI\'s `add_pydantic_response_models` recursing into circular refs).
- **STOP** if the drift gate fails on a legitimate cosmetic-only PR (e.g. comment / docstring change that somehow gets reflected in OpenAPI). Fix is to update the baseline manually; do NOT relax the gate. If the cosmetic change actually alters the schema, the gate is doing its job.
- **STOP** if a pre-commit hook integration is required (`pnpm run pre-commit` + `.pre-commit-config.yaml`). The hooks cross-process boundary to pnpm is brittle cross-platform — if requested, add a follow-up plan to wire the `generate:api` invocation to the existing `.pre-commit-config.yaml` framework.
