# v0.10.6 — Branch-protection rule for `.github/**` (Change A1)

This is the **GitHub-side** half of the dependabot hardenig from
plans/136. It cannot be applied from a file edit — it requires a
`gh api` call against the repo (admin scope required) and is
executed once by the user on their workstation.

## Background

`plans/136-v0105-gha-major-version-bug.md` documents the
dependabot-metadata bug (emits invalid major tags for some GHA
actions). Two of the three layered defenses were already shipped
via file edits in commits `b4b34f3` + `b59a3e7`:

- **Change A2** — `.github/workflows/dependabot-auto-merge.yml`
  with `paths-ignore: ['.github/**']` so the auto-merge workflow
  never fires on PRs that touch workflow files.
- **Change B** — `ignore:` block in `.github/dependabot.yml` for
  the 6 stale GHA actions (5 actions + `dependabot/fetch-metadata`)
  with `update-types: ["major"]` (or `["minor", "major"]` for
  `fetch-metadata`).

This plan (137) covers the third layer: **Change A1** —
branch-protection rule on `main` requiring an approval review when
the diff touches `.github/**`. With all three layers active:

1. dependabot never opens a major PR for a known-bad action (Change B),
2. even if it opens a PR, the auto-merge workflow excludes `.github/**`
   (Change A2),
3. AND even if a hand-rolled PR gets past Change A2 (e.g. human
   pushes a workflow edit), the branch-protection rule forces a
   review before merge (Change A1 — this plan).

## Exact command (run on your workstation)

You need admin scope on the repo. The bundled GH_TOKEN in this
session doesn't carry that scope (it's `gist, read:org, repo` —
all standard coder scopes, but not admin-protections:write).

```bash
# From your local workstation with gh auth login as an admin:
gh api -X PUT \
  repos/Roddygithub/Gw2Analytics/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  --input /tmp/branch-protection.json
```

The body file (`/tmp/branch-protection.json`) — put this content
there:

```json
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
```

That puts:
- 1 human approval required before any PR can merge (when path is
  anything in the repo — broad safety),
- `require_last_push_approval: true` ensures the latest push
  re-triggers review (so a force-pushed rebase can't slip past an
  existing approval),
- `dismiss_stale_reviews: true` so an approve against commit X
  doesn't auto-approve commit X+10.

## Path-scoped protection (the real `.github/**` gate)

The body above gives blanket 1-approval review across the whole
repo. To **specifically** require review when paths touch
`.github/**` (the actual narrow gate from plans/136), append a
GitHub CODEOWNERS rule:

Add this line to `.github/CODEOWNERS`:

```
# v0.10.6 plan 137 — any change to .github/** requires review
# by the repo's admin team. Prevents a patched workflow from
# landing without human eyes.
.github/** @Roddygithub
```

(The owner handle is a placeholder; replace `@<your-handle>` with
the actual GitHub owner/org that owns the workflow files. If you
use a team, e.g. `@Roddygithub/platform-team`.)

When CODEOWNERS is in place and the rule above is set, GitHub
will automatically require a review from `@<owner>` on any PR
that touches a `.github/**` file — even dependabot's PR — and
block the merge button until that review is granted.

## Manual steps

1. (one-time) Run the `gh api PUT` above with the JSON body.
2. (one-time) Commit `.github/CODEOWNERS` with the line above.
3. The branch is now protected. Verify with:
   ```bash
   gh api repos/Roddygithub/Gw2Analytics/branches/main/protection \
     | python3 -m json.tool
   ```
4. Re-run a dependabot cycle to confirm the integration:
   - dependabot opens a GHA PR with an invalid major → filtered by
     `ignore:` (no PR opened).
   - dependabot opens a non-workflow PR (pyproject.toml, lockfile) →
     auto-merge workflow fires, lands on main after CI green.
   - a human PR with `.github/workflows/**` edit → CODEOWNERS
     forces review.

## Rollback

If branch-protection blocks legitimate work:

```bash
gh api -X DELETE repos/Roddygithub/Gw2Analytics/branches/main/protection
```

(does NOT delete CODEOWNERS — that just stops enforcing the
human-check). To restore after rollback is the same `gh api PUT`
as above.

## Tracking

- [ ] User executes `gh api PUT` from workstation
- [ ] User commits `.github/CODEOWNERS`
- [ ] Verify with `gh api .../protection`
- [ ] Re-run a dependabot cycle as integration test
- [ ] Land plans/138-v0106-integration-test-results.md with the
       observed behavior

## Companion documents

- `plans/136-v0105-gha-major-version-bug.md` — bug investigation +
  Change A2 + Change B (already shipped).
- `plans/137-v0106-branch-protection.md` — this file (Change A1,
  GitHub-side).
