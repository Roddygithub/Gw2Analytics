# Release v0.10.22 — Tour 4 Skill build analyser + per-player skill attribution

**Cycle:** v0.10.22 (the next cycle after the v0.10.21 M-8-bis substrate-rework cycle resumes).
**Marker commit SHA:** TBD at cycle-execution start (the atomic commit 1 of 6 serves as the marker; may precede with a `--allow-empty v0.10.22 cycle-window marker` if the maintainer's linear-history rule warrants).
**Cycle-end audit filename convention:** `plans/AUDIT-2026-07-XX-v0.10.22.md`.
**Inheritance:** This cycle ships the `Skill build analyser` design-doc item from `docs/ROADMAP.md` §1 v1.0 candidates (originally sourced from `docs/v0.8.0-web-design.md` §6 forward work). The item was provisioned as plan 044 in the advisor-plans/ numbering; this cycle is the FIRST attempt at closing it.

**Ordering note:** Tour 4 (this v0.10.22 plan) may ship BEFORE OR AFTER the v0.10.21 M-8-bis cycle. The tag compare-range URL `compare/v0.10.20...v0.10.22` is invariant under either ordering (Tour 4 does NOT touch `apps/api/tests/conftest.py` — the surface the v0.10.21 cycle modifies — so the merge-conflict surface area between the two cycles is ZERO). The wrapper deliverable ordering is preserved either way.

---

## §1 — Cycle thread (Tour 4 vs M-8-bis topology)

| Cycle | Phase | Output |
|---|---|---|
| v0.10.20 | main scope | M8 PARTIAL-FIX (5 atomic commits) + 12 TASK-Y forward-blockers at `plans/AUDIT-2026-07-13-v0.10.20.md` §4 |
| v0.10.21 | mimo-half M-8-bis pickup | The 12 v0.10.20 forward-blockers split as 4 true residues + 8 substrate/cycle-authoring items. Plan spec drafted at `plans/RELEASE-v0.10.21.md` |
| **v0.10.22** | **mimo-half Tour 4 (this plan)** | Skill build analyser per `docs/v0.8.0-web-design.md` §6. 6 atomic commits + this release plan + cycle-end audit + ROADMAP stamp refresh + CHANGELOG entry. **Forward-deferred non-blocking surface** (the Skill build analyser was never a TASK-Y item, so v0.10.21 M-8-bis cycle is unaffected by this release). |

**Decoupling note:** Tour 4 is INDEPENDENT of the M-8-bis substrate rework. The Skill build analyser does NOT touch `apps/api/tests/conftest.py` (the v0.10.20 PARTIAL-FIX surface); it ONLY adds new schemas + new route + new web components + new tests. A v0.10.21 mimo-half cycle can run BEFORE or AFTER v0.10.22 without merge-conflict surface area on the new endpoint, because the artisan route handler does NOT inherit the substrate rework (the new `/api/v1/fights/{id}/players/{account_name}/skills` route uses `_load_fight_events` — the SAME shared helper the pre-Tour-4 endpoints use).

---

## §2 — Sub-deliverables (Tour 4 surface, mimo-half is a single-cycle contiguous scope)

### 2.1 Backend (apps/api) — 3 atomic commits

| Order | Commit | Files | Why now |
|---|---|---|---|
| 1 | `feat(api): schemas — PlayerSkill*Out schema additions` | `apps/api/src/gw2analytics_api/schemas/fight.py` + `__init__.py` | Tour 4 step 1: the wire contract MUST land BEFORE the route (Pydantic-first contracts). |
| 2 | `feat(api): routes/fights — get_fight_player_skills artisan route handler` | `apps/api/src/gw2analytics_api/routes/fights/__init__.py` | Tour 4 step 2: the route depends on the schemas + the `SkillUsageAggregator` library wrapper from plan 117. |
| 3 | `test(api): test_fights_player_skills.py — 4 hermetic pytest cases` | `apps/api/tests/routes/test_fights_player_skills.py` (NEW) + `apps/api/tests/routes/_evtc_builder.py` (already shared) | Tour 4 step 3: the artisan route MUST be test-covered before the web integration. |

**Wire contract:**
- `GET /api/v1/fights/{fight_id}/players/{account_name}/skills` → `PlayerSkillsOut`
- 404 `fight not found` when `_load_fight_events` raises (the shared blob-loader canonical 404)
- 404 `player not found in fight` when the `OrmFightAgent` lookup returns None
- 200 `skills: []` when the agent row resolves BUT no events match the player's agent_id (the idle-player edge case)
- 100-row cap on `skills` (mirrors the v0.10.2 hotfix followup #12 cap pattern on `get_fight_skills`)

### 2.2 Frontend (web) — 3 atomic commits

| Order | Commit | Files | Why now |
|---|---|---|---|
| 4 | `feat(web): lib/api — fetchFightPlayerSkills + fetchFight + PlayerSkill* / AgentOut / SkillOut / FightOut types` | `web/src/lib/api/fights.ts` (3 types added BEFORE `FightEventsSummaryRow` + 2 types appended AT END + 2 functions appended AT END) + `web/src/lib/api/index.ts` (re-exports appended AFTER existing) | Tour 4 step 4: the TS contract surface mirrors the backend's `PlayerSkillsOut` + the bare `/fights/{id}` fetch (the existing `OrmFight` + agents) |
| 5 | `feat(web): PlayerSkillUsageTable + PlayerSkillUsageFilter + /fights/[id] ?account= integration` | `web/src/components/PlayerSkillUsageTable.tsx` (NEW Client Component) + `web/src/components/PlayerSkillUsageFilter.tsx` (NEW Client Component) + `web/src/app/fights/[id]/page.tsx` (extended with `parseAccount` helper + `accountFilter`/`<PlayerSkillUsageFilter>` retrieval + conditional `fetchFight` + conditional `fetchCached<PlayerSkills>` + new `<section>` between existing per-skill + event-windows) | Tour 4 step 5: the page is the Single Source of Truth for URL state; the page must accept the `?account=` filter + cascade it through to the per-player section.
| 6 | `test(web): vitest / mock-server / playwright test surface` | `web/tests/setup.ts` (2 component no-op mocks added) + `web/tests/components/player-skill-usage-table.test.tsx` (NEW, 10 cases) + `web/tests/components/player-skill-usage-filter.test.tsx` (NEW, 7 cases) + `web/tests/app/fight-events-page.test.tsx` (mockFightFetch extended with 2 new URL slots + regex URL match + 4 new page-test cases for Tour 4 surface) + `web/tests/e2e/mock-server.mjs` (2 NEW endpoint handlers + restored Stub payload comment) + `web/tests/e2e/fights.spec.ts` (3 NEW Playwright cases for Tour 4 wire surface) | Tour 4 step 6: full hermetic coverage at vitest + Playwright layers. |

**Component contract:**
- `<PlayerSkillUsageTable playerSkills={...} filename?={...} />` — pure-render Client Component; data-testids: `player-skill-loadout` / `player-skill-account` / `player-skill-table` / `player-skill-empty`. Empty-state contract: `skills.length === 0` renders `player-skill-empty` panel (matches the v0.8.0 §8.4 always-render pattern). CSV button visibility: `filename` provided AND `skills.length > 0` (AND-gate).
- `<PlayerSkillUsageFilter currentValue?={...} playerAgents={[...]} fightId={...} />` — URL-state Client Component mirroring the `ProfessionFilter` + `TargetFilter` precedent; data-testid: `player-skill-filter`. Empty-state contract: `playerAgents.length === 0` → `null` (the page renders its own placeholder). URL contract: `?account=NEW_VALUE` for selection, drop `?account=` for "All players".

**URL contract (the page-level integration):**
- `?account=TestAccount.1234` → the per-player section renders the loadout + the per-skill table + the CSV download button. The agent row matches `is_player === true && account_name === TestAccount.1234` (lenient contract: a malformed `?account=` falls back to the prompt placeholder, NOT a 404 page-level card).
- No `?account=` → the per-player section renders the "Pick a player from the dropdown to see per-player skill attribution" prompt placeholder.
- `?account=UnknownAccount.9999` (NOT in agents list) → the per-player section renders the section-level diagnostic chimp `player-skill-error` with "Player 'UnknownAccount.9999' not found in this fight" (NOT a page-level 404).
- Per-player fetch 502 / 404 → the section-level diagnostic chimp with the upstream error verbatim.
- Agents-fetch 502 / 404 → the section-level diagnostic chimp `player-skill-agents-error` cascading from the upstream error.

---

## §3 — Iteration budget

**Single-cycle mimo-half, single iteration budget, 6 atomic commits.**

**Why single iteration:**
- The backend surface is mechanical additions (3 classes + 1 route handler + 4 tests); no refactor.
- The frontend surface is mechanical additions (3 components + 1 fetcher + 1 URL contract extension); no refactor.
- The test surface is mechanical additions (2 vitest files + 1 page-test extension + 1 mock-server extension + 1 Playwright extension); no refactor of existing tests.

**Commit schedule:**

| # | Conventional prefix | Files | Atomicity surface |
|---|---|---|---|
| 1 | `feat(api)` | schemas/fight.py + __init__.py | The 3 NEW schema classes + the schema package re-export (added above existing `PerPlayerTimelineOut` declaration). |
| 2 | `feat(api)` | routes/fights/__init__.py | The 1 NEW artisan route handler + the imports of the 3 NEW schemas. |
| 3 | `test(api)` | tests/routes/test_fights_player_skills.py + (no edit to _evtc_builder.py — already shared) | The 4 NEW hermetic pytest cases. |
| 4 | `feat(web)` | lib/api/fights.ts + index.ts | 5 NEW TS types + 2 NEW functions + 5 NEW index.ts re-exports. |
| 5 | `feat(web)` | components/PlayerSkillUsageTable.tsx + components/PlayerSkillUsageFilter.tsx + app/fights/[id]/page.tsx | 2 NEW Client Components + 1 page.mdx edit (6 str_replace ops). |
| 6 | `test(web)` | tests/setup.ts + tests/components/player-skill-usage-table.test.tsx (NEW) + tests/components/player-skill-usage-filter.test.tsx (NEW) + tests/app/fight-events-page.test.tsx (extended) + tests/e2e/mock-server.mjs (extended) + tests/e2e/fights.spec.ts (extended) | 1 setup enhancement + 2 NEW vitest files + 2 EXISTING vitest file extensions + 2 e2e extensions. |

---

## §4 — Cycle-topology (single linear commit chain on main)

```
main (starting point: v0.10.21 M-8-bis close-out OR pre-v0.10.21)
  ├─ commit 1 (api schemas)        ─ schemas/fight.py + __init__.py
  ├─ commit 2 (api route)          ─ routes/fights/__init__.py
  ├─ commit 3 (api pytest)         ─ test_fights_player_skills.py (NEW)
  ├─ commit 4 (web fetcher+types)  ─ lib/api/fights.ts + index.ts
  ├─ commit 5 (web components)     ─ components/PlayerSkillUsageTable.tsx + PlayerSkillUsageFilter.tsx (NEW) + page.tsx (extended)
  ├─ commit 6 (web tests)          ─ tests/setup.ts + 2 NEW vitest + 2 page-test/Playwright extensions
  ├─ docs commit 7 (CHANGELOG)     ─ CHANGELOG.md
  ├─ docs commit 8 (ROADMAP)       ─ docs/ROADMAP.md
  ├─ docs commit 9 (audit)         ─ plans/AUDIT-2026-07-XX-v0.10.22.md (NEW)
  └─ tag v0.10.22 force-advance at cycle-end
```

**Branch policy:**
- All commits land DIRECTLY on `main` (per `CONTRIBUTING.md` linear-history rule).
- No WIP-branch decoupling required (Tour 4 is single-cycle, single-iteration, no F17-equivalent parallel sub-cycle).

---

## §5 — WIP branch lifecycle

**No WIP branch required.** This cycle is single-cycle, single-iteration. Tour 4 does NOT require a parallel sub-cycle (unlike v0.10.21's M-8-bis + F17 split).

**Anti-pattern (deliberately broken-by-design):**
- DO NOT land commit 5 BEFORE commit 6 (the page integration depends on the components being shippable; the tests in commit 6 would fail without commit 5).
- DO NOT split the test work from the page-integration work (the test surface is the contract that validates the page integration).

---

## §6 — Anti-drift + risk register

### 6.1 Anti-drift notes

1. **Submission order matches the schedule in §3**: commit 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → tag. Reordering risk: tests in commit 6 would FAIL if commit 5 is missing (the page imports `PlayerSkillUsageTable` from `@/components/PlayerSkillUsageTable` which doesn't exist until commit 5).
2. **Per-player loadout V1 stub is INTENTIONAL**: the equipped-skill extraction is deferred to v0.11.0 (a separate parser-layer ticket). The frontend's `PlayerSkillUsageTable.tsx` renders the empty-state panel with the canonical "(parser extraction deferred — see plan 044)" caption so the analyst sees the V1-stub status rather than mistaking it for "0 skills parsed".
3. **The "skill build analyser" item is REMOVED from §1 v1.0 candidates of ROADMAP** at cycle-end (it now lives in §1.1 cycle shipts + has the brief cross-reference to this release plan). The §5 anti-drift protocol mandates the move + the rationale.

### 6.2 Risk register

1. **Backend `aggregate_skill_usage` is unchanged** but pre-filtered via `[e for e in events if e.source_agent_id == player_agent.agent_id]`. Risk: a future event-stream change adds an extra `source_agent_id == 0` for non-attributed events which would silently leak "global" damage into the per-player rollup. Mitigation: a future guard ("drop events with source_agent_id == 0 from per-player rollups") is a v0.11.0 followup.

2. **The page.tsx uses `import("@/lib/api").FightOut`** as a dynamic type-import (rather than a static `import type`). Risk: a future refactor that changes the import surface in `web/src/lib/api/index.ts` would silently break the dynamic type-resolution. Mitigation: the v0.10.22 tests catch this via the `mockFightFetch` dispatch; the test failures would surface as TypeError on the page render rather than compile-time (already exercised by the 4 page-test cases).

3. **The `?account=` URL param is a STRICT-name match** (the page filters `a.account_name === accountFilter` byte-for-byte). Risk: a future analyst typing `?account=Testaccount.1234` (lowercase 't') would land on the section-level error chimp rather than the parseable view. Mitigation: a future case-insensitive contract is a v0.11.0 followup (the page should `decodeURIComponent(accountFilter.toLowerCase())` AND `a.account_name.toLowerCase()` for the comparison).

---

## §7 — Cross-references

- **Prior cycle audit chain:** see `CHANGELOG.md` for the v0.10.20 PARTIAL-FIX + v0.10.21 cycle-end audit (when authored) + v0.10.19 DEFER + v0.10.18.1 D2 vacuity + v0.10.18 + v0.10.17 + v0.10.15 + v0.10.14 + v0.10.13 + v0.10.11 cycle audits.
- **Design doc source (Skill build analyser):** `docs/v0.8.0-web-design.md` §6.
- **Pre-existing forward-blockers (NOT touched by this cycle):** `plans/RELEASE-v0.10.21.md` §2.1 + §2.2 (M-8-bis substrate + F17 parser extension).
- **Hardened cycle close-out script:** `apps/api/scripts/cycle_closeout_apply_docs.py`.
- **Smoke test for the close-out script:** `apps/api/tests/test_cycle_closeout_apply_docs.py`.

---

## §8 — Cycle-execution checklist (close-out time)

At the end of the v0.10.22 mimo-half cycle, the executor MUST verify:

1. `uv run pytest apps/api/tests/routes/test_fights_player_skills.py -v` → 4/4 PASS.
2. `uv run ruff check apps/api/src apps/api/tests apps/api/scripts` → 0 violations.
3. `uv run ruff format --check apps/api/src apps/api/tests` → 0 violations.
4. `uv run mypy apps/api/src libs/gw2_core/src libs/gw2_analytics/src libs/gw2_evtc_parser/src` → 0 errors in 74 source files.
5. `cd web && pnpm tsc --noEmit` → 0 errors (strict mode).
6. `cd web && pnpm vitest run` → 180+ tests green (162 v0.10.17 baseline + 17 NEW Tour 4 vitest cases).
7. `cd web && pnpm playwright test` → 28+ tests green (25 v0.10.18 baseline + 3 NEW Tour 4 Playwright cases).
8. `git diff --check` → clean (no whitespace + line-ending regressions).
9. Full-surface `cd apps/api && uv run pytest apps/api/tests/` → 252 + N green (where N = 4 NEW Tour 4 tests = 256 baseline).
10. CHANGELOG `[0.10.22]` entry spliced with §1 sub-section enumerating the 9 atomic commits.
11. ROADMAP "Current state" stamp refreshed AT v0.10.22 cycle close-out + §1.1 v0.10.22 cycle shipts sub-section appended with commit-level attribution.
12. ROADMAP §1 v1.0 candidates "Skill build analyser" item REMOVED (moved to §1.1 cycle shipts).
13. Cycle-end audit `plans/AUDIT-2026-07-XX-v0.10.22.md` authored with the standard 6-section structure (Executive Summary + §1 Cycle topology + §2 Tour 4 deliverables + §3 Validation matrix + §4 Cross-references + §A shipping-invariant).
14. Annotated tag `v0.10.22` + force-push + `gh release create` at <https://github.com/Roddygithub/Gw2Analytics/releases/tag/v0.10.22>.

---

## §9 — Forward-blocker handbook (multi-cycle)

When authoring a new cycle release plan that picks up previously-deploy forward-blockers (this cycle does NOT — Tour 4 is the FIRST delivery of the Skill build analyser; the only forward-blocker this cycle generates is the future-parser-layer extraction ticket pushed at v0.10.22 §6.1.2 + §6.2.1-3), enforce:

1. **Source-of-truth precedence:** a forward-blocker in the prior cycle's AUDIT doc is authoritative. Do NOT restate it in the new release plan; reference by file-path + section anchor.
2. **Two-tier attribution:**
   - **True test residuals** → must fix in the cycle's PRIMARY iteration budget; otherwise the cycle declares PARTIAL-FIX (not "completed").
   - **Substrate-improvement / cycle-authoring / future-cycle items** → may fold into close-out docs OR defer to a sibling sub-cycle.
3. **PARTIAL-FIX framing:** Tour 4 departs with **0 true residuals** (the 4 backend tests are NOT test-substrate residuals — they are backend hermetic tests for the new wire contract). PARTIAL-FIX framing does NOT apply. The only forward-blocker this cycle generates is the parser-layer equipped-skill extraction (deferred to v0.11.0 + the case-insensitive account-name + the source-agent-id-zero guard).

**This cycle's commitment:** v0.10.22 ships **0 true residuals** + **3 forward-blockers** carried to v0.11.0/v0.11.X (parser-layer equipped-skill extraction + compact-name case-insensitivity + source-agent-zero guard).
