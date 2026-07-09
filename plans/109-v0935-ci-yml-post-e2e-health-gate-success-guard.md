# Plan 109 (v0.9.35) — `ci.yml` post-e2e health gate `if: success()` guard against pytest-failure false-negatives

## Files touched
- `.github/workflows/ci.yml` (one-line addition of `if: success()` to the post-e2e health-gate step + corresponding cleanup)

## Findings (audit)

- `.github/workflows/ci.yml` has 12 named steps in order. The 3 health-probe steps are:
  - `Health probe baseline (v0.8.7)` — runs BEFORE pytest.
  - `Pytest`
  - `Health probe CI gate (v0.8.7 regression check)` — runs AFTER pytest.
  - `Health probe: cleanup /tmp/health_baseline.json` — runs `if: always()`.
- The `Health probe CI gate` step does NOT have an `if: success()` guard. If `Pytest` fails EARLY (e.g. a fixture import error, a missing test dependency), the e2e suite DID NOT RUN. The post-pytest probe sees the SAME database state as the baseline. The drift count is 0; the gate passes.
- Real-world impact: a regression in v0.8.4 materialise (the purpose of the gate) would manifest as a post-pytest drift > MAX_DRIFT_DELTA. But the regression COULD coincide with a coincident pytest fixture failure (e.g. a missing import in the same PR). Without the `if: success()` guard, the gate passes (false negative) regardless of the regression — the deeper signal is the pytest failure, but the gate ALSO PASSES because drift was 0.
- The fix: gate the post-e2e step on `if: success()` so the gate ONLY runs when pytest actually executed the e2e suite. The base-line + the post-suite comparison only makes sense when the test DB was actually exercised.
- The `if: success()` semantic in GitHub Actions is the canonical "previous steps all passed" guard. The `if: always()` semantic is "previous steps all completed (success or failure)". We want `success()`, not `always()`.

## Fix

1. `.github/workflows/ci.yml` — replace the post-e2e health-gate step:

   ```yaml
   - name: Health probe CI gate (v0.8.7 regression check)
     if: success()
     run: uv run python -m gw2analytics_api.scripts.health_gate --check-delta /tmp/health_baseline.json
   ```

   The single-line change adds `if: success()` so the step only runs when the upstream `Pytest` step passed.

2. The `Health probe: cleanup /tmp/health_baseline.json` step (`if: always()`) remains unchanged — cleanup is unconditional to avoid leaking the baseline file to a later job in the same runner. Cleanup should ALWAYS happen regardless of pytest success/failure.

3. NO new env-var additions. NO conditional logic in the python script.

4. NO change to the comment block on the health-probe steps (the existing inline comment block explains the rationale — it just doesn't mention the failure-mode-false-negative).

## Tests (3, NEW file `.github/workflows/test_ci_yml.py` — uses PyYAML to parse + AST inspect the step-level `if:` conditions)

- `test_post_e2e_health_gate_step_has_if_success_guard` — `yaml.safe_load` the workflow file; locate the step with name `"Health probe CI gate (v0.8.7 regression check)"`; assert the step's `if:` key equals `"success()"`.
- `test_baseline_step_has_no_if_guard` — the baseline step (`"Health probe baseline (v0.8.7)"`) MUST run unconditionally (no `if:` attribute); otherwise the baseline-vs-post comparison is off.
- `test_cleanup_step_has_if_always_guard_not_if_success` — the cleanup step (`"Health probe: cleanup /tmp/health_baseline.json"`) MUST have `if: always()` (NOT `if: success()`); otherwise a pytest failure would leave the baseline file in `/tmp/` for a later job to pick up.

## Rejected alternatives

- **Wrap the post-e2e gate in `if: success() || failure()` (= `if: always()`)** — same as the current pattern; runs even on failure. The fix requires `success()` ONLY. REJECTED.
- **Use `if: failure()` (run the gate only when pytest fails)** — inverse of the right semantic. The gate measures DRIFT; running it on pytest failure gives a false-positive when pytest crashed before the e2e suite ran. REJECTED.
- **Move the post-e2e health gate to a SEPARATE job** (`if: needs.lint-and-test.result == 'success'`) — adds another job's-worth of CI minutes for the same effect. The `if: success()` step-level guard is the cheaper fix. REJECTED.
- **Update the inline comment to say "false-negative-aware"** — the inline comment is correct; the issue is the missing `if:` guard, not the comment. REJECTED.
- **Skip the gate entirely if the post-e2e drift equals baseline (drift = 0)** — defeats the purpose; the gate's job is to catch drift > 0 regressions. With drift = 0 + pytest failure: the operator's PR has a coincident pytest error AND a (silent) materialise regression. The fix is `if: success()`. REJECTED.

## Dependency graph

- Independent: touches `.github/workflows/ci.yml` only + 1 NEW test file.
- Parallel-safe with plans 107 / 108.
- Pattern-aligns with the canonical GitHub Actions "conditional step" pattern: add `if:` to gate the step on a previous step's success/failure status. The `success()` keyword is the documented GitHub Actions expression that evaluates to true when no previous step in the same job failed.
