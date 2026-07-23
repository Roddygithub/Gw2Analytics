# DCO validation

This README describes how to validate the inline bash DCO check
(`.github/workflows/ci.yml` job `dco-check`) end-to-end.

## Quick validation (2 phases)

Execute each step manually from the repo root:

### Phase 1 — Unsigned commit (expect FAILURE)

```bash
git fetch origin main
git checkout -b test/dco-validation origin/main
git commit --allow-empty -m "test(dco): unsigned commit"
git push -u origin test/dco-validation
gh pr create --base main --head test/dco-validation \
  --title 'WIP: DCO check test (unsigned)' \
  --body 'Test PR — will be closed without merging'
# Wait for CI, then:
gh pr view --json statusCheckRollup --jq \
  '.statusCheckRollup[] | select(.name == "DCO check") | .conclusion'
# Expected: FAILURE
```

### Phase 2 — Signed commit (expect SUCCESS)

```bash
git commit --amend --allow-empty -s -m "test(dco): signed commit"
git push --force-with-lease origin test/dco-validation
# Wait for CI, then:
gh pr view --json statusCheckRollup --jq \
  '.statusCheckRollup[] | select(.name == "DCO check") | .conclusion'
# Expected: SUCCESS
```

### Cleanup

```bash
gh pr close --delete-branch
git checkout main
git branch -D test/dco-validation
```

## Notes

- The DCO check only runs on `pull_request` events (skipped on direct pushes
  to `main`).
- As of v0.15.2, `DCO check` is a required status check in the `main`
  ruleset (6 required checks total).
- The check is implemented as plain bash (`git log` + `grep`) with zero
  external action dependencies.

## Prerequisites

- `gh` CLI authenticated against `Roddygithub/Gw2Analytics`
- Git configured with `user.name` + `user.email`
- `jq` available
