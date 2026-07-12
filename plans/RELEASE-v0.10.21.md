# Release v0.10.21 — M-8-bis test-substrate rework + F17 statechange parser extension

**Cycle:** v0.10.21 `mimo-half` parent cycle consolidating two sub-surfaces.
**Marker commit SHA:** TBD at cycle-execution start (--allow-empty v0.10.21 cycle-window marker).
**Cycle-end audit filename convention:** `plans/AUDIT-2026-07-XX-v0.10.21.md`.
**v0.10.20 PARTIAL-FIX inheritance:** All 12 TASK-Y forward-blockers from `plans/AUDIT-2026-07-13-v0.10.20.md` §4 are the published pickup scope. The AUDIT doc is the single source of truth for TASK-Y enumeration; this release plan is the execution-strategy + branch-tree artifact.

---

## §1 — Cycle thread (the five-cycle logical unit)

| Cycle | Phase | Output |
|---|---|---|
| v0.10.18 | main scope | CHANGELOG reorder (K counts post-v0.10.18 closeout) + ROADMAP §1.2 Option B+ M8 placement |
| v0.10.18.1 | mimo-half follow-up | Lock-in v0.10.18 close-out; place M8 ↔ ROADMAP §1.2; close-out audit at `plans/AUDIT-2026-07-13-2ffafc75.md`; K1+K2+K3 discoverer |
| v0.10.19 | mimo-half M8 attempt + DEFER | plan-landing docs at `712522a`; 6 iterations on conftest.py exhausted signature budget; DEFER close-out audit at `plans/AUDIT-2026-07-12-cd6e9ad.md` |
| v0.10.20 | mimo-half M8 PRIMARY + PARTIAL-FIX | 5 atomic commits + AUDIT close-out + tag force-advanced to `96f938e`; PARTIAL-FIX framing per AUDIT §A invariant |
| **v0.10.21** | **mimo-half M-8-bis (this plan) + F17 sub-cycle** | 2-iteration budget; M-8-bis 4 true residues first + 8 substrate/cycle-authoring followups; F17 sub-cycle on the ADR 002 WIP branch (off main `0069c63`); cycle-end audit at `plans/AUDIT-2026-07-XX-v0.10.21.md` |

---

## §2 — Sub-deliverables (multi-branch tree; 2 sub-cycles, ZERO shared commit topology)

### 2.1 M-8-bis sub-cycle — `k-cluster-residual-12` branch (PRIMARY)

**Surface:** `apps/api/tests/` substrate rework ONLY. NO production code changes (K-cluster is test-substrate-mismatch per `plans/AUDIT-2026-07-13-2ffafc75.md`).

**Pickup order (from reviewer §3 + AUDIT §4):**

| Order | TASK-Y ID | Sub-cluster | True-residual? | Effort |
|---|---|---|---|---|
| 1 | TASK-K-1-DISPATCH-FK-A | K-1 dispatch FK | YES | S |
| 2 | TASK-K-1-DISPATCH-FK-B | K-1 dispatch FK | YES | S |
| 3 | TASK-K-2-SSRF-SUBSTRATE-REWORK-A | K-2 SSRF + cross-test pollution | YES | M |
| 4 | TASK-K-2-SSRF-SUBSTRATE-REWORK-B | K-2 SSRF substrate | YES | S |
| 5 | TASK-SUBSTRATE-MONOREPO-A | Cross-cutting conftest | NO (cycle-authoring) | M |
| 6 | TASK-M9-EXCLUDE-BROADEN-A | pre-commit M9 | NO (substrate) | XS |
| 7 | TASK-K-3-EXECUTOR-MOCK-A | K-3 executor mock | NO (substrate-improvement) | M |
| 8 | TASK-K-3-EXECUTOR-MOCK-B | K-3 cross-validation | NO (cross-validation) | XS |
| 9 | TASK-K-1-DISPATCH-FK-C | K-1 cross-validation | NO (passes; cross-validate) | XS |
| 10 | TASK-K-1-DISPATCH-FK-D | K-1 cross-validation | NO (passes; cross-validate) | XS |
| 11 | TASK-M-8-BIS-PLAN-LANDING | Cycle-authoring (this doc) | NO | XS (lands at close-out) |
| 12 | (intentionally out of M-8-bis sub-cycle) | F17 sub-cycle | — | — |

**Acceptance criteria:**
- `pytest tests/test_uploads_arq.py` → all 7 cases PASS (6 post-fix + 1 cross-validate).
- `pytest tests/test_webhooks_e2e.py` → all 22 cases PASS (4 SSRF-gate + 18 non-SSRF; previously 18/22 → target 22/22).
- `pytest tests/test_uploads_e2e.py --tb=line -q` → 36/36 PASS (D2 baseline preserved).
- Zero production-code regression (audit validates via `git diff main --stat` showing zero changes to `apps/api/src/`).

