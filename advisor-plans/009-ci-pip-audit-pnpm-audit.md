# advisor-plan 009 — CI pip-audit + pnpm audit dependencies

## Problem

`.github/workflows/ci.yml` has NO `pip-audit` step and NO `pnpm audit` step. The README §"Highlights" v0.10.0 advertises "CI security hardening (pip-audit + pnpm audit) + cluster-dep recovery" but the actual YAML has neither step. Known CVE/supply-chain surface for the monorepo: 5 backend deps + ~15 frontend deps. Dependabot already weekly-pulls new versions; the audit step is the SECOND SIGNAL — known-CVE lookup against the installed lockfile.

## Context

- `.github/workflows/ci.yml` — verified via `grep -nE 'audit|safety|trivy|codeql|snyk|pip-audit|pnpm audit' .github/workflows/ci.yml` → 0 matches.
- `README.md` §"Highlights" v0.10.0 line: "CI security hardening (pip-audit + pnpm audit) + cluster-dep recovery".
- `dependabot.yml` weekly pulls for uv + npm but does NOT flag known-CVE advisories.

## Approach

Add two new CI steps to the `lint-and-test` job, AFTER pytest + vitest but BEFORE the Playwright e2e step (which takes ~1 minute — keep audit OFF the critical path of failures). Use `pip-audit` for Python, `pnpm audit` for Node. Hard-fail on CRITICAL / HIGH advisories; soft-warn for MEDIUM.

## Files

**In scope**: `.github/workflows/ci.yml` only.
**Out of scope**: dependabot config (already weekly), per-package pyproject.toml files (NO dep changes here).

## Steps

1. Add a new step AFTER `Web unit tests (vitest)`, BEFORE `Install Playwright chromium`:
   ```yaml
   - name: pip-audit (Python deps, hard-fail on CRITICAL+HIGH)
     run: |
       uv run pip-audit --strict --vulnerability-service osv
   ```
2. Add a sibling step in the same job, `working-directory: web`:
   ```yaml
   - name: pnpm audit (Node deps, hard-fail on HIGH)
     working-directory: web
     run: |
       pnpm audit --audit-level=high
   ```
3. Add a soft-warn step at the END of the job for MEDIUM that DOES NOT fail the build (informational):
   ```yaml
   - name: pip-audit (MEDIUM warnings, soft-fail)
     if: always()
     continue-on-error: true
     run: uv run pip-audit --strict --vulnerability-service osv --ignore-vuln list-of-known-low-priority
   ```
4. Add a `[skip audit]` bypass via a `if:` conditional reading the commit message (`git log --pretty=%B -1 | grep -i '\[skip audit\]'`).

## Verification

- Local: `cd /home/roddy/Gw2Analytics && uv run pip-audit --strict --vulnerability-service osv` exits 0 (clean) or 1 (known CVE flagged). Same for `cd web && pnpm audit --audit-level=high`.
- `.github/workflows/ci.yml` greppable: `grep -nE 'name:.*pip-audit|name:.*pnpm audit' .github/workflows/ci.yml` → 3 matches (1 pip-audit hard, 1 pnpm audit hard, 1 pip-audit soft).
- Push the branch; observe the new step runs in CI; report exit codes in the PR description.

## Test plan

- The CI steps ARE the tests. PR-CI triggers both; `main` push triggers both.
- A weekly cron is NOT added in this plan — dependabot already weekly pulls; the audit steps re-scan on every PR.

## Done criteria

- Both hard-fail steps present in `.github/workflows/ci.yml`.
- `pnpm audit` step is `working-directory: web` (NOT repo root).
- `pip-audit` is invoked via `uv run` so it uses the workspace venv (not a fresh pip install).
- Soft-warn pip-audit step uses `continue-on-error: true`.

## Maintenance note

- `pip-audit` may flag transitive deps that the operator pinned below the safe ceiling (per README "cluster-dep recovery" § v0.10.8 pin lists: `redis>=5.0,<8`, `ag-grid-{community,react} ^34`, `jsdom ^25`, `@types/node ^20.19`). Soft-fail these via `--ignore-vuln GHSA-xxx` flags; document each ignore in a step-level comment.
- Don't change to `pnpm audit --all` (includes devDeps) — expanding the audit surface should be a separate plan with operator sign-off.

## Escape hatch

- If `pip-audit` install fails on Python 3.12 (compatibility issue as of writing), replace with `safety check --policy=pyproject.toml` or `osv-scanner --lockfile=uv.lock`. The CVEs flagged are the same surface.
- If a future pnpm upgrade makes `pnpm audit` exit non-zero on a known-good baseline (e.g. peer-dep noise on AG Grid), pin the audit step to a specific pnpm version via a separate setup step.
