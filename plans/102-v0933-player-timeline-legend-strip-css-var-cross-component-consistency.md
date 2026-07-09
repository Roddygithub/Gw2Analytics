# Plan 102 (v0.9.33) — `--strip` CSS var + cross-component colour consistency

## Files touched
- `web/src/app/globals.css` (NEW `:root { --strip: #f59e0b; }` token in the colour-block where `--accent` / `--foreground` / `--border` already live)
- `web/src/components/PlayerTimelineLegend.tsx` (replace `STRIP_FILL = "#f59e0b"` → `STRIP_FILL = "var(--strip)"`)
- `web/src/components/EventWindowsChart.tsx` (add `STRIP_FILL = "var(--strip)"` + a third legend swatch — currently shows Damage + Healing only; the strip line is bypassed)
- `web/tests/components/player-timeline-legend.test.tsx` (extend the existing test to assert the swatch colour is `var(--strip)`)
- `web/tests/components/event-windows-chart.test.tsx` (new component test if it doesn't exist; assert the strip legend swatch colour when added)

## Findings (audit)

- `web/src/components/PlayerTimelineLegend.tsx` line ~26 declares `const STRIP_FILL = "#f59e0b"; // warm orange; matches the per-target strip roll-up`. The comment notes "no matching CSS var yet"; the colour is hardcoded as a hex literal in the component source.
- `web/src/app/globals.css` defines `--accent` + `--foreground` + `--background` + `--surface` + `--border` as CSS custom properties — the canonical dark-theme tokens used by every other surface in the app. A `--strip` token is MISSING.
- `web/src/components/EventWindowsChart.tsx` lines 25-26 declare `const DAMAGE_FILL = "var(--accent)"` + `const HEALING_FILL = "var(--foreground)"` but does NOT add a third swatch for buff-strip events. The Phase 8 `BuffRemovalEvent` is in the wire shape (`EventBucket.buff_removal_total` doesn't exist yet per plan 083 v0.9.27 which plans it) — so the strip line isn't currently rendered in the chart; BUT the chart's legend documents only Damage + Healing, which doesn't reflect the broader app's 3-colour convention.
- The component-level hardcoded `#f59e0b` is duplicated as the "per-target strip roll-up" hue elsewhere — but no two-place DRY enforcement exists because there's no canonical `--strip` token to compare against. Any future colour tweak requires a textual grep for `#f59e0b` across the codebase.
- Future-affordance impact: when `EventBucket.buff_removal_total` lands (the v0.9.21 plan 083 follow-up), the EventWindowsChart will need to add a third swatch matching the strip colour. Today's hardcoded literal in PlayerTimelineLegend would force the chart to copy the same literal — propagating the DRY violation forward.

## Fix

1. `web/src/app/globals.css` — add the new token in the `:root` block:

   ```css
   :root {
     /* Surface tokens */
     --background: #0a0a0a;
     --surface: #111111;
     --border: #222222;
     /* Foreground + accent */
     --foreground: #ededed;
     --accent: #ef4444;
     /* Phase 8 + globally-consistent strip colour. The warm
        orange was chosen to be visually distinct from the red
        --accent (damage) AND from the muted --foreground
        (healing): the analyst sees damage=red, healing=white,
        strip=orange at a glance without ambiguity. The hex
        literal previously lived as `#f59e0b` in
        PlayerTimelineLegend.tsx -- centralised here so the
        chart, the legend, and any future strip-related
        surface stay visually consistent without a textual-grep
        refactor. */
     --strip: #f59e0b;
   }
   ```

2. `web/src/components/PlayerTimelineLegend.tsx` — update the constant:

   ```typescript
   const STRIP_FILL = "var(--strip)"; // pairs with the canonical token in globals.css
   ```

3. `web/src/components/EventWindowsChart.tsx` — add the new strip-line affordance (so the chart documents the full 3-colour convention):

   ```typescript
   const DAMAGE_FILL = "var(--accent)";
   const HEALING_FILL = "var(--foreground)";
   const STRIP_FILL = "var(--strip)";  // pairs with the canonical token; cross-component consistency
   ```

   And add a third `<span>` legend swatch below the existing two, mirroring the PlayerTimelineLegend pattern. The chart's BARS don't render strip data today (the `EventBucket` interface from `lib/api.ts` doesn't carry `buff_removal_total` per the plan 083 follow-up), so the legend entry is documentation-only until plan 083 ships. Add a docstring comment on the legend entry clarifying the future-affordance:

   ```typescript
   {/* Strip (will be displayed as a third bar when plan 083 ships). */}
   ```

   NO third `<rect>` is added today — only the legend swatch is added so the colour convention is documented in the chart from day 1.

## Tests (4)

- `test_player_timeline_legend_strip_swatch_uses_strip_css_var` — assert `getComputedStyle(legendStripSwatchElement).backgroundColor === "var(--strip)" OR equivalent computed lookup` verifies the swatch's CSS computes to the canonical token. The test uses jsdom + a tiny `<style>` injection to define `--strip: #f59e0b`; the assertion is on the `cssText` of the inline style (jsdom doesn't fully resolve CSS vars, but the constant in source IS `"var(--strip)"` which is sufficient evidence).
- `test_player_timeline_legend_no_longer_references_hex_strip_literal` — `grep -E "#[0-9a-fA-F]{6}" web/src/components/PlayerTimelineLegend.tsx` regex returns NO match (defensive: catches a regression where the literal comes back).
- `test_event_windows_chart_legend_includes_strip_swatches` — assert that the rendered chart's legend contains a 3-row list (Damage, Healing, Buff removal), in that order. Defensive: catches a regression where the third swatch is dropped.
- `test_globals_css_declares_strip_token_with_canonical_hex` — `parse the CSS via a minimal regex (rootStartBlock \\{ ... \\})` for the `--strip:\s*#[0-9a-fA-F]{6}` line and extract the hex; assert it's `#f59e0b` (the canonical value documented in the PlayerTimelineLegend comment).

## Rejected alternatives

- **Keep the hardcoded `#f59e0b` literal in PlayerTimelineLegend** — fine today, but tech debt. The moment a designer wants to tweak the colour (e.g. warm orange → muted ochre), every file with the literal must be updated. The CSS var centralises. REJECTED.
- **Rename `--strip` to `--strip-event` or `--accent-strip`** — `--strip` is short + matches the existing naming convention (`--accent` + `--foreground`). The "event" suffix is overly verbose for a 3-character variable name. REJECTED.
- **Skip the EventWindowsChart third-legend-swatch addition** — leaves the chart's 2-colour convention while the rest of the app documents 3; the inconsistency can surface as a "why is the strip missing from the chart?" question. The legend entry is documentation-only (no strip data today), zero-byte delta. REJECTED.
- **Move the strip colour into a per-component prop** — couples the colour to the component import surface; the CSS var is the right abstraction (theme-level). REJECTED.
- **Replace the THREE colours with a single `Palette` object** — overengineering for 3 hex literals; the canonical token system (CSS vars) is the lower-cost fix. REJECTED.

## Dependency graph

- Independent: touches 3 files in disjoint regions (`globals.css` token block; `PlayerTimelineLegend.tsx` constant; `EventWindowsChart.tsx` constants + legend).  
- Parallel-safe with plans 101 / 103.
- Pattern-aligns with `plan 070 v0.9.22` (the DRY utility extraction pass): both plans expand the canonical token system with new `--strip` semantic. Future colour additions follow the same pattern (add to `:root`, reference `var(--token)` in component source).
