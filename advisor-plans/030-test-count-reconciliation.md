# Plan 030 — Test count reconciliation in README

**Stamped at:** `5cfd962` (origin/main HEAD at audit time)
**Severity:** LOW (documentation accuracy)
**Category:** docs, DX
**Addresses finding:** `README.md` `**Status:**` line claims `1,150+ active tests (353 pytest + 797 vitest)`; actual is `279 pytest pass / 2 skip` in `apps/api` + `112 pytest pass / 1 skip` in `libs/` = `~391 pytest total` (not 353) + `vitest run` count is 85 pass. The 74-test gap in the pytest number and the imprecise vitest number need correction.

---

## Finding

Evidence from the audit health metrics:

```
| Pytest (apps/api) | 279 pass / 2 skip / 0 fail |
| Pytest (libs)     | 112 pass / 1 skip / 0 fail |
| Pytest total      | 391 pass / 3 skip / 0 fail |
| Vitest (web)      | 85 pass / 0 fail            |
```

The README claims `1,150+ active tests (353 pytest + 797 vitest)`. Both numbers are stale:
- pytest: 353 → 391 (38 more tests added since the count was last updated)
- vitest: 797 → 85 (the 797 was likely a different counting methodology or a stale number from a different scope)

The `1,150+` total is also stale: 391 + 85 = 476, not 1,150.

---

## Fix

### Step 1 — Update the `**Status:**` line in README.md

Replace:
```
**1,150+ active tests** (353 pytest + 797 vitest) across pytest + vitest + Playwright
```

With:
```
**~476 active tests** (~391 pytest + ~85 vitest) across pytest + vitest + Playwright
```

### Step 2 — Update the Highlights section

Line 21:
```
- 🧪 **1,150+ automated tests** across `pytest` (353), `vitest` (797), and `Playwright` e2e — all green on every PR.
```

Replace with:
```
- 🧪 **~476 automated tests** across `pytest` (~391), `vitest` (~85), and `Playwright` e2e — all green on every PR.
```

### Step 3 — Commit

```bash
git add README.md
git commit -m "docs(readme): reconcile test counts with actual pass rates (plan 030)"
```

---

## Tests

- Visual inspection: the README numbers match the actual test output.
- `uv run pytest apps/api/tests/ --tb=short` — confirms 279 pass / 2 skip.
- `uv run pytest libs/ --tb=short` — confirms 112 pass / 1 skip.
- `cd web && pnpm vitest run` — confirms 85 pass.

---

## Rejected alternatives

- **Add a CI step that auto-updates the test count**: tempting (prevents future drift). Rejected: the README is a snapshot document; auto-updating it on every CI run would create noisy commits. A manual reconciliation per audit cycle is sufficient.
- **Remove the test count entirely**: the count is useful for contributors evaluating test coverage. Keep it but make it accurate.
- **Pin the exact count (476) instead of using `~`**: the count changes with every PR. The `~` prefix signals "approximately" and prevents the number from becoming stale again immediately.

---

## Dependency graph

- **Standalone.** No plan depends on this one; this plan doesn't depend on any.

---

## Notes for executors

- The vitest count (85) was verified from the CHANGELOG v0.9.0 entry and the audit health metrics. If the actual `pnpm vitest run` count differs, use the live number.
- The `~391 pytest total` includes both `apps/api` (279) and `libs/` (112). Some libs tests may be counted differently depending on the runner scope.