### 2.2 F17 statechange parser sub-cycle — `v0.10.21/f17-statechange-extension` branch (PARALLEL)

**Surface:** Parser-side mechanism + analytics-side aggregator + new `BuffApplyEvent` subclass. **ZERO test-substrate work** (orthogonal to M-8-bis).

**Files planned per ADR 002 WIP marker (`plans/adr/002-WIP-statechange-extension.md`):**
1. `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` — extend `_iter_fights`/`parse_events` to emit `BuffApplyEvent` from `is_statechange != 0` records whose `is_statechange == 0` falsify flag is determined by byte 52 (post-realignment era).
2. `libs/gw2_core/src/gw2_core/models.py` — add `BuffApplyEvent` subclass to `Event` discriminated union.
3. `libs/gw2_analytics/src/gw2_analytics/boons_apply.py` — NEW aggregator for per-(fight, agent) BuffApply count + per-target BuffApply rollup.
4. `libs/gw2_evtc_parser/tests/test_parser_emit_buffapply.py` — NEW expansion of `test_parser_byte_alignment` asserting BuffApply emit predicate.

**Two-phase flow (per ADR 002 WIP marker + §5 below):**
- **Phase 1**: F17 commits grow on the WIP branch (`v0.10.21/f17-statechange-extension`). WIP branch stays NOT ff-merged to main throughout the cycle.
- **Phase 2**: On F17 completion, ff-merge WIP branch to main AT v0.10.21 cycle-end (atomically after M-8-bis close-out but BEFORE tag force-advance).

**Acceptance criteria:**
- New `BuffApplyEvent` rows appear in `apps/api/tests/test_uploads_e2e.py --tb=line -q` (D2 baseline extended from 36 → 36+ test cases).
- Zero regression on existing `DamageEvent` + `HealingEvent` + `BuffRemovalEvent` paths.
- `plans/AUDIT-2026-07-XX-v0.10.21.md` enumerates per-file change attribution (4 files + tests).

---

## §3 — Iteration budget

**M-8-bis sub-cycle: 2 iterations** (vs the 1-iteration convention for mimo-half).

**Why 2 iterations:**
- The 4 true residues (K-1 dispatch FK ×2 + K-2 SSRF-substrate ×2) need PR slots that can't be co-located (K-2's `_get_settings_no_dotenv` autouse is the substrate; K-1's `lifespan teardown flush` is the runtime). Splitting into 2 atomic commits:
  - **Iteration 1 = PR-A (TASK-K-1-DISPATCH-FK-A + B)**: 5-line conftest.py / lifespan.py edit (commit e.g. `8e9dXXX`).
  - **Iteration 2 = PR-B (TASK-K-2-SSRF-SUBSTRATE-REWORK-A + B + SUBSTRATE-MONOREPO + M9-EXCLUDE-BROADEN)**: 30+ line conftest.py / pre-commit / route refactor (commit e.g. `9a8bYYY`).
- The 8 substrate/cycle-authoring items then fold into a series of `--no-verify` docs-only close-out commits (per AUDIT §5.6 positive pattern).

**F17 sub-cycle: 1 iteration** (parser + analytics is straightforward additive work; no substrate tangle).

**Total budget:** 3 atomic commits + 4 docs commits + 1 WIP-merge + 1 close-out audit = 9 atomic events on `v0.10.21/mimo-half` branch.

---

## §4 — Sub-cycle topology (multi-branch tree)

```
                          main (FFE merge target)
                          ▲
       ┌──────────────────┴──────────────────┐
       │                                     │
v0.10.21/mimo-half (parent)   v0.10.21/f17-statechange-extension (WIP)
       │                                     │
       │                                     └─ F17 parser-side +4 commits
       │
       ├─ M-8-bis PR-A (TASK-K-1-DISPATCH-FK-A + B) — commit e.g. `8e9dXXX`
       ├─ M-8-bis PR-B (TASK-K-2-SSRF + SUBSTRATE-MONOREPO + M9-EXCLUDE) — commit e.g. `9a8bYYY`
       ├─ K-3 EXECUTOR-MOCK-A + B — commit e.g. `4c5dZZZ`
       ├─ CHANGELOG [0.10.21] splice — commit (docs)
       ├─ ROADMAP §1.2 M-8-bis CLOSED + status marker — commit (docs)
       ├─ plans/AUDIT-2026-07-XX-v0.10.21.md — commit (docs)
       └─ tag v0.10.21 force-advance AT cycle-end
```

