# Plan 024 — v0.9.6: `PlayerTimelineChart` forces `timeZone: "UTC"` to prevent React hydration mismatch

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/*.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`web/src/components/PlayerTimelineChart.tsx` (lines 50-60) constructs 2 `Intl.DateTimeFormat` instances WITHOUT an explicit `timeZone` option. The server (Node.js) defaults to UTC (process.env.TZ is empty in production); the client (browser) uses the analyst's local timezone. The formatter therefore produces different strings on server vs client for the same `started_at` input — e.g. `"07/07/26, 12:00"` on the server vs `"07/07/26, 08:00"` on the client (analyst in PT). React's hydration check fires and the entire timeline component re-renders (or throws in strict mode), causing a visible flash + warning in the console.

The fix: add `timeZone: "UTC"` to both `Intl.DateTimeFormat` calls so server and client agree deterministically. The chart's X-axis labels then always render in UTC — which is the canonical analyst contract (the day-bucketed points are at UTC midnight per the v0.8.1 + v0.8.9 contract).

The `PerFightTimelineChart` and `EventWindowsChart` likely have the same bug. A future plan can DRY the fix; this plan scopes the v0.9.6 fix to the highest-traffic surface (the player timeline).

---

## Files IN scope

- `web/src/components/PlayerTimelineChart.tsx` (2-line fix).
- `web/tests/components/player-timeline-chart.test.tsx` (add 1 timezone-determinism test).

## Files NOT in scope

- `web/src/components/PerFightTimelineChart.tsx` (likely same bug; deferred to a followup plan).
- `web/src/components/EventWindowsChart.tsx` (likely same bug; deferred).
- `web/src/components/TimelineChart.tsx` (the shared base; not the source of the issue).
- Server-side rendering of `Intl.DateTimeFormat` (the server's UTC default is correct; only the client is wrong without the explicit `timeZone` option).

---

## Current code (read from `44ea862`)

### `PlayerTimelineChart.tsx` (lines 50-60)

```typescript
const X_AXIS_LABEL_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  // ← no timeZone: server (UTC) and client (local TZ) disagree.
});
const X_AXIS_DAY_LABEL_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "2-digit",
  day: "2-digit",
  // ← no timeZone.
});
```

---

## Step-by-step

### Step 1 — Add `timeZone: "UTC"` to both formatters

REPLACE both `Intl.DateTimeFormat` constructors with:

```typescript
/**
 * v0.9.6 plan 024: explicit ``timeZone: "UTC"`` so server (Node)
 * and client (browser) agree deterministically. Without it, the
 * server defaults to UTC but the client uses the analyst's local
 * TZ, causing a React hydration mismatch on every page load.
 * The chart's contract is UTC-aligned (the day-bucketed points
 * are at UTC midnight per v0.8.1 + v0.8.9); the X-axis labels
 * match the contract.
 */
const X_AXIS_LABEL_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});
const X_AXIS_DAY_LABEL_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "2-digit",
  day: "2-digit",
  timeZone: "UTC",
});
```

### Step 2 — Tests

Add to `web/tests/components/player-timeline-chart.test.tsx`:

```typescript
describe("PlayerTimelineChart timezone determinism", () => {
  it("formats dates identically in UTC and any local TZ", () => {
    // v0.9.6 plan 024: the X-axis label format must NOT depend
    // on the local timezone. Snapshot a known timestamp under
    // multiple TZ environment values; assert the formatted
    // string is identical.
    const ts = "2024-01-15T12:34:00Z";
    const expectServer = "01/15, 12:34";  // UTC format
    const localResult = X_AXIS_LABEL_FORMAT.format(new Date(ts));
    expect(localResult).toBe(expectServer);
  });
});
```

The vitest test must run with `process.env.TZ = "America/Los_Angeles"` (or similar non-UTC TZ) to assert determinism — vitest config in `web/vitest.config.ts` may need a small update to set the env.

If TZ overrides are not feasible, the test can simulate by constructing the formatter twice with explicit `timeZone: "UTC"` + `timeZone: "America/Los_Angeles"` and asserting the chart's `X_AXIS_LABEL_FORMAT` matches the UTC one.

---

## Verification commands

```bash
pnpm typecheck
pnpm test:unit
# Expected: existing tests pass + 1 new test passes.
```

A worktree `git diff` against `44ea862` must show ONLY:
- `web/src/components/PlayerTimelineChart.tsx` (2 `timeZone: "UTC"` additions).
- `web/tests/components/player-timeline-chart.test.tsx` (add 1 test).

## Maintenance note

- The fix aligns the client with the server's existing UTC behavior. The chart's contract is UTC (per the v0.8.1 + v0.8.9 day-bucketing decisions); this plan makes the rendering match the contract.
- A future v0.9.6+ plan can extend the fix to `PerFightTimelineChart` and `EventWindowsChart` (likely same bug). Out of scope here; tracked for the next deep-audit pass.
- If a future plan adds a per-chart TZ selector (e.g. "render in user's local TZ"), the `timeZone` field becomes a prop. Out of scope here.

## Escape hatches

- If a future plan introduces a per-chart TZ preference, lift `timeZone: "UTC"` to a `formatTimeZone: string` prop with default `"UTC"`. The vitest test updates to assert the prop is threaded.
- If a downstream consumer (e.g. a third-party embed) requires local-TZ rendering, the same `timeZone` prop controls the formatter.
