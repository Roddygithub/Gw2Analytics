# Plan 035 — v0.10.15: per-section partial-failure UI surface on `web/src/app/fights/[id]/page.tsx`

**Status:** open
**Priority:** P2
**Impact:** MED (UX)
**Confidence:** 1.0

## Finding

`web/src/app/fights/[id]/page.tsx` (verified) fetches 5 sibling
sections via `Promise.allSettled`:

```ts
const results = await Promise.allSettled([
  fetchCached<FightEventsSummaryRow>(`${base}/events${qs}`),
  fetchCached<FightSquads>(            `${base}/squads`),
  fetchCached<FightSkills>(            `${base}/skills`),
  fetchCached<FightTimeline>(          `${base}/timeline${qs}`),
  fetchCached<FightPlayerTimeline>(    `${base}/timeline/players${qs}`),
]);
```

The current error handler surfaces ONLY `results[0]` rejection
as `fetchError` and short-circuits the entire page. The other
4 sections' failures are silently swallowed — an analyst who
navigated to a deeply-encoded fight id sees 4 empty grids with
no diagnostic.

The page already depends on `formatApiError` (imported on line
36). The per-section error case is a one-record addition to the
existing affordance.

## Fix

Replace the single `fetchError` accumulator with a
per-section error map:

```diff
- let fetchError: string | null = null;
+ // Per-section error surface: each failed fetch gets its own
+ // diagnostic in the wire contract (the ``fetchError`` was the
+ // page-level error before; the per-section map preserves the
+ // partial-failure UX where an analyst sees which sections
+ // failed, not just that one failed).
+ type SectionKey = "events" | "squads" | "skills" | "timeline" | "playerTimeline";
+ const sectionErrors: Partial<Record<SectionKey, string>> = {};
  const base = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(id)}`;
  const qs = windowS !== 5 ? `?window_s=${windowS}` : "";
  const results = await Promise.allSettled([
    fetchCached<FightEventsSummaryRow>(`${base}/events${qs}`),
    fetchCached<FightSquads>(            `${base}/squads`),
    fetchCached<FightSkills>(            `${base}/skills`),
    fetchCached<FightTimeline>(          `${base}/timeline${qs}`),
    fetchCached<FightPlayerTimeline>(    `${base}/timeline/players${qs}`),
  ]);
- if (results[0].status === "fulfilled") {
-   summary = results[0].value;
- } else {
-   fetchError = formatApiError(results[0].reason);
- }
- if (results[1].status === "fulfilled") { squads = results[1].value; }
- if (results[2].status === "fulfilled") { skills = results[2].value; }
- if (results[3].status === "fulfilled") { timeline = results[3].value; }
- if (results[4].status === "fulfilled") { playerTimeline = results[4].value; }
+ ([summary, squads, skills, timeline, playerTimeline] = [
+   results[0], results[1], results[2], results[3], results[4],
+ ].map((r, i) => {
+   const key: SectionKey = ["events","squads","skills","timeline","playerTimeline"][i];
+   if (r.status === "fulfilled") return r.value;
+   sectionErrors[key] = formatApiError(r.reason);
+   return null;
+ }));

- if (fetchError || !summary) {
-   return (
-     <main> ... <p style={{ color: "var(--accent)" }}>{fetchError}</p> </main>
-   );
- }
+ if (!summary) {
+   // The events endpoint is the only "blocking" fetch -- the
+   // per-target roll-ups + per-bucket event_windows are
+   // derived from the same blob upstream. Other section
+   // failures are non-blocking; we render the partial-failure
+   // UI below.
+   return (
+     <main> ... <p style={{ color: "var(--accent)" }}>
+       Events unavailable: {sectionErrors.events ?? "unknown error"}
+     </p> </main>
+   );
+ }
```

In each section's render block, add:

```diff
 <section style={...}>
   <h2>Per-subgroup (squad)</h2>
+  {sectionErrors.squads && (
+    <p style={{ color: "var(--accent)", fontSize: 14 }}>
+      Failed to load squads: {sectionErrors.squads}
+    </p>
+  )}
   <SquadRollupsGrid rows={squads?.squads ?? []} ... />
 </section>
```

The chips are intentionally low-emphasis (fontSize 14, var(--accent)) — the section still renders with empty data so the analyst can correlate "this failed" with specific UI affordances.

## Tests

| Test | File | Type |
|------|------|------|
| `test_fights_page_partial_failure_renders_errors` (NEW) | `web/tests/app/fights-partial-failure.test.tsx` | vitest |
| `test_fights_page_all_succeed_renders_no_chip` (NEW) | `web/tests/app/fights-partial-failure.test.tsx` | vitest |
| `test_fights_page_events_failure_blocks_page` (NEW) | `web/tests/app/fights-partial-failure.test.tsx` | vitest |

The new vitest tests use `vi.mock('@/lib/fetchCached', ...)`
to inject per-section rejections; the page is rendered with
`<FightEventsPage>` inside a test harness.

## Out of scope

- A per-section retry button (defer to v0.10.16+; the chip
  surfaces WHY the section failed, which is the UX floor).
- A dedicated `ErrorBoundary` wrapper (Next.js 16
  `error.tsx` boundaries work above the render boundary;
  per-section fails need per-section handlers as designed
  here).

## Done criteria

- `pnpm typecheck` GREEN
- `pnpm test:unit` GREEN
- New vitest tests PASS
- Manual smoke: page with `?fight_id=<bad>` shows the
  pre-existing "Events unavailable" 4-hundred-char error
  message; page WITH fights shows no error chip on the
  per-target roll-up trio + an empty grid for squads (if
  squads fails alone).

## Maintenance note

The 5-key tuple in the `[summary, ...]` destructure is index-coupled
with the `results` array. If a future section is added, BOTH the
`results` array AND the `SectionKey` type AND the type-cast tuple
must update. Add a runtime assertion:

```ts
const sectionLabels: SectionKey[] = ["events","squads","skills","timeline","playerTimeline"];
if (results.length !== sectionLabels.length) throw new Error(`fights/[id] Promise.allSettled length mismatch: results=${results.length} expected=${sectionLabels.length}`);
```

ONCE at module-load time (cheap) so a future maintainer's
section addition surfaces the mismatch immediately.

## Escape hatches

- For analyst browsers: `?failAllSections=1` query param can be
  added as a force-fail helper for QA. Out of scope here;
  flag for v0.10.16.

## Dependency graph

- Depends on `web/src/lib/fetchCached` (D2 v0.10.14 deliverable).
- Standalone otherwise.

## Cross-references

- Finding sourced from `plans/AUDIT-2026-07-12-5d0d4d4.md` §"Open
  findings" O4.
- Audit doc rejected alternative: `error.tsx` boundary approach
  loses per-section granularity (documented in audit doc §Rejected).