**Branch policy:**
- `v0.10.21/mimo-half` is the only branch where M-8-bis commits land.
- `v0.10.21/f17-statechange-extension` (already exists, SHA 9440400) is the F17 WIP branch; NEVER ff-merge mid-cycle.
- Both branches share main `0069c63` (v0.10.20 PARTIAL-FIX base) as the divergence point.
- F17 WIP grows on main's v0.10.20 PARTIAL-FIX tip + v0.10.21 cycle-end M-8-bis tip via rebase (NOT ff-merge to main).

---

## §5 — WIP branch lifecycle (2-phase flow)

**Phase 1 — F17 commits grow on WIP branch.**
- Each F17 sub-task lands as an atomic commit on `v0.10.21/f17-statechange-extension`.
- The WIP branch is NOT ff-merged to main during cycle execution.
- Commit messages preserve the F17 marker convention: `feat(parser): ...` / `feat(core): ...` / `feat(analytics): ...` / `test(parser): ...`.
- Cross-cycle disturbance: F17 commits MAY cause the WIP branch to diverge from main by N+ commits (N grows over cycle execution).

**Phase 2 — ff-merge WIP branch to main at cycle-end.**
- After all F17 commits land AND M-8-bis cycle-end commits land on `v0.10.21/mimo-half`:
  1. `git checkout v0.10.21/mimo-half`
  2. `git merge --ff-only v0.10.21/f17-statechange-extension` (or `git rebase v0.10.21/mimo-half` onto WIP for clean shape)
  3. `git checkout main && git merge --ff-only v0.10.21/mimo-half`
  4. `git tag -a v0.10.21 -F /tmp/v0.10.21_annotation.txt`
- The WIP branch is NOT deleted (it stays as a branch reference; future cycles may need it for rebase-onto-v0.10.22 work).

**Anti-pattern (deliberately broken-by-design):**
- DO NOT ff-merge WIP branch BEFORE cycle-end (would mix F17 work into M-8-bis verification).
- DO NOT `--no-verify` on F17 commits without footer rationale (parser changes may introduce real regressions; --no-verify is for docs-only).

---

## §6 — Anti-drift + risk register

### 6.1 Anti-drift notes

1. **Pickup order enforcement**: this plan enumerates 12 TASK-Y items in §2.1; do NOT reorder picks #1-#4 (true residues) without explicit reviewer approval. Reshuffling items 5-11 is OK.
2. **M-8-bis = 2 iterations**: do NOT exceed budget. If TASK-K-2-SSRF-SUBSTRATE-REWORK-A needs >1 iteration, escalate to PARTIAL-FIX formal cycle name (not DEFER).
3. **Cross-cycle pollution check**: after every M-8-bis commit, re-run `pytest tests/test_uploads_e2e.py --tb=line -q` to confirm D2 36/36 PASS. Substrate rework may regress the D2 surface; abort PR if regression detected.

### 6.2 Risk register

1. **TASK-K-2-SSRF-SUBSTRATE-REWORK-A may require coordinated PR across conftest.py + pre-commit + routes/webhooks.py** — risk of partial landing. Mitigation: pre-write a 3-file patch in conftest authoring phase; commit atomically.

2. **F17 WIP branch may rebase conflicts with main progress** — risk of stale FF target. Mitigation: keep WIP branch divergence ≤ N+10 commits; if divergence grows, rebase WIP onto current main tip atomically (no F17 commit during rebase).

3. **D2 baseline regression risk from `_get_settings_no_dotenv` conftest autouse**: per AUDIT §1.3.2 (b), the per-process cache pollution can surface D2 tests that depend on `Settings()` fields. Mitigation: dry-run D2 in conftest authoring phase BEFORE committing.

---

## §7 — Cross-references

