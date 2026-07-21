# v0.10.5 — GHA major-version bug investigation

## Summary

In the v0.10.5 dep-cycle (Phase 2), dependabot opened 5 PRs bumping
GHA action versions to tags that **do not exist on the GitHub Marketplace**.
The invalid tags were merged into `main` (either via auto-merge or via
manual integration), causing the workflow's "Set up job" phase to fail
before any Python/Node work could run. CI result: `failure` for every
PR and the resulting push to `main`.

This document captures the investigation + the long-term fix.

## PRs that introduced invalid tags

| PR | Action | Bumped to | Latest on Marketplace | Status |
|---|---|---|---|---|
| #1 | actions/checkout | `@v7` | `@v4` | Auto-merged → commit `56c8378` |
| #2 | actions/upload-artifact | `@v7` | `@v4` | Open |
| #3 | pnpm/action-setup | `@v6` | `@v4` | Open |
| #4 | astral-sh/setup-uv | `@v7` | unknown (do not trust dependabot's metadata for this action) | Open — dependabot emitted a v7 ref the action does not ship |
| #5 | actions/setup-node | `@v6` | `@v4` | Open |

(PR #8 was a no-op since Phase 1A already absorbed the bump.)

## Why CI failed at "Set up job"

GitHub resolves the `uses: <action>@<tag>` ref BEFORE any step runs.
A missing major (e.g. `actions/checkout@v7`) yields a workflow-level
error:

```
Error: Unable to resolve action `actions/checkout@v7`, unable to find version `v7`
```

This causes:
1. The `actions/checkout` step itself fails.
2. Every downstream step (`Install uv`, `Set up Python`, `Ruff`, `Mypy`,
   `Playwright`, etc.) reports `skipped`.
3. The job is marked `failure`.

Local `uv run ruff` + `uv run mypy` pass cleanly because they bypass
the workflow entirely — a misleading signal that "tests are green"
when actually CI is broken at the infrastructure layer.

## Recovery applied (Phase 2)

1. `git reset --hard 88df40f && git push --force-with-lease origin main`
   — removed the manual integration of PRs #2/#3/#4/#5 from main.
2. `sed -i 's|actions/checkout@v7|actions/checkout@v4|g' .github/workflows/ci.yml`
   — fixed PR #1's auto-merged invalid bump.
3. Closing PRs #2/#3/#4/#5 with comment "invalid major version tag,
   dependabot will re-spin with a valid tag on the next cycle".

## Why dependabot picked the wrong tags

Not investigated end-to-end. The exact mechanism is not auditable
from inside dependabot logs, and a deep investigation is out of
scope for this fix (would require running dependabot standalone
with a controlled fixture repo, then filing an upstream ticket
with reproduction logs). The actionable conclusion is: **make the
dependabot integration human-in-the-loop for any change that
touches `.github/workflows/**`**, regardless of root cause.

## Long-term fix (Phase 2 v0.10.6)

Two complementary changes to `.github/dependabot.yml`:

### Change A — isolate `.github/workflows/**` from dependabot auto-merge

Dependabot does not expose a per-ecosystem `automerged: false` knob.
The only reliable way to force human review on `.github/workflows/**`
edits is one of the following GitHub-Actions-side mechanisms:

**A1.** Branch-protection rule on `main` requiring at least one
human `approval` review when the diff touches `.github/workflows/**`.
This works regardless of whether dependabot opened the PR.

**A2.** A `.github/dependabot-auto-merge.yml` workflow that ONLY
auto-merges dependabot PRs whose path filter EXCLUDES
`.github/**`. Set `paths-ignore` on the auto-merge workflow:

```yaml
name: Dependabot auto-merge
on: pull_request
jobs:
  dependabot-auto-merge:
    if: github.actor == 'dependabot[bot]'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Auto-merge
        run: gh pr merge --auto --squash "$PR_URL"
        env:
          PR_URL: ${{ github.event.pull_request.html_url }}
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

In this project's `.github/dependabot.yml` ecosystem block,
restrict auto-merge to non-workflow ecosystems (uv workspace, npm)
via the auto-merge workflow's `paths-ignore: ['.github/**']`. The
`github-actions` ecosystem PRs then fall through to manual review.

Either A1 or A2 (or both together) constitutes the real prevention.
`open-pull-requests-limit: N` is NOT a prevention — it only caps
the queue depth.

### Change B — cap major bumps via `ignore` blocks

As belt-and-braces, ignore major bumps for the specific actions
we know dependabot gets wrong. (`update-types` accepts
`major`/`minor`/`patch`/`digest`, NOT `version-update:semver-*` —
those are PR-title tokens only.)

```yaml
- package-ecosystem: "github-actions"
  directory: "/"
  # ... see Change A above
  ignore:
    # Bug: dependabot emits majors that don't exist on Marketplace.
    # Re-evaluate quarterly once the upstream bug is fixed.
    # See plans/136.
    - dependency-name: "actions/checkout"
      update-types: ["major"]
    - dependency-name: "actions/upload-artifact"
      update-types: ["major"]
    - dependency-name: "actions/setup-node"
      update-types: ["major"]
    - dependency-name: "astral-sh/setup-uv"
      update-types: ["major"]
    - dependency-name: "pnpm/action-setup"
      update-types: ["major"]
```

This caps GHA PRs to minor + patch — where the tag stream and
dependabot's metadata match reliably. Major bumps remain possible
via manual `git diff` + PR review.

`uv` workspace + `npm` ecosystems continue receiving major PRs
freely; those registries don't exhibit the same metadata-bug pattern.

## Tracking

- Dependabot will re-open any closed PRs on its next weekly cycle,
  this time hopefully with valid major tags.
- The Change A automation gate means each new GHA PR surfaces for
  human review before it can land, regardless of dependabot's
  metadata correctness.
- We will sample-inspect the next cycle's PR diff within 24h of
  the weekly run to confirm the ignore block + automation gate
  work as intended.

## Fallback

If dependabot emits invalid major tags AGAIN after the `ignore`
block + automation gate land:

1. Pin the affected action version in `.github/workflows/ci.yml`
   manually (`uses: actions/checkout@<sha>` style pin, NOT a tag).
2. Open a dependabot support ticket reporting the bug with our
   reproduction logs (the failing `##[error] Unable to resolve
   action 'actions/checkout@v7'` lines).
3. Consider replacing the dependabot GHA ecosystem with a manual
   weekly review of action releases from `astral-sh/`, `pnpm/`,
   `actions/` GitHub orgs.
