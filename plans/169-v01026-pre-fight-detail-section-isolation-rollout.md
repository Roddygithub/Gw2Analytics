# Plan 169 — Per-section error isolation on `/fights/[id]` — Implementation rollout spec

**Source:** Decomposition of `plans/161-fight-detail-section-isolation.md` (opened in commit `1813881` as a problem statement + suggested-fix sketch) into an implementable M-effort rollout spec. This plan carries the actual file-by-file breakpoint so a future executor does not rebuild the plan from scratch.

**Severity:** MED (UX clarity — E2E-journey finding #4).
**Effort:** M (≈140 LoC across 5 files: 1 NEW chip component, 1 NEW pilot regression-guard, 4 NEW per-section subcomponents replacing monolith page.tsx).
**Drift base:** Post commit `20b2bd6` (the cycle's HEAD before this plan lands).
**Cycle anchor:** Wave 2 — v0.10.26 per `plans/167-v01026-pre-cycle-anchor.md`.
**Depends on:** `plans/164-v01025-parser-time-ms-normalization.md` Stage 2 (closes the upstream `time_ms` ordering root cause for E2E-journey finding #2) ships FIRST OR in parallel. If 164 defers, 169 defers with it (the section-isolation benefit is moot if the upstream 500 is from a parser bug).

## Goal

Decouple the per-section fetches (`/events`, `/squads`, `/skills`, `/timeline`, `/timeline/players`) on `/fights/[id]` so each renders **independently**. Sections whose upstream returned 200 continue to render normally; the failing section shows an inline "this section is unavailable" chip. The page-level header + nav + section headings render in BOTH paths.

## Current architecture (problem statement)

Read `web/src/app/fights/[id]/page.tsx` to ground in the current shape:
- Page-level fetch: ~5 fetch calls wrapped in `Promise.allSettled(...)` then a single `try/catch` around the page's server-component entry.
- A single `error.tsx` (at the segment level) catches any uncaught throw → the page-level chrome is replaced by the "Upstream error: 500" full-page layout.
- If ANY of the 5 fetches throws (e.g. `/events` → 500 on a non-normalized `time_ms` per finding #2), the entire page renders the error boundary. Sections whose fetch succeeded are silently discarded.

## Target architecture (2 options)

### Option 1: per-section subcomponents + inline error chip

Decomposition:
- `web/src/app/fights/[id]/sections/EventsSection.tsx` (NEW) — exports `async function EventsSection({ base, qs }: { base: string; qs: string })`. Internally: `try { return <EventsRollupTable data={await fetchEvents()} />; } catch (e) { return <SectionErrorChip testid="events-section-error" message={e.message} />; }`.
- `web/src/app/fights/[id]/sections/SquadsSection.tsx` (NEW) — same shape for `/squads`.
- `web/src/app/fights/[id]/sections/SkillsSection.tsx` (NEW) — same shape for `/skills`.
- `web/src/app/fights/[id]/sections/PlayerTimelineSection.tsx` (NEW) — same shape for `/timeline/players`.
- `web/src/app/fights/[id]/sections/PerFightTimelineSection.tsx` (NEW) — co-located expansion of the existing `web/src/components/PerFightTimelineSection.tsx` (currently auto-nulls silently on fetch fail) to surface a chip on fail.

`page.tsx` refactor: each section call becomes `<Sections.X base={base} qs={qs} />` inside `Promise.all` (NOT `Promise.allSettled` — each section's own try/catch handles its own error path; the page-level fetch orchestrator is unchanged).

Shared UI:
- `web/src/components/SectionErrorChip.tsx` (NEW) — shared chip component carrying `{ testid: "section-error-chip-{name}" }` + `message` prop. ~30 LoC. Visual: bordered red panel with testid-stamped message span. Pairs cleanly with the existing page-level error chip pattern at `web/src/app/fights/[id]/error.tsx`.

### Option 2: per-segment `error.tsx` files (Next.js App Router convention)

Next.js App Router supports a per-segment `error.tsx` file (one per route subdirectory). Decomposition:
- `web/src/app/fights/[id]/events/page.tsx` + `error.tsx` (NEW directory) — fetches `/events`, error.tsx renders on throw.
- Same for the other 4 sections.
- `web/src/app/fights/[id]/page.tsx` orchestrates with 5 child route imports.

**Tradeoff**: Option 2 requires more file proliferation (5 NEW directories × 2 files each) but the error boundary matches the Next.js convention. Option 1 has fewer files (one NEW file per section + one shared chip) but the error UI lives in-component.

**Recommendation: Option 1.** The existing codebase already uses an in-component section-level error chip on the per-player section (`PlayerSkillUsageErrorChip` at `web/src/components/PlayerSkillUsageFilter.tsx` lines ~38–80). Re-using the same pattern across all 5 sections keeps the error UI consistent + the file count lower. Plus Option 1 composes naturally with plan 168's `renderWithSession` helper for per-section tests (no segment-by-segment boundary crossing).

## Migration path (5 atomic commits)

Order matters — commits 1 + 2 establish the foundation, 3 + 4 are the bulk of the refactor, 5 is the regression guard:

1. **`feat(web): add SectionErrorChip component`** — `web/src/components/SectionErrorChip.tsx` (NEW, ~30 LoC) + `web/tests/components/section-error-chip.test.tsx` (NEW pilot, ~20 LoC). Establishes the shared UI element before any caller uses it.
2. **`refactor(web): extract EventsSection + use in page.tsx`** — `web/src/app/fights/[id]/sections/EventsSection.tsx` (NEW) + slim down `page.tsx` by ~80 LoC. Test: extend `fight-events-page.test.tsx` with `it("renders the events section chip when /events throws")` case.
3. **`refactor(web): extract SquadsSection`** — same shape as #2 (commit batch not split because pattern is mechanical).
4. **`refactor(web): extract SkillsSection + PlayerTimelineSection + PerFightTimelineSection`** — batched 3-section extraction in one commit (all share the same pattern + reduce per-commit overhead).
5. **`test(web): pilot per-section isolation`** — `web/tests/app/fight-events-page-error.test.tsx` NEW (~30 LoC) reproducing the original E2E-journey finding #4 regression net. Three `it()` bodies cross-cutting all 4 sections + ensuring the page-level chrome (header + nav) renders in ALL cases.

## Test strategy (cumulative)

- `web/tests/components/section-error-chip.test.tsx` (commit #1): pilot for the chip UI element itself.
- Extend `web/tests/app/fight-events-page.test.tsx` (commit #2): add the per-section error case for `EventsSection`.
- `web/tests/app/fight-events-page-error.test.tsx` NEW (commit #5): the regression guard. Three test bodies cross-cutting:
  - (a) `/events` fails → events section chip renders + squads+skills+timelines render normally.
  - (b) `/squads` fails → squads chip + others render.
  - (c) `/timeline` fails → timeline chip + others render.
- The pilot `web/tests/components/_smoke/renderWithSession.test.tsx` (plan 168 Bullet 1) validates the helper used by these new section tests.

## Acceptance criterion

`pnpm vitest run tests/app/fight-events-page-error.test.tsx tests/app/fight-events-page.test.tsx` returns **0 failing tests** + master audit's "fight-events-page" vitest failure row is removed on the next audit pass + the original E2E-journey finding #4 is closed.

## Acknowledged constraints

- **Wall-clock cost**: ~140 LoC across 5 commits takes ~half a cycle (per the v0.10.x cycle rhythm). Each commit must validate independently (no broken state at end of any commit). Plan 167's Wave-2 budget accommodates this.
- **Risk**: the section-level error UI must NOT cascade to the page-level `error.tsx` — so each section's `try/catch` must catch `Error`-class exceptions (NOT re-throw as `Promise` rejections). Pre-flight: verify the section subcomponents do not propagate via `throw` outside their own try block.

## Execution budget

Total ~140 LoC. Single mimo-half cycle (Wave 2 — v0.10.26). Operator handoff: see `plans/167` under "Wave 2 — v0.10.26" + the cycle delta includes this plan 169 + plan 162 (lazy-load timeline/players).
