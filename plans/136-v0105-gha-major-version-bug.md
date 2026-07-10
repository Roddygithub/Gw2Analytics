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
| #4 | astral-sh/setup-uv | `@v7` | `@v5` | Open (not yet — dependabot missed the v7 ceiling too) |
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

`astral-sh/setup-uv` ships major versions with breaking semantics:
the v3 → v7 jump was likely caused by dependabot reading the
action's `action.yml` `branding.iconUrl` or some metadata field
that does NOT correspond to the action ref tags. The `setup-uv`
v7 referenced in PR #4 is the action's *version* not its *git tag*;
dependabot confused the two.

For `actions/checkout`, `actions/setup-node`, `actions/upload-artifact`:
the GitHub-owned actions only publish heads up to v4. Dependabot
somehow computed a higher major from internal version metadata.
We suspect a dependabot ecosystem metadata bug.

## Long-term fix (Phase 2 v0.10.6)

Add an `ignore` block in `.github/dependabot.yml` for the GHA ecosystem:

```yaml
- package-ecosystem: "github-actions"
  directory: "/"
  schedule:
    interval: "weekly"
  groups:
    github-actions-minor-and-patch:
      patterns: ["*"]
      update-types: ["minor", "patch"]
  ignore:
    # Bug: dependabot emits invalid major versions for these actions.
    # Re-evaluate quarterly. See plans/136.
    - dependency-name: "actions/checkout"
      update-types: ["version-update:semver-major"]
    - dependency-name: "actions/upload-artifact"
      update-types: ["version-update:semver-major"]
    - dependency-name: "actions/setup-node"
      update-types: ["version-update:semver-major"]
    - dependency-name: "astral-sh/setup-uv"
      update-types: ["version-update:semver-major"]
    - dependency-name: "pnpm/action-setup"
      update-types: ["version-update:semver-major"]
```

This caps the auto-PR stream to `minor + patch` updates for GHA
actions only, where the tags are reliably published and CI-safe.

`uv` workspace + `npm` will continue receiving major PRs as those
package registries don't have this metadata bug.

## Tracking

- Dependabot will re-open closed PRs (#2/#3/#4/#5) on its next
  weekly cycle, this time with valid major tags.
- We will inspect the next cycle's PR diff BEFORE it has a chance
  to auto-merge, so we catch the next regression early.
- If dependabot emits invalid major tags again after the `ignore`
  block lands, escalate to disabling the `github-actions` ecosystem
  entirely and pinning versions in `ci.yml` manually.
