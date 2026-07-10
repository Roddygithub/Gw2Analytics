# Plan 028 — v0.9.8 CI workflow hardening

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — prod hardening pass
**Status:** pending
**Effort:** S
**Category:** infra hardening (CI security + reliability + supply chain)
**Files touched:** `.github/workflows/ci.yml` (modifications) + `.github/dependabot.yml` (NEW) + `apps/api/pyproject.toml` (add `pip-audit` dev dep) + `web/package.json` (add `audit` script) + `.github/CODEOWNERS` (NEW, optional)

## Problem

`.github/workflows/ci.yml` is the canonical CI pipeline (per
`README.md` `## CI/CD` + `CONTRIBUTING.md` `## Running CI locally`).
The current workflow has 7 hardening gaps:

1. **No `permissions:` block** — by default, GitHub grants
   `GITHUB_TOKEN` **write** access to the job. For a lint+test
   job that does not push to the repo, this is a supply-chain
   attack surface: a compromised `actions/checkout` or
   `pnpm install` step could push code to main. The fix is
   `permissions: { contents: read }` (or `permissions: read-all`
   for the minimum needed).
2. **No `timeout-minutes` on the job** — a hung step runs for
   6 hours (the GitHub default), burning CI minutes. The Playwright
   E2E suite is the longest step; it deserves an explicit
   timeout.
3. **No `pip-audit` / `pnpm audit`** — known-vulnerability scanning
   for Python + npm deps is absent. A dependency with a known
   CVE (e.g. `requests` with a CVE-2023-32681) is silently
   shipped.
4. **`concurrency.cancel-in-progress: true` cancels main pushes too**
   — a push to main that starts a run is cancelled by the next
   push. For production-validation runs (tag-triggered
   deployments, etc.) this is wrong. The fix is
   `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`.
5. **No Dependabot config** — Python + npm deps age silently. A
   `dependabot.yml` would create weekly PRs to bump deps.
6. **No `concurrency` group for the main branch** — multiple
   pushes to main (e.g. a force-push + a follow-up commit) can
   race. A `concurrency: group: ci-main-${{ github.sha }}` would
   cancel stale runs.
7. **No `actions/checkout@v4` with `persist-credentials: false`**
   — the default persists the GITHUB_TOKEN in `.git/config`,
   enabling a subsequent step to push to the repo. The fix is
   `persist-credentials: false` on the checkout step.

## Goals

- Set `permissions: { contents: read }` at the job level.
- Add `timeout-minutes: 30` to the job + `timeout-minutes` per-step
  for the long-running steps.
- Add a `pip-audit` step (via `uv run pip-audit`).
- Add a `pnpm audit` step (via `pnpm audit --prod --audit-level=high`).
- Restrict `cancel-in-progress` to PRs.
- Add `.github/dependabot.yml` for weekly Python + npm dep updates.
- Add `persist-credentials: false` to the checkout step.

## Non-goals

- Adding a `release-please` / `changesets` flow. The repo uses
  manual CHANGELOG + tag flow per the README; a future plan can
  automate it.
- Adding a `dependabot-auto-merge` workflow. The auto-merge
  requires GitHub branch protection + is a future hardening.
- Adding `cargo-audit` / `bundle-audit` (no Rust / no Ruby in the
  stack).
- Switching from `ubuntu-latest` to a self-hosted runner. The
  default runner is fine for the current suite size.

## Implementation

### File: `.github/workflows/ci.yml`

Add the hardening changes below. The diff is additive (new steps
+ new top-level keys) + 1 modification to the `concurrency` block
+ 1 modification to the `actions/checkout@v4` step + 1 new
`permissions:` block at the job level.

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

# Cancel in-progress runs ONLY on PRs. Main pushes are
# production-validation runs and should not be cancelled by
# a subsequent push.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  lint-and-test:
    name: Lint + test (Python 3.12 + web)
    runs-on: ubuntu-latest
    # 30-minute hard timeout. The full suite (lint + mypy + pytest +
    # typecheck + vitest + playwright) takes ~10-15 min on the
    # default runner; 30 min gives 2x headroom.
    timeout-minutes: 30

    # Read-only token by default. The `actions/upload-artifact@v4`
    # step needs `id-token: write`? No — it uses the default
    # `GITHUB_TOKEN` which has `repo: read` for uploading
    # artifacts. The `contents: read` permission is the minimum
    # for the job.
    permissions:
      contents: read

    # ... (services: postgres block unchanged) ...

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          # Do NOT persist the GITHUB_TOKEN in .git/config. A
          # subsequent malicious step could `git push` to the
          # repo. The `actions/upload-artifact` step uses its
          # own auth path.
          persist-credentials: false

      # ... (uv install + sync + ruff + mypy steps unchanged) ...

      # ----------------------------------------------------------------
      # pip-audit: known-vulnerability scan for Python deps
      # ----------------------------------------------------------------
      # `uv run pip-audit` resolves the same dep graph `uv sync`
      # uses (via the `uv.lock`), so the scan is the production
      # truth (not the source-of-truth-only). Fails the build on
      # any HIGH or CRITICAL CVE.
      - name: pip-audit (Python deps)
        run: uv run pip-audit --strict
        timeout-minutes: 5

      # ... (health probe baseline + pytest + health gate unchanged) ...

      # ... (pnpm + node setup unchanged) ...

      # ... (pnpm install unchanged) ...

      # ----------------------------------------------------------------
      # pnpm audit: known-vulnerability scan for npm deps
      # ----------------------------------------------------------------
      # `pnpm audit --prod` skips dev-dep vulns (the build is the
      # production truth). `--audit-level=high` fails only on
      # HIGH or CRITICAL CVEs (so a new MED vuln in a dev-dep
      # doesn't break the build; Dependabot creates the PR).
      - name: pnpm audit (web deps)
        working-directory: web
        run: pnpm audit --prod --audit-level=high
        timeout-minutes: 3

      # ... (openapi dump + regenerate + drift gate + tsc unchanged) ...

      # ----------------------------------------------------------------
      # Web unit tests (vitest) — explicit timeout
      # ----------------------------------------------------------------
      - name: Web unit tests (vitest)
        working-directory: web
        run: pnpm exec vitest run --reporter=verbose
        timeout-minutes: 5

      # ----------------------------------------------------------------
      # Playwright E2E — explicit 20-minute timeout
      # ----------------------------------------------------------------
      # The full Playwright suite (16 specs + visual-regression)
      # takes ~5-8 min on the default runner; 20 min gives 3x
      # headroom for the `--with-deps` install + browser boot.
      - name: Install Playwright chromium
        working-directory: web
        run: pnpm exec playwright install --with-deps chromium
        timeout-minutes: 5

      - name: Playwright E2E tests
        working-directory: web
        run: pnpm exec playwright test
        timeout-minutes: 20

      # ... (upload artifacts unchanged) ...

      # ----------------------------------------------------------------
      # Visual regression e2e (PR only) — explicit timeout
      # ----------------------------------------------------------------
      - name: "Visual regression e2e (PR only)"
        if: github.event_name == 'pull_request'
        working-directory: web
        run: pnpm exec playwright test --project=visual-regression
        timeout-minutes: 10
