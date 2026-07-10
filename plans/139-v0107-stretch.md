# Plan 139: v0.10.7 stretch & deferred items

*TBD document. Carries over context from plans 136, 137, and 138
(round-2 / round-3 code-reviewer items the user deferred to a
future plan rather than block v0.10.6 closeout on).*

## Why this exists

Round-2 of the plans/136/137 code-reviewer pass surfaced 5
substantive issues. 3 were addressed in round-2/3 commits; 2 were
deferred to user judgement:

- The CODEOWNERS rule on `.github/**` requires
  `require_code_owner_reviews: true` in the branch-protection
  rule (plans/137 gh-api PUT) to actually fire on the merge
  button. Without A1 applied, the CODEOWNERS rule is INERT.
- The pytest_env precedence trap verification (plans/138
  Acceptance Bar) pins a behaviour that depends on the user's
  pytest_env version. If a future bump changes
  `overwrite=True` defaults, the trap check becomes
  un-falsifiable.
- The v0.10.6 port-fix dev-host fragility (`wvw-postgres` block
  + cryptic `port is already allocated` failure mode) was
  deferred in favour of a one-line operator instruction. A more
  robust fix (depends_on healthcheck OR non-default port like
  5440) is unblockable here.

This stub makes these items discoverable via `ls plans/1*` so the
next agent picking up after the v0.10.6 closeout has a clear
home for the work.

## Tracking checklist

- [ ] **A1 branch-protection applied** (user-side, admin scope):
      run the `gh api PUT .../branches/main/protection` command
      from plans/137 on an admin-scoped workstation. Without
      this, `.github/CODEOWNERS` rules are inert. Verify with
      `gh api repos/Roddygithub/Gw2Analytics/branches/main/
      protection` returning non-null.

- [ ] **pytest_env version pin** in `pyproject.toml`:
      `[dependency-groups] dev = [..., "pytest-env>=1.6.0", ...]`
      (already pinned per pyproject.toml; just verify the pinned
      version's `overwrite=True` default is documented in the
      plans/138 acceptance step).

- [ ] **Port-5432 dev-host robustness** (alternative to current
      `docker rm -f wvw-postgres` operator step):
      - **Option A**: change `docker-compose.yml` to
        `depends_on: postgres: condition: service_healthy` with
        a port-5432 preflight check.
      - **Option B**: remap docker-compose to a non-default port
        like 5440 + update pytest_env accordingly. Eliminates
        the wvw-postgres conflict entirely but requires pytest_env
        + CI service updates to match.

- [ ] **CODEOWNERS handle switch** (production-readiness):
      `@Roddygithub` is a personal handle. For a team-managed
      deploy, switch to `@<org>/<team>` (e.g. `@Roddygithub/
      platform-team`). One search-and-replace in
      `.github/CODEOWNERS`; requires the team to exist in
      GitHub org settings first.

- [ ] **CI network-leak audit** (latent risk): if the test
      suite was leaking S3 calls to real MinIO via the broken
      placeholder creds, the CI workflow might be masking
      similar leaks for other services (Redis outbound, webhook
      HTTP). Audit `apps/api/tests/` per-test fixtures for
      completeness; consider a `pytest-mock-resources` or
      `responses` library to standardise hermeticity.

## References

- `plans/136-v0105-gha-major-version-bug.md` — dependabot bug
  investigation, Change A2 + B (file-based defense layers).
- `plans/137-v0106-branch-protection.md` — Change A1
  (branch-protection rule, user-side apply).
- `plans/138-v0106-dependabot-integration-test.md` — 5-scenario
  acceptance test for the 3 layered defenses.
- `apps/api/tests/conftest.py` `_mock_s3` fixture — the
  followup-1 S3 hermeticity fix that closed the 26-test gap.
