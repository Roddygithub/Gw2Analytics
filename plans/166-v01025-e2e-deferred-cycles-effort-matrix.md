# Plan 166 — v0.10.25+ — E2E-deferred cycles effort matrix + dependency graph

**Source:** Aggregation of `plans/160` / `161` / `162` / `163` / `164` / `165`
(post-E2E-JOURNEY `1813881`).
**Severity:** N/A (analysis doc — no code changes).
**Effort:** XS (analysis only).
**Drift base:** `1813881`.

## Scope

This plan enumerates the 6 E2E-deferred / carryforward cycles opened
in the v0.10.25 mimo-half wave + the cross-cycles they depend on.
It is the *operator handoff* — the table below is the single
source of truth for the next 4-6 mimo-half cycles.

## Effort + dependency matrix

| # | Plan | Severity | Effort | Files touched | Depends on | Blocks |
|---|------|----------|--------|---------------|-----------|--------|
| **159** | Timeline bucket guard `_MAX_BUCKETS=50_000` | HIGH | S ✅ DONE (`edacc4b`) | `libs/gw2_analytics/src/gw2_analytics/per_fight_timeline.py` | — | 164 |
| **160** | `fight_id` collision 409 vs idempotent | MED | S | `apps/api/src/gw2analytics_api/services/parse.py` + `tests/test_uploads_*.py` | Decision: (a) idempotent or (b) 409 | — |
| **161** | Per-section error isolation on `/fights/[id]` | MED (UX) | M | `web/src/app/fights/[id]/page.tsx` + `error.tsx` per segment | 164 (parser fix needed for non-empty sections) | 162 |
| **162** | `/timeline/players` lazy-load (~10s → fast) | LOW | M | `apps/api/src/gw2analytics_api/routes/fights/__init__.py` (lazy response) OR `web/src/app/fights/[id]/page.tsx` (client fetch after paint) | 161 (so SSR doesn't return 500-prone data) | — |
| **163** | `PlayerSearchBar` hydration mismatch | LOW | S | `web/src/components/PlayerSearchBar.tsx` + 1 CSS module extract | — | — |
| **164** | Parser `time_ms` normalization + skill-table re-read | HIGH | L | `libs/gw2_evtc_parser/src/gw2_evtc_parser/parser.py` + 2 hermetic tests | 159 (already done) | 161 (detection of bad data) |
| **165** | fight-events-page vitest migration | MED | M | `web/tests/app/_helpers/renderWithSession.ts` (NEW) + 6 test files | — | — |

## Recommended execution order

### Wave 1 (mimo-half budget: 2 cycles)

1. **#164 (parser fix)** + **#163 (search-bar hydration)** in PARALLEL.
   - #164 is HIGH severity and unblocks every other fight-detail UX fix
     (without it, fight detail still renders "Upstream error: 500").
   - #163 is free-floating S effort (frontend-only, no backend coupling).

2. **#160 (fight_id collision)** — needs an (a) vs (b) decision from
   the operator; otherwise small.

### Wave 2 (mimo-half budget: 2 cycles)

1. **#161 (section isolation)** + **#162 (timeline/players perf)** in PARALLEL.
   - Both are mid-effort (M), #161 is frontend-only, #162 spans backend+frontend.
   - Could ship in same PR but the review burden is high enough to split.

2. **#165 (fight-events-page migration)** — low coupling to the parser
   fix; can land anywhere in Wave 2.

### Suggested cal timeline

| Cycle | Plans to ship | Net cleanliness delta |
|-------|---------------|----------------------|
| v0.10.26-pre | #164 + #163 | Parser 500 → 200; hydration mismatch gone |
| v0.10.26 | #160 | 409 (or idempotent) on duplicate upload |
| v0.10.27 | #161 | Per-section error isolation on detail page |
| v0.10.27-bis | #162 | `/timeline/players` lazy-load |
| v0.10.28 | #165 | Vitest carryforward zero on fight-events-page |
| v0.10.29-pre | #159-cleanup + WAVE-8 Blocker A.4 | Statechange emit path |

## Operator handoff

- **479f3ac operator decision** (per plan 160): approve (a) idempotent
  or (b) 409 here, then plan 160 ships as-is.
- **All 5 plans (160/161/162/163/164) are NOT yet authorized to
  start mimo-half cycles** — they are queued as post-1813881
  carryforward, awaiting `RELEASE-v0.10.26-pre.md` sign-off.

## Audit-trail pointers

- Per-plan files: `plans/159..165` (this repo).
- Findings doc (rolled-up): `plans/E2E-JOURNEY-2026-07-11.md`.
- WAVE-8 cross-reference: `plans/WAVE-8-parser-side.md` (the
  statechange emit path is upstream of #164).