```

### File: `.github/dependabot.yml` (NEW)

Add a Dependabot config that creates weekly PRs to bump Python +
npm deps + GitHub Actions versions:

```yaml
# Dependabot config: weekly PRs to bump Python + npm + GitHub
# Actions versions. The PRs trigger the same CI pipeline, so a
# bump that breaks the build fails its own PR.

version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "python"

  - package-ecosystem: "npm"
    directory: "/web"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "web"

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "ci"
```

### File: `apps/api/pyproject.toml`

Add `pip-audit` as a dev dependency so `uv run pip-audit` works:

```toml
[dependency-groups]
dev = [
    # ... existing dev deps ...
    "pip-audit>=2.7.0",
]
```

### File: `web/package.json`

Add an `audit` script for local parity with the CI step:

```json
{
  "scripts": {
    "audit": "pnpm audit --prod --audit-level=high",
    // ... existing scripts ...
  }
}
```

## Test plan

1. **`permissions: read-only`**: a malicious test step that tries
   `git push origin main` fails with `Permission denied`.
2. **`timeout-minutes: 30`**: a step that `sleep 1801` is killed
   at the 30-minute mark.
3. **`pip-audit`**: a known-vulnerable dep (e.g. a deliberately-
   downgraded `requests`) fails the build.
4. **`pnpm audit`**: a known-vulnerable npm dep (e.g. a
   deliberately-downgraded `lodash`) fails the build.
5. **`cancel-in-progress` PR-only**: a force-push to a PR cancels
   the previous PR run; a force-push to main does NOT cancel the
   previous main run.
6. **Dependabot**: a test repo with a stale dep gets a weekly PR
   within 7 days of the config landing.
7. **`persist-credentials: false`**: a subsequent step that
   `git push` fails with `could not read Username for
   'https://github.com'`.

## Acceptance criteria

- [ ] `.github/workflows/ci.yml` has the new `permissions: { contents: read }`
      block at the job level.
- [ ] The job has `timeout-minutes: 30`; long-running steps have
      per-step timeouts.
- [ ] `concurrency.cancel-in-progress` is restricted to PRs.
- [ ] `actions/checkout@v4` has `persist-credentials: false`.
- [ ] A new `pip-audit` step + a new `pnpm audit` step are present.
- [ ] `.github/dependabot.yml` exists with the Python + npm +
      GitHub Actions ecosystems configured for weekly updates.
- [ ] `apps/api/pyproject.toml` lists `pip-audit` as a dev dep.
- [ ] `web/package.json` has an `audit` script.
- [ ] No production code paths change.

## Out-of-scope / deferred

- **`dependabot-auto-merge` workflow** (auto-merge Dependabot PRs
  that pass CI): requires GitHub branch protection + is a future
  hardening. Tracked as a v0.9.9+ item.
- **`release-please` / `changesets`** for CHANGELOG automation:
  out of scope (manual CHANGELOG + tag flow is the production
  contract).
- **CodeQL / Snyk / Trivy for SAST**: out of scope for v0.9.8
  (the repo is small + well-tested; SAST is a future hardening).
- **Self-hosted runner** for the Playwright suite (saves ~3 min
  per run): out of scope (cost/ops tradeoff for a small repo).
- **Matrix strategy** for Python 3.12 + 3.13: out of scope
  (single Python version is the production contract).

## Maintenance notes

- **`pip-audit` API**: `pip-audit` v2.7+ supports the
  `--strict` flag (fails on any vuln, not just HIGH+). The plan
  uses `--strict`; an operator who wants HIGH+ only can drop
  the flag.
- **Dependabot labels**: the `dependencies`, `python`, `web`,
  `ci` labels must exist in the repo's label set. If they
  don't, the Dependabot config is silently ignored. A future
  plan can add a `.github/labels.yml` to seed the labels.
- **GitHub Actions version bumps**: Dependabot will PR bumps
  for `actions/checkout@v4` → `v5`, etc. The plan assumes
  v4 is the current target; v5 bumps are auto-PR'd by
  Dependabot after the config lands.
