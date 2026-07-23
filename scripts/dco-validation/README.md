# DCO validation scripts

This directory contains scripts to validate the inline bash DCO check
(`.github/workflows/ci.yml` job `dco-check`) end-to-end.

## How to re-run the validation

```bash
# From the repo root:
bash scripts/dco-validation/dco_full_test.sh
```

The script:

1. **Phase 1** — Creates a test branch with an **unsigned** commit, opens a
   PR, and waits for CI. The inline bash DCO check SHOULD return FAILURE
   (missing `Signed-off-by:` trailer).
2. **Phase 2** — Amends the commit with `-s` and force-pushes. The DCO check
   SHOULD return SUCCESS (trailer present).
3. **Cleanup** — Closes the PR, deletes the branch.
4. **Promotion** — If both phases behave as expected, promotes `DCO check`
   to the `required_status_checks` ruleset rule in `main-protection`
   (ruleset 19640118).

## Prerequisites

- `gh` CLI authenticated against `Roddygithub/Gw2Analytics`
- Git configured with `user.name` + `user.email`
- `jq` and `python3` available
