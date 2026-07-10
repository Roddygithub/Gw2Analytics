# v0.10.6 — Dependabot integration test (post-A1 acceptance)

Compact checklist the user runs after applying `plans/137`'s
branch-protection rule (`gh api PUT .../branches/main/protection`)
manually. Verifies the 3 layered defenses (plans/136 Change A2 +
Change B + plans/137 Change A1) work end-to-end against a real
dependabot cycle.

## Prerequisites (all MUST be on `main`)

- [x] plans/136 A2: `.github/workflows/dependabot-auto-merge.yml`
      with `paths-ignore: ['.github/**']` (commit `b4b34f3`)
- [x] plans/136 B: `.github/dependabot.yml` `ignore:` blocks for
      5 stale GHA actions + `dependabot/fetch-metadata` (rounds 2/3/4)
- [x] plans/137 JSON body applied via `gh api PUT` (user did this)
- [x] `.github/CODEOWNERS` rule `.github/** @Roddygithub` merged
- [x] Port-5432 dev postgres standardized (commit on top of `aa812d7`)
- [x] pytest apps/api/tests runs cleanly with no DATABASE_URL override
      (post port-fix)

## Test scenarios (compact)

### Scenario 1 — patch bump on NON-action GHA

- [ ] Trigger a manual dependabot rebase on the uv workspace ecosystem:
      `gh workflow run dependabot-auto-merge.yml` (or push a no-op PR)
- [ ] Verify the workflow fires (PR is the trigger).
- [ ] Confirm `dependabot-auto-merge :: ecosystem=uv update-type=...`
      line appears in Actions log.
- [ ] PR lands on `main` automatically within ~3 minutes.

### Scenario 2 — workflow-touching PR (any source)

- [ ] Open a manual PR that touches `.github/workflows/ci.yml`
      (e.g. add a comment).
- [ ] Verify the dependabot-auto-merge workflow does NOT fire
      (paths-ignore excludes it).
- [ ] Verify CODEOWNERS flags the PR for `@Roddygithub` review.
- [ ] Verify the merge button is disabled until approval granted.

### Scenario 3 — major bump on a blacklisted action (operator-controllable)

- [ ] Open a hand-crafted branch that bumps `actions/checkout@v4`
      -> `actions/checkout@v8` in `.github/workflows/ci.yml`. Open
      a PR. Confirm the PR is allowed to be created (dependabot's
      `ignore:` filter only suppresses DEPENDABOT-emitted PRs; the
      `ignore` block does not block human-authored PRs).
- [ ] Confirm CODEOWNERS flags this PR for `@Roddygithub` review
      (the `.github/**` rule fires; the auto-merge workflow's
      paths-ignore also blocks auto-merge).

### Scenario 4 — observe next dependabot cycle

- [ ] Observe dependabot's weekly run on the github-actions
      ecosystem. Confirm NO dependabot PR is opened for:
      actions/checkout, actions/upload-artifact, actions/setup-node,
      astral-sh/setup-uv, pnpm/action-setup, dependabot/fetch-metadata
      (all 6 filtered by ignore: for the actions + the action
      itself). Depends on timing — record the date the cycle ran.
- [ ] Operator-controllable ALTERNATIVE: `gh workflow run
      dependabot-auto-merge.yml` does NOT trigger dependabot's
      cycle (dependabot has its own scheduler). The observation
      step is non-falsifiable on the day; record the timestamp so
      future post-mortems can correlate.

### Scenario 5 — fetch-metadata SHA pin operator-initiated update

- [ ] (operator-initiated.) Manually bump `dependabot/fetch-metadata@v2`
      to a fresh SHA via PR after upstream releases. Confirms the
      `[major, minor, patch]` ignore does NOT block human PRs (only
      dependabot PRs); the SHA pin lands via CODEOWNERS review + CI.

## Verification commands (for the user)

```bash
# Pull latest main + verify parity
git fetch origin main && git checkout main && git pull origin main
git log --oneline -10 | head -10
git show HEAD:.github/workflows/dependabot-auto-merge.yml | head -8

# Confirm CODEOWNERS rule applied
cat .github/CODEOWNERS

# Confirm branch protection state (should report non-null protection)
gh api repos/Roddygithub/Gw2Analytics/branches/main/protection \
  | python3 -m json.tool | head -20

# Confirm docker-compose runs on port 5432
docker compose up -d postgres
docker ps | grep gw2a-postgres

# Run the full pytest suite + the new dev port
uv run pytest apps/api/tests --no-header -q
```

## Acceptance bar

- Scenarios 1, 2, 3, 5 pass (operator-controllable inside one PR cycle).
- Scenario 4 is a post-cycle observation record (non-falsifiable on
  the day; track via timestamp).
- `pytest apps/api/tests` exits 0 with no env var overrides.
- `git log --oneline origin/main -1` matches local HEAD.
- Branch-protection `gh api` returns a non-null protection rule.

## Rollback (if something breaks)

1. **Layered defense rollback is independent per layer**:

   - **A2 + B layer** (file-based): revert the commits via
     `git revert <commit>` -- keeps CODEOWNERS + plans/137 intact.
   - **A1 layer** (branch-protection): delete via
     `gh api -X DELETE repos/.../branches/main/protection`.
   - **CODEOWNERS layer**: delete `.github/CODEOWNERS` file (no
     revert needed).

2. **Hard reset to known-good `9f70aaf`** (the post-port-fix HEAD
   that includes docker-compose port-5432 + CODEOWNERS + plans/138):
   `git reset --hard 9f70aaf && git push --force-with-lease origin
   main`. The PRE-port-fix anchor `aa812d7` no longer applies (it
   used port 5433 in docker-compose) so reverting to `aa812d7`
   would re-introduce the port-5432 conflict. The CI-green state
   is `9f70aaf`, not `aa812d7`.

3. **Test-suite won't run after port fix**: the dev host has a
   foreign postgres on port 5432 (`wvw-postgres`). Run
   `docker rm -f wvw-postgres` and retry.

## Tracking checklist

- [ ] User applies plans/137 gh-api PUT (admin scope required)
- [ ] User runs each Scenario above
- [ ] All 4 scenarios pass
- [ ] pytest exits 0 without env overrides
- [ ] Head of main logged with the commit that includes
      CODEOWNERS + port-5432 fix + plans/138
- [ ] Acceptance bar met
