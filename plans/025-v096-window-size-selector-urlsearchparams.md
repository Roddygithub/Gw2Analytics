# Plan 025 — v0.9.6: `WindowSizeSelector` preserves other URL query params when updating `window_s`

**Author:** senior-advisor audit (improve skill, standard effort) — deep audit of libs/* + web/*.
**Drift base:** `44ea862`.
**Repo root:** `/home/roddy/Gw2Analytics`.
**Audience:** executor model with NO prior context.

---

## Why this matters

`web/src/components/WindowSizeSelector.tsx` (line 94) builds the next URL via string concat:
```typescript
const next = value === String(WINDOW_S_PRESETS[1])
  ? pathname
  : `${pathname}?window_s=${value}`;
```

If the analyst has an active sub-filter (e.g. `?target=123` on the fight drilldown) and changes `window_s`, the new URL is `${pathname}?window_s=5` — the `?target=123` filter is **silently dropped**. The analyst's "filter to target X" workflow is broken every time they tweak the window size.

Fix: use Next.js's `useSearchParams()` hook + `URLSearchParams` to preserve all current query params, updating only `window_s`. The `?target=123` filter (and any other active filter) survives the URL rewrite.

---

## Files IN scope

- `web/src/components/WindowSizeSelector.tsx` (refactor `onChange` to use `useSearchParams` + `URLSearchParams`).
- `web/tests/components/window-size-selector.test.tsx` (update existing test + add 1 preservation test).

## Files NOT in scope

- Other URL-driven selectors (`ProfessionFilter`, `PlayerSearchBar`, `TargetFilter`) — they may have the same bug; out of scope for this plan, but a followup v0.9.6+ plan could DRY the pattern.

---

## Current code (read from `44ea862`)

### `WindowSizeSelector.tsx` (lines 65-95)

```typescript
import { useRouter, usePathname } from "next/navigation";
...
export function WindowSizeSelector({ current, fightId }: WindowSizeSelectorProps) {
  const router = useRouter();
  const pathname = usePathname() ?? `/fights/${fightId}`;
  return (
    <label ...>
      <span>Window (s):</span>
      <select
        data-testid="window-s-selector"
        value={current}
        onChange={(e) => {
          const value = e.target.value;
          // BUG: string concat drops any other active query
          // params (e.g. ?target=123 on the fight drilldown).
          const next =
            value === String(WINDOW_S_PRESETS[1])
              ? pathname
              : `${pathname}?window_s=${value}`;
          router.push(next);
        }}
        ...
      >
        ...
      </select>
    </label>
  );
}
```

---

## Step-by-step

### Step 1 — Add `useSearchParams` import

REPLACE the imports:
```typescript
import { useRouter, usePathname, useSearchParams } from "next/navigation";
```

### Step 2 — Refactor the component body

```typescript
export function WindowSizeSelector({ current, fightId }: WindowSizeSelectorProps) {
  const router = useRouter();
  const pathname = usePathname() ?? `/fights/${fightId}`;
  const searchParams = useSearchParams();

  return (
    <label ...>
      <span>Window (s):</span>
      <select
        data-testid="window-s-selector"
        value={current}
        onChange={(e) => {
          const value = e.target.value;
          // v0.9.6 plan 025: build a new URLSearchParams from the
          // current state + update only the window_s key. This
          // preserves any other active query params (e.g. the
          // ?target=123 sub-filter on the fight drilldown). When
          // the user picks the default (5 s), delete the
          // window_s key so the URL stays canonical (no
          // ?window_s=5 entry in the back-button history).
          const next = new URLSearchParams(searchParams.toString());
          if (value === String(WINDOW_S_PRESETS[1])) {
            next.delete("window_s");
          } else {
            next.set("window_s", value);
          }
          const queryString = next.toString();
          const url = queryString ? `${pathname}?${queryString}` : pathname;
          router.push(url);
        }}
        ...
      >
        ...
      </select>
    </label>
  );
}
```

### Step 3 — Tests

Update `web/tests/components/window-size-selector.test.tsx`:

1. The existing test should still pass (the default case — picking 5s — produces a bare-pathname URL via the new branch).
2. Add 1 new test:

```typescript
it("preserves other active query params when changing window_s", async () => {
  // v0.9.6 plan 025: changing window_s must NOT drop other
  // active query params (e.g. the target sub-filter on the
  // fight drilldown). Mock useSearchParams to return a
  // pre-existing ?target=123, then change window_s, assert
  // the resulting URL contains BOTH ?target=123 and ?window_s.
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams("target=123&window_s=5"),
  );
  // ... render + click the dropdown + change to 30s ...
  // Assert router.push called with a URL containing both params.
  expect(mockRouterPush).toHaveBeenCalledWith(expect.stringContaining("target=123"));
  expect(mockRouterPush).toHaveBeenCalledWith(expect.stringContaining("window_s=30"));
});
```

---

## Verification commands

```bash
pnpm typecheck
pnpm test:unit
# Expected: existing tests pass + 1 new test passes.
```

A worktree `git diff` against `44ea862` must show ONLY:
- `web/src/components/WindowSizeSelector.tsx` (1 import + ~5 lines of refactor in `onChange`).
- `web/tests/components/window-size-selector.test.tsx` (add 1 test).

## Maintenance note

- The fix uses Next.js's `useSearchParams()` hook which is `null` during the first server-render tick. The component is `"use client"` so this is not a concern at runtime, but the `searchParams.toString()` call handles the empty case naturally (the `?window_s=N` URL is the only thing in the new state).
- The same pattern (`new URLSearchParams(searchParams.toString())` + update single key) is reusable for `ProfessionFilter` and `TargetFilter` if they have the same bug. A future v0.9.6+ plan could DRY the pattern into a `useFilteredQueryParam` hook.
- The `?window_s=5` deletion (when the user picks the default) keeps the URL canonical — the back-button doesn't accumulate `?window_s=5` entries for the default case.

## Escape hatches

- If a future plan needs to redirect (vs push) on `window_s` change, swap `router.push(url)` for `router.replace(url)`. Out of scope here.
- If a future plan adds a "reset all filters" button, add a `next.clear()` after the per-key update. Out of scope.
