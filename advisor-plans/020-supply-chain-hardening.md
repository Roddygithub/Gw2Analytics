# Plan 020 — Supply-chain hardening: remove `dangerouslyAllowAllBuilds`, sync react versions

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f0249ef..HEAD -- web/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f0249ef`, 2026-07-11

## Why this matters

Two supply-chain hygiene issues in `web/`:

1. `.npmrc` has `dangerouslyAllowAllBuilds=true` — every transitive npm dep can run arbitrary install scripts. A compromised dep executes code in CI and on every dev machine. The `pnpm audit` gate (plan 009) catches known CVEs but not supply-chain attacks via install scripts.

2. `package.json` pins `react@19.2.7` and `react-dom@19.2.4` — different patch versions. React 19.2.x is semver-compatible, but mismatched pins signal sloppy version management and may trigger peer-dep warnings in certain tooling.

## Current state

```ini
# web/.npmrc:10
dangerouslyAllowAllBuilds=true
```

```json
// web/package.json:19-20
"react": "19.2.7",
"react-dom": "19.2.4",
```

```yaml
# web/pnpm-workspace.yaml:1-8
allowBuilds:
  esbuild: set this to true or false
  sharp: set this to true or false
verify-deps-before-run: false
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install | `pnpm install` | exit 0 |
| Typecheck | `pnpm typecheck` | exit 0, no errors |
| Test | `pnpm test:unit` | all pass |
| Audit | `pnpm audit` | exit 0 |

## Scope

**In scope**:
- `web/.npmrc`
- `web/package.json`
- `web/pnpm-workspace.yaml`

**Out of scope**:
- `apps/api/pyproject.toml`
- Gateway dependency changes

## Steps

### Step 1: Remove `dangerouslyAllowAllBuilds`, switch to explicit allowlist

Edit `web/.npmrc`:
- Remove `dangerouslyAllowAllBuilds=true`
- Add `onlyBuiltDependencies=esbuild,sharp` (pnpm 11 syntax)

Alternatively, add to `web/package.json`:
```json
"pnpm": {
  "onlyBuiltDependencies": ["esbuild", "sharp"]
}
```

(pnpm 11 supports both locations; check which syntax your pnpm version supports via `pnpm --version` and `pnpm help install`.)

**Verify**: `pnpm install --frozen-lockfile` → exit 0 (should not prompt for build approval)

### Step 2: Sync `react-dom` to match `react`

Edit `web/package.json`:
```json
"react-dom": "19.2.7"
```

**Verify**: `pnpm install` → lockfile updates; `pnpm typecheck` → exit 0; `pnpm test:unit` → all pass.

### Step 3: Clean up `pnpm-workspace.yaml`

Edit `web/pnpm-workspace.yaml`:
```yaml
# Remove allowBuilds block entirely (moved to .npmrc/package.json)
# Set verify-deps-before-run to true to catch lockfile drift
verify-deps-before-run: true
```

**Verify**: `pnpm install --frozen-lockfile` → exit 0 (lockfile is fresh)

## Test plan

No new tests needed. Regression gate:
- `pnpm typecheck` catches type errors
- `pnpm test:unit` catches runtime regressions
- `pnpm audit` confirms no new advisories

## Done criteria

- [ ] `pnpm install --frozen-lockfile` exits 0
- [ ] `pnpm typecheck` exits 0
- [ ] `pnpm test:unit` exits 0
- [ ] `grep -r "dangerouslyAllowAllBuilds" web/` returns no matches
- [ ] `grep '"react-dom"' web/package.json` shows `19.2.7`
- [ ] No files outside in-scope list are modified

## STOP conditions

Stop and report if:
- `pnpm install` fails with build-script approval prompt (pnpm version may use different config key; check `pnpm help install` for `onlyBuiltDependencies` syntax).
- `pnpm audit` shows HIGH/CRITICAL for `esbuild` or `sharp` (these are Next.js peer deps, can't be removed).

## Maintenance notes

When a new dependency needs build scripts, add it to `onlyBuiltDependencies` in `package.json`. The `pnpm audit` gate in CI ensures known-vulnerable deps are caught. The `verify-deps-before-run: true` catches lockfile drift.