- **v0.10.20 PARTIAL-FIX AUDIT (single-source-of-truth for v0.10.21 pickup scope):** `plans/AUDIT-2026-07-13-v0.10.20.md` — §4 enumerates the 12 TASK-Y forward-blockers; §A carries the relabeling invariant.
- **ADR 002 WIP marker (F17 sub-cycle landing-zone):** `plans/adr/002-WIP-statechange-extension.md` (on `v0.10.21/f17-statechange-extension` branch only, NOT on main).
- **ADR 002 itself (statechange parser extension Phase 9 step 4):** `plans/adr/002-statechange-parser-extension.md` (on main since v0.10.20 plan-landing sub-cycle, commit `0069c63`).
- **v0.10.20 RELEASE plan (this plan's structural template):** `plans/RELEASE-v0.10.20.md` (at main `0069c63`).
- **Prior v0.10.19 mimo-half DEFER audit:** `plans/AUDIT-2026-07-12-cd6e9ad.md`.
- **K1+K2+K3 canonical discoverer:** `plans/AUDIT-2026-07-13-2ffafc75.md`.
- **Closure thread retrospective (v0.10.17 → v0.10.18 → v0.10.18.1):** `plans/AUDIT-2026-07-13-RETROSPECTIVE-V01017-V010181.md`.
- **Hardened cycle close-out script:** `apps/api/scripts/cycle_closeout_apply_docs.py`.
- **Smoke test for the close-out script:** `apps/api/tests/test_cycle_closeout_apply_docs.py`.

---

## §8 — Cycle-execution checklist (close-out time)

At the end of the v0.10.21 mimo-half cycle, the executor MUST verify:

1. `pytest tests/test_uploads_e2e.py --tb=line -q` → 36/36 PASS (D2 baseline preserved).
2. `pytest tests/test_uploads_arq.py --tb=line -q` → all 7 cases PASS (K-1 dispatch FK closed).
3. `pytest tests/test_webhooks_e2e.py --tb=line -q` → all 22 cases PASS (K-2 SSRF-gate + 18 non-SSRF closed).
4. `pytest tests/test_webhooks_dns_under_attack.py tests/test_webhooks_getaddrinfo_timeout.py tests/test_webhooks_dns_executor_concurrency.py` → all DNS-concurrency cases PASS (K-3 closed).
5a. (F17 conditional — gates ONLY if F17 ships in v0.10.21 per §5 2-phase flow) `pytest tests/test_parser_emit_buffapply.py` (NEW F17 test) → all BuffApply emit predicate cases PASS; `pytest tests/test_parser_byte_alignment.py` extended assertions PASS.
5b. WIP branch `v0.10.21/f17-statechange-extension` ff-merged to main ONLY post M-8-bis close-out + pre-tag-force-advance. **F17 deferral gate:** if F17 phase 1 has NOT produced at least 1 commit on the WIP branch by step-5 execution time, F17 defers to v0.10.22 sub-cycle (NOT v0.10.21); WIP branch preserved; v0.10.21 cycle may STILL declare CLOSED if steps 1-4 PASS + D2/D1 baselines preserved.
6. Full surface `pytest tests` → 297+ / 297+ green (no D2 regression; K-cluster now zero).
7. `ruff check` + `mypy --no-incremental` on the modified `apps/api/tests/` + new pod scripts + new tests → clean.
8. CHANGELOG `[0.10.21]` entry spliced with K-cluster closed + F17 sub-cycle landed language.
9. ROADMAP §1.2 M8 row reclassified from "M8 PARTIAL-FIX" to "M8 (test-substrate fix-up) CLOSED" + new F17 row IF F17 ships in this cycle.
10. Cycle-end audit `plans/AUDIT-2026-07-XX-v0.10.21.md` authored with the standard 6-section structure (Executive Summary + §1 Cycle topology + §2 M-8-bis + F17 closed rationale + §3 Validation matrix + §4 Cross-references + §A shipping-invariant).
11. WIP branch `v0.10.21/f17-statechange-extension` preserved (NO accidental deletion).
12. `v0.10.20` tag remains anchored at `96f938e` (NO force-re-advance of v0.10.20 tag).
13. Annotated tag `v0.10.21` + force-push + `gh release create`.

---

## §9 — Forward-blocker handbook (multi-cycle)

When authoring a new cycle release plan that picks up previously-deploy forward-blockers (this cycle does NOT — all 12 v0.10.20 forward-blockers are INTERNAL pick-ups for the v0.10.21 mimo-half), enforce:

1. **Source-of-truth precedence:** a forward-blocker in the prior cycle's AUDIT doc is authoritative. Do NOT restate it in the new release plan; reference by file-path + section anchor.
2. **Two-tier attribution:**
   - **True test residuals** → must fix in the cycle's PRIMARY iteration budget; otherwise the cycle declares PARTIAL-FIX (not "completed").
   - **Substrate-improvement / cycle-authoring / future-cycle items** → may fold into close-out docs OR defer to a sibling sub-cycle.
3. **PARTIAL-FIX framing:** if any true residual remains OPEN at cycle-end, the v0.10.21 cycle's release plan must explicitly call out "12 → 0 residuals → N residuals" delta and the new forward-blocker list (per AUDIT §A invariant: release prohibited from being relabeled "completed" until N = 0).

**This cycle's commitment:** v0.10.21 departs with **0 true residuals** (all 4 closed), and lands 0 new forward-blockers. PARTIAL-FIX framing only applies if 1 of the 4 true residuals fails to close — escalation path NOT in scope of this plan (would be a separate plans/RELEASE-v0.10.21-PARTIAL-FIX.md).
