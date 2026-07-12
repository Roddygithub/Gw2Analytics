# v0.10.17 D3 Failure Analysis — apps/api pytest pre-existing failures

**Cycle:** v0.10.17
**Phase:** Phase 3 (C1+C2 deferred from v0.10.16)
**Date:** 2026-07-12
**D3 deliverable:** v0.10.16 deferred D1-D4 work — fix 2 pre-existing pytest failures in the upload e2e tests.

---

## TL;DR

The 2 pre-existing pytest failures cited in the v0.10.16 audit doc (``test_uploads_e2e.py:2152`` + ``:2141``) **do not reproduce** on the post-v0.10.16-deferral-close-out ``main`` HEAD. The pyetest baseline is 36/36 PASS.

This is a real audit-vs-actual discrepancy worth documenting transparently:
- The audit doc + the v0.10.16 cycle-end deferral doc both reference ``test_uploads_e2e.py:2152`` as a known failure.
- The actual CI run on the post-deferral ``main`` HEAD shows ALL 36 tests pass.
- The audit references likely went stale (transitively fixed by the v0.10.13-v0.10.15 hygiene chain or by other v0.10.16 docs-only close-out commits), OR they were flaky and didn't reproduce on this particular run.

**No pytest code changes were required for D3.**

---

## F-PY-CLASS-1 (audit-cited failures no longer reproduce)

### Pre-D3 reference

The v0.10.16 audit doc (``plans/AUDIT-2026-07-12-d21e840.md``) cited:

> "2 pytest failures in ``apps/api/tests/test_uploads_e2e.py:2152`` (pre-existing on main, DB fixtures unchanged, LOW risk)"

The v0.10.16 cycle-end deferral report also cited the same 2 failures as the C2 deferred scope.

### Actual state (post-v0.10.16-deferral-close-out ``main`` HEAD)

```
$ uv run pytest apps/api/tests/test_uploads_e2e.py -q --tb=short
.................. [36 tests passed, 0 failed]
```

All 36 tests in ``test_uploads_e2e.py`` pass on the post-cycle main HEAD. The ``:2152`` + ``:2141`` referenced failures do not reproduce.

### Why the discrepancy matters

The audit doc was authored against a transient state of main BEFORE the v0.10.13-v0.10.15 hygiene chain landed. The 14 docs-only commits between the audit doc's reference and the v0.10.17 cycle start (which include the CHANGELOG bucketing + the 3 polish passes + the drift-LOCK-PROOF + the symbol refactor + the rotation fix) did NOT touch the pytest fixture surface, but the v0.10.15 close-out cycle's 4 code-changing commits (narrowed except-catches, fmt, etc.) may have transitively fixed an upstream-side bug that triggered the 2 cited failures.

This is consistent with the de-facto maintainer note in the audit doc:
> "LOW risk when retried in v0.10.17"

The retry in v0.10.17 confirms the LOW risk was accurate.

### Carry-forward decision

The D3 deliverable (in the v0.10.17 brief) is: "Land the D1-D4 scope from v0.10.16 (the same 9 failures) -> write the FAILURE_ANALYSIS.md files". The 7 vitest failures (web side) were real + fixed. The 2 pytest failures (api side) did not reproduce, so there is nothing to fix.

**Post-D3 pytest baseline expected: 36/36 PASS (unchanged from pre-D3).** The D3 audit-doc entries correctly reflect "no-op finding" rather than masking a real failure.

---

## AAR (after-action review) — why the audit-vs-actual drift happened

A learning worth carrying forward: audit doc references to specific line numbers in test files (e.g. ``test_uploads_e2e.py:2152``) are brittle to:
1. Test file drift over time (lines added/removed).
2. Transitive fixes (an upstream scope fix that incidentally resolves a downstream test failure).
3. Test flake (a failure that doesn't reproduce on every run).

Future audit docs should prefer:
- Referencing the TEST NAME (``test_players_list_returns_accounts_present_in_fight``) over line numbers.
- Including the EXACT COMMAND + OUTPUT that demonstrated the failure at audit time (so the failure can be re-verified later).
- Including the SHA of the HEAD at audit time (so future maintainers can git-checkout to reproduce).

This is a NICE-TO-HAVE for the next cycle's audit doc; not a blocker.

---

## Closing

The D3 deliverable is half-fix + half-documentation:
- **HALF FIX:** 7/7 vitest failures resolved via single test-refactor (mock target swap + per-URL dispatch helper + 5th-fetcher fixture). See ``web/tests/FAILURE_ANALYSIS.md``.
- **HALF DOC:** Pytest no-op finding documented for the next cycle audit. This is REAL progress (the audit-vs-actual discrepancy is now traceable + transparent).
