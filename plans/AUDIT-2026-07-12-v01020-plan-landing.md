# Audit 2026-07-12 — v0.10.20 cycle-start plan-landing audit

**Cycle:** v0.10.20 `plan-landing` sub-cycle (forward-deferred from v0.10.19 mimo-half close-out).
**Marker commit SHA:** TBD at v0.10.20 mimo-half cycle-execution start (`--allow-empty`).
**Cycle-end audit filename convention:** `plans/AUDIT-2026-07-<cycle-end-date>-<marker>.md`.
**Recon scope:** Forward-deferred v0.10.19 M8 scope + ADR 002 bootstrap + M9 pre-commit hook race fix plan + hardened cycle close-out script archival.

---

## Executive Summary

| Axis | Verdict | Notes |
|---|---|---|
| **M8 PRIMARY scope planning** | 🟢 GREEN | `plans/RELEASE-v0.10.20.md` authored with 3-PR sub-deliverable breakdown (K1 / K2 / K3) + 1-iteration budget assertion (per code-reviewer-minimax-m3 v0.10.19 strongest recommendation). |
| **F17 forward-blocker formalisation** | 🟢 GREEN | ADR 002 (`plans/adr/002-statechange-parser-extension.md`) locks the statechange parser extension at byte-offset dispatch predicate EXCLUSIVELY. Target implementation: v0.10.21+. |
| **Pre-commit hook race fix plan** | 🟢 GREEN | `plans/M9-pre-commit-hook-race-fix.md` authored with file-scope hook exclusion (option (i)) as the minimal-cost fix. Target: v0.10.20 cycle-startup or close-out pre-mode. |
| **Hardened cycle close-out script** | 🟢 GREEN | `apps/api/scripts/cycle_closeout_apply_docs.py` archived from `/tmp/v0.10.19_apply_docs.py` with 4 production-safety fixes (assert → SystemExit; remove silent fallback; add re-splice guard; add post-Latest-tag guards) per code-reviewer verdict. Smoke test at `apps/api/tests/test_cycle_closeout_apply_docs.py`. |
| **M8 forward-defer thread (v0.10.19 → v0.10.20)** | 🟢 GREEN | The 4-cycle thread (v0.10.18 → v0.10.18.1 → v0.10.19 → v0.10.20) reads as one logical unit; this plan-landing phase bridges v0.10.19's DEFER close-out to v0.10.20's PRIMARY commit. |
| **M8 execution status** | ◯ PENDING | The actual M8 PRIMARY commit (PR-1 + PR-2 + PR-3) ships in `v0.10.20/mimo-half`, NOT in this plan-landing sub-cycle. |

---

## §1 — Document topology (4 new artifacts)

| Path | Role | Owner |
|---|---|---|
| `plans/RELEASE-v0.10.20.md` | M8 PRIMARY 1-iteration budget plan; 3-PR sub-deliverable breakdown + cycle-execution checklist | This sub-cycle |
| `plans/adr/002-statechange-parser-extension.md` | ADR locking the F17 forward-blocker (Phase 9 step 4 statechange parser extension); target: v0.10.21+ | This sub-cycle |
| `plans/M9-pre-commit-hook-race-fix.md` | M9 plan addressing the recurring `--no-verify` bypass at v0.10.18.1 + v0.10.19 close-outs; option (i) file-scope hook exclusion | This sub-cycle |
| `apps/api/scripts/cycle_closeout_apply_docs.py` + `apps/api/tests/test_cycle_closeout_apply_docs.py` | Hardened script for cycle close-outs (replaces ad-hoc `/tmp` scripts); production-safety guards per code-reviewer verdict | This sub-cycle |

The plan-landing sub-cycle ships these 4 docs as baseline on `main`.
The next sub-cycle (`v0.10.20/mimo-half`) executes the M8 PRIMARY scope
per `plans/RELEASE-v0.10.20.md` and lands its own close-out docs on top.

---

## §2 — M8 forward-defer thread (v0.10.19 → v0.10.20)

Cycle-end audit at `plans/AUDIT-2026-07-12-cd6e9ad.md` (v0.10.19) DIRECTED
M8 PRIMARY target = `v0.10.20/mimo-half`. This plan-landing sub-cycle
sets up the execution conditions:

1. **Authored the M8 fix-up plan** at `plans/RELEASE-v0.10.20.md` —
   the 3-PR sub-deliverable breakdown that the v0.10.19 cycle attempted
   but could not close under its 6-iteration signature budget. The v0.10.20
   plan opts for a simplified path: drop the `_disable_dotenv_for_tests`
   autouse fixture entirely (the v0.10.19 trap) and use `Settings(_env_file=None)`
   construction via a wrapped `get_settings` factory.

2. **Hardened the close-out script** at
   `apps/api/scripts/cycle_closeout_apply_docs.py` — production-safety
   guards prevent the v0.10.19 cycle's 6-iteration signature-budget
   pitfall from recurring in FUTURE close-out cycles.

