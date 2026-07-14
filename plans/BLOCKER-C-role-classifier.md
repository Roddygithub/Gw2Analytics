# Blocker C — Player Role Classifier (combat-readout)

> **Companion docs:**
> - **Spike:** [`docs/v0.10.19-combat-readout-spike.md`](../docs/v0.10.19-combat-readout-spike.md) — Blocker C sizing (§3.1 + §3.3) + heuristic classification parameters.
> - **Upstream Plan:** [`plans/WAVE-8-parser-side.md`](WAVE-8-parser-side.md) — Blocker A + Blocker B plans + the shared SCAFFOLD-zero contract standard (§5).
> - **Downstream Consumer:** [`plans/F17-frontend-rollout.md`](F17-frontend-rollout.md) — W.2-W.12 AG Grid integration that surfaces this classifier's output.

> **Cross-references:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) (F17 cycle topology) + [`docs/v0.9.0-combat-readout-design.md`](../docs/v0.9.0-combat-readout-design.md) (§3-6 the 4 tablet contracts that consume the role column).

> Status: **DRAFT** — pending spike re-validation + corpus availability sign-off.

## §0 Scope + ownership

> **Cross-references:** [`docs/ROADMAP.md`](../docs/ROADMAP.md) (F17 cycle topology) + upstream [`plans/WAVE-8-parser-side.md`](WAVE-8-parser-side.md) (Blockers A + B plans + shared SCAFFOLD-zero contract) + downstream [`plans/F17-frontend-rollout.md`](F17-frontend-rollout.md) (W.2-W.12 AG Grid surface).

Blocker C completes the SCAFFOLD-zero column unlocks for the F17 combat readout by implementing the `PlayerRoleClassifier` and delivering the 7-role subset `{HEAL, DPS, STRIP, SUPPORT, CC, TANK, BOONS}`. Unlike Blockers A and B (which extract missing data from the parser), Blocker C is pure analytical logic applied over **stable Wave 3 R.1-R.4 per-player roll-ups**.

**Owners / effort:**

- **Blocker C** → `libs/gw2_analytics` (Python classifier) + thin `web/src/lib/role-classifier.ts` TS surface for the 8th column rendering. Effort: **M** for code (~150-200 LOC Python + ≤40 LOC TS surface) but **L** calendar time for offline threshold tuning against a representative corpus.

## §1 SCAFFOLD-zero mode + migration contract

Until C.1-C.3 reach DONE, the Web UI renders the `roles` column in **SCAFFOLD-zero mode** per the Wave 8 §5 contract: each cell hydrates to `"—"` (em-dash) regardless of roll-up presence. When Blocker C ships, the SCAFFOLD-zero default is dropped at a single call site (see §4) and the column auto-hydrates to native values for any zevtc log versioned under the post-Wave 3 aggregator schema.

The prefix-only scaffold framing in Wave 8 §5 ("2-line SCAFFOLD-zero default removal at the page.tsx level") applies identically here — Blocker C does **not** redefine the contract, only consumes it.

## §2 Blocker C sub-blocks

(Source of truth for sub-block descriptions: `docs/v0.10.19-combat-readout-spike.md` §3.1 + §3.3.)

| Sub-block | Effort | Done criterion |
|---|---|---|
| **C.1** Implement classifier core | M | `PlayerRoleClassifier.classify(per_player_roll_ups)` outputs valid `{HEAL, DPS, STRIP, SUPPORT, CC, TANK, BOONS}` sets per spike §3.1 heuristics. Pure function; deterministic; no I/O. |
| **C.2** Offline threshold calibration | L | Thresholds tuned against a representative historical zevtc corpus (N≥20 boss fights across M=4 archetypes: raid / fractal / strike / wvw). Calibration report committed alongside. |
| **C.3** Hermetic tests (5+) | S | Test-suite covers boundary thresholds (below / at / above each role's cutoff), multi-role scenarios (e.g., HEAL+SUPPORT player), empty roll-ups dict, and missing-aggregator-field graceful degradation. |

## §3 Sequencing

1. **Blockers A + B** → must reach DONE first (parser emits the new event subclasses; Skills DB seeds the catalog used by BOONS role-detection).
2. **Wave 3 R.1-R.4 aggregators** → must reach DONE (stable schema for the roll-ups Blocker C consumes). R.3 + R.4 are explicitly **XL** effort — calendar-time risk.
3. **C.1 + C.3** can run in parallel with C.2's corpus-gathering; C.2 calibration is the gating step for production unlock.
4. **Wave 6 / Wave 7 (baseline)**: once C reaches DONE, the SCAFFOLD-zero `roles` column auto-hydrates to native values; no separate cycle is required for the existing baseline. Forward-flow of role data into later phases is captured by future plans scoped at their respective cycle topology (no forward-binding to R.5+ or Wave 9+ from this doc).

## §4 Migration impact in web/

Per the Wave 8 §5 contract (single-line SCAFFOLD-zero default removal), Blocker C requires exactly **2 surgical edits** in `web/`:

- `web/src/app/fights/[id]/page.tsx` → drop the 1-line `roles` SCAFFOLD-zero list fallback (the `?? ["—"]` short-circuit for the missing classifier key).
- `web/src/components/PlayerReadoutBase.tsx` → drop the `"—"` default `valueGetter` for the role-cell column resolver; let AG Grid consume the classifier's native `Set<string>` via `valueFormatter` (renders as e.g. `"HEAL, SUPPORT"`).

Both edits land atomically with the C.1 PR; no in-flight transition state required (UI flips from scaffold to native in a single deploy).

## §5 Risks + mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Non-representative calibration corpus** | Thresholds misclassify non-meta builds (e.g., WvW strips / boon-strip DPS missed) → false negatives in role column. | C.2 dictates corpus spans M=4 archetypes with N≥20 fights; calibration report reviewer enforces coverage before merge. |
| **Unstable R.1-R.4 inputs** | Calibration invalidated mid-cycle if an aggregator schema edits mid-flight. | Sequence C.2 strictly *after* R.1-R.4 aggregators freeze (see §3 ordering). Pin aggregator schema hashes in the calibration report. |
| **Multi-role UI bloat** | A player hitting 4+ role thresholds overflows AG Grid cell width → visual regression. | C.1 restricts classifier output to ≤3 roles per player (hard cap; tie-break by descending impact-share). C.3 tests the cap. |
| **Missing aggregator fields** | Classifier throws on partial EVTC parses (e.g., raid log missing the boons table). | C.3 hermetic tests probe `empty_rollups` + `missing_fields` gracefully (returns empty `set()`, never throws). |
| **TS surface drift from Python core** | TS wrapper in `web/src/lib/role-classifier.ts` desyncs from `libs/gw2_analytics.PlayerRoleClassifier` (role set diverges). | TS surface re-exports `ROLES = [...] as const` from a single source of truth; Python tests assert the same constant set; CI cross-checks parity. |

## §6 Done criteria

Blocker C is **DONE** when: `PlayerRoleClassifier.classify(per_player_roll_ups)` produces calibrated role sets in ≤3 roles / player across the 7-role contract, passes all boundary + multi-role + null-input hermetic tests, the C.2 calibration report is merged with M=4 / N≥20 coverage, AND `web/src/app/fights/[id]/page.tsx` (plus `PlayerReadoutBase.tsx`) drops the 2 SCAFFOLD-zero defaults so the UI auto-hydrates native role values for any log versioned under the post-Wave 3 aggregator schema.
