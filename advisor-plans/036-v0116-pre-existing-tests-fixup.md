# Plan 036 — v0.10.16+: pre-existing pytest + vitest fix-up (deferred, NOT v0.10.15 scope)

**Status:** DEFERRED
**Priority:** P3
**Impact:** MED (gates from "documented pre-existing" to GREEN)
**Confidence:** 0.7 (audit-pass hypothesis — the failing tests' LRU interaction is not direct-line verifiable)

## Finding

Per the v0.10.14 cycle audit (`plans/AUDIT-2026-07-12-5d0d4d4.md`),
the following pre-existing failures live on `main` and were
documented but NOT fixed in v0.10.14:

- **7 vitest failures** in `web/tests/components/{fight-events-page*, window-size-selector.test.tsx}`
- **2 pytest failures** in `apps/api/tests/test_uploads_e2e.py`

Both are documented in `plans/RELEASE-v0.10.14.md`'s "Gate contract"
section as a known-but-deferred state.

The vitest failures interaction with the v0.10.14 `fetchCached`
LRU is **an audit-pass hypothesis** — the cycle-end file-picker
read of `fights/[id]/page.tsx` does NOT reveal whether the failing
vitest tests assert against the LRU surface. The hypothesis
("may now be flaky intermittently") is plausible but not
direct-line verifiable from the audit.

## Fix

### Phase A (v0.10.16 diagnostic — 1 cycle work)

1. Run the 7 vitest failures with verbose stdout to capture the
   actual assertion messages.
2. Cross-correlate the failing test ids with the `fetchCached`
   call sites (D2 from v0.10.14 cycle).
3. For each pair: classify as (a) pure assertion drift, (b) LRU
   interaction, (c) unrelated to v0.10.14 cycle.

### Phase B (v0.10.16+ fix-up)

Per classification:

- (a) Pure assertion drift → fix the assertion to the new
  contract (no LRU mock needed).
- (b) LRU interaction → mock the LRU (`vi.mock('@/lib/fetchCached')`)
  per test.
- (c) Unrelated → fix the underlying assertion or mark
  `test.skip` with a `todo` doctring.

### Phase C (pytest fix-up — separate)

The 2 pytest failures in `test_uploads_e2e.py:2152` are
DB-fixture-gated and pre-cycle. Likely candidates:
- Alembic migration drift (already guarded by `check_schema_drift`,
  but the pre-existing failures predate that guard).
- A change in the upload schema not reflected in fixture seeders.

The pytest fix-up is a S/M-effort standalone cycle; separate plan
recommended.

## Tests

| Test | File | Type |
|------|------|------|
| `test_fetch_cached_lru_unaffected_by_component_test` (NEW) | `web/tests/lib/fetchCached.test.ts` | vitest |

The new test pins the LRU-on-test-isolation contract — a vitest
test invoking `fetchCached` does NOT pollute the next test's
state. This is the regression-pin for an LRU interaction gate.

## Out of scope

- **F8/F9/F20 god-module carry-forward** (`plans/AUDIT-2026-07-12-5d0d4d4.md`) — separate cycles.
- **F17/F18 combat readout + replay UI** — deferred per maintainer direction.

## Done criteria

Phase A done when the vitest + pytest failures are
classified by category with a typed cause.

Phase B done when pytest collection returns 0 failures and
`pnpm test:unit` returns 0 failures.

## Maintenance note

The audit doc's O5 record will be reclassified after Phase A —
if the LRU interaction is confirmed, the finding moves from
"hypothesis-grade" to "confirmed". If not, it's a pure
assertion-drift cleanup.

## Escape hatches

- If Phase A reveals the LRU interaction IS the cause, plan 035
  (partial-failure UI) gains a `?failAllSections=1` query param
  for QA.

## Dependency graph

- Depends on plan 035 (partial-failure UI surface) for the
  QA affordance.
- Loose dep on the v0.10.13 mypy-strict chore (plan 019) for
  test-discipline parity.

## Cross-references

- Finding sourced from `plans/AUDIT-2026-07-12-5d0d4d4.md` §"Open
  findings" O5 (hypothesis-graded).
- Cycle scope: v0.10.16+ (NOT v0.10.15). The audit doc
  recommended v0.10.16+ for O5 by design — pre-existing pytest
  failures are stable but documented.

## Why deferred

The v0.10.15 cycle budget is the 4 S+M-effort items
(O1-O4). The M-L effort pre-existing-test fix-up is a
multi-cycle task (diagnostic + fix + regression-pin) and
benefits from the O1-O4 cycle's lessons learned.