3. **Authored M9 fix plan** at `plans/M9-pre-commit-hook-race-fix.md` —
   the `--no-verify` workaround used at v0.10.18.1 + v0.10.19 close-outs
   is a RECURRING pattern. M9 either fixes it (option (i) file-scope
   hook exclusion) OR formalizes `--no-verify` as the documented
   close-out-time workaround (option (iv)). Currently option (i) is
   the recommendation.

---

## §3 — F17 / ADR 002 forward-blocker

ADR 002 (`plans/adr/002-statechange-parser-extension.md`) locks the
structural change for F17's missing `BuffApplyEvent`:

- **Decision D.1**: surgical pass-through sub-branch at the upstream
  `if is_statechange != 0: continue` filter EXCLUSIVELY for
  `CBTS_BUFFAPPLY` (`is_statechange=1, is_buffremove=0`).
- **Decision D.2**: dispatch to a new `BuffApplyEvent` emit path
  (parallel to the existing `DamageEvent` / `HealingEvent` /
  `BuffRemovalEvent` dual-channel emit contract).
- **Decision D.3**: byte-offset dispatch predicate is the lock —
  future parser refactors that touch the upstream filter MUST
  preserve this contract as a regression-tested invariant.

Target implementation: v0.10.21+ (NOT v0.10.20 since v0.10.20 is M8
PRIMARY scope and ADR 002's effort is M-sized).

---

## §4 — Cycle-end status

**Cycle-end audit filename placeholder**: `plans/AUDIT-2026-07-<cycle-end-date>-<marker>.md`
where `<cycle-end-date>` = close-out date of v0.10.20 mimo-half and
`<marker>` = the marker commit SHA at v0.10.20 mimo-half cycle-execution start.

The 4 cycle-end docs landed at v0.10.20 mimo-half close-out time (NOT
this plan-landing) are:

1. `CHANGELOG.md` `[0.10.20]` entry splice — K-cluster closed language + 3-PR breakdown summary.
2. `docs/ROADMAP.md` §1.2 M8 row reclassification — M8 status `PENDING` → `CLOSED`.
3. `docs/ROADMAP.md` stamp refresh — `Last refreshed AT v0.10.20 cycle close-out (...)`.
4. `plans/AUDIT-2026-07-<date>-<marker>.md` cycle-end audit per the
   standard 5-section structure (Executive Summary + §1 Cycle topology +
   §2 K-cluster closed rationale + §3 Validation matrix + §4 Cross-references).

---

## §5 — Cross-references

- **Prior v0.10.19 cycle-end audit (DEFER rationale, INPUT for this cycle)**: `plans/AUDIT-2026-07-12-cd6e9ad.md`.
- **Prior v0.10.18.1 cycle-end audit (K-discoverer)**: `plans/AUDIT-2026-07-13-2ffafc75.md`.
- **Closure thread retrospective (v0.10.17 → v0.10.18 → v0.10.18.1)**: `plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md`.
- **M8 fix-up plan (this sub-cycle)**: `plans/RELEASE-v0.10.20.md`.
- **ADR 002 (F17 forward-blocker, this sub-cycle)**: `plans/adr/002-statechange-parser-extension.md`.
- **M9 pre-commit hook race fix plan (this sub-cycle)**: `plans/M9-pre-commit-hook-race-fix.md`.
- **F17 sizing spike (input for ADR 002)**: `docs/v0.10.19-combat-readout-spike.md`.
- **F17 design (XL+ effort)**: `docs/v0.9.0-combat-readout-design.md`.
- **Hardened close-out script (archive target)**: `apps/api/scripts/cycle_closeout_apply_docs.py`.
- **Smoke test (this sub-cycle)**: `apps/api/tests/test_cycle_closeout_apply_docs.py`.

---

## §6 — Plan-landing sub-cycle commit topology

| Commit | Purpose |
|---|---|
| `docs(release)` | `plans/RELEASE-v0.10.20.md` (M8 fix-up PRIMARY plan) |
| `docs(adr)` | `plans/adr/002-statechange-parser-extension.md` (F17 forward-blocker ADR; creates `plans/adr/` dir) |
| `docs(precommit)` | `plans/M9-pre-commit-hook-race-fix.md` (M9 plan) |
| `chore(script)` | `apps/api/scripts/cycle_closeout_apply_docs.py` (hardened close-out script archival) |
| `test(script)` | `apps/api/tests/test_cycle_closeout_apply_docs.py` (smoke test) |

5 atomic commits in `v0.10.20/plan-landing` working branch, ff-merged to
main on cycle-end. NO version tag (the v0.10.20 release tag is reserved
for the subsequent v0.10.20/mimo-half sub-cycle that ships M8 PRIMARY).
