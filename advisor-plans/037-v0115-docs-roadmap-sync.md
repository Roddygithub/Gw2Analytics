# Plan 037 — v0.10.15: sync `docs/ROADMAP.md` to v0.10.14 cycle

**Status:** open
**Priority:** P3
**Impact:** LOW-MED (dev DX / project state honesty)
**Confidence:** 1.0

## Finding

`docs/ROADMAP.md` "Current state" header reads:

> **Status:** Living document. Last refreshed during the v0.10.9+
> audit cycle (2026-07-11).

The audit's F15-16 carried-forward finding: ROADMAP.md is stale
through v0.10.9; needs refresh for v0.10.13 + v0.10.14 cycle
shipts. The audit's "Findings carried forward" table confirms:

> F15-F16 (prior) — ROADMAP.md stale + `web/README.md` 3/8 routes
> documented — **PARTIALLY RESOLVED** — `ROADMAP.md` synced
> through v0.10.9; need refresh for v0.10.13 + v0.10.14 cycle
> shipts. NEW plan 050 below.

Per ROADMAP §4 "Update protocol" step 1, every release tag must
update the "Current state" section + walk §1-3 to check off
shipped items. The v0.10.13 + v0.10.14 cycles shipped without
this update.

## Fix

Update ROADMAP.md in 4 places:

1. **Header** — bump the "Last refreshed" date and reference the
   v0.10.15 cycle close-out (this plan lands AT v0.10.15 close).
2. **"Current state" section** — bump the "Latest shipped tag"
   from v0.10.x to the explicit `v0.10.14` + add the 4 MiMo
   deliverables (D1-D4) and the 5 v0.10.13 cycle plans
   (027, 028, 029, 012, 013) under the "Architecture" note.
3. **§1.1 "Items removed"** — ADD a new shipped-items subsection
   noting v0.10.13 + v0.10.14 cycle shipts:
   - DLQ GET + replay route + UI (plan 012 followup)
   - DNS executor w/ bounded timeout (plan 013 followup)
   - `_DNS_EXECUTOR.max_workers=32` (v0.10.10 followup)
   - `_event_dispatch.build_event_iterator` streaming gzip
     (plan 027)
   - Single `EVENT_TYPE_ADAPTER` across 3 routes (plan 028)
   - Per-fight blob `lru_cache(maxsize=8)` (plan 029)
   - `fetchCached` helper + drilldown page wrap (D2)
   - Visual regression baseline refresh 1→1.5% threshold (D3)
   - ARQ-integration CI gate (D4)
   - BFF Playwright e2e to CI green (D1)
4. **§1.2 "Ready to implement" shortlist** — ADD `Pre-existing
   test fix-up` (plan 036, deferred to v0.10.16+) as a future M
   effort (per §4 step 3 — new candidate emerged).

## Tests

No tests — this is a docs-only change. Verify via:
- `git diff docs/ROADMAP.md` shows the 4 sections updated.
- The "Last refreshed" date matches the v0.10.15 release.

## Out of scope

- `web/README.md` is already current (8/8 routes documented per
  the v0.10.14 cycle's README audit; the F15 finding cites the
  pre-v0.10.16 `web/README.md` state).
- CHANGELOG.md updates are handled per-release by the
  `conventional-changelog` CHANGELOG generator; out of scope
  here.

## Done criteria

- `git status` shows `docs/ROADMAP.md` modified with the 4
  sections above.
- "Last refreshed" date is the v0.10.15 cycle close-out date
  (not a stale earlier stamp).
- §1.1 still says "do not re-add without a fresh 'Why now'
  rationale" (the existing anti-drift rule is preserved).

## Maintenance note

This plan lands AT v0.10.15 close-out, AFTER the 4 code-changing
plans (032, 033, 034, 035) commit. The "Current state" header
correctly cites v0.10.14 as the LATEST SHIPPED TAG before the
docs update lands.

## Escape hatches

- If a maintainer prefers docs updates on a separate PR cycle,
  this plan can land standalone as a `docs(roadmap): sync to
  v0.10.14` commit. Out of scope to ship on the same PR as the
  code changes.

## Dependency graph

Standalone — no inter-plan deps. Pairs naturally with plans 032 +
033 + 034 + 035 in the v0.10.15 release PR.

## Cross-references

- Finding sourced from `plans/AUDIT-2026-07-12-5d0d4d4.md` F15.
- ROADMAP.md §4 "Update protocol" — the procedure being followed.
- ROADMAP §5 "Anti-drift notes" — preserved per the existing rule.
