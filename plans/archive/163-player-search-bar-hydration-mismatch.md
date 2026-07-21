# Plan 163 — `PlayerSearchBar` hydration mismatch

**Source:** E2E journey finding #7 (`plans/E2E-JOURNEY-2026-07-11.md`). **Severity:** LOW (frontend). **Effort:** S.

## Problem

Every page logs a React hydration-mismatch `console.error` originating from the `PlayerSearchBar` `<input>` inline `style` object: the server-rendered HTML and the client render disagree (server emits CSS **longhand** — `padding-top`, `border-*`, etc. — plus `caret-color: transparent`; client uses the **shorthand** `padding: "4px 8px"` / `border: "1px solid …"` and no `caret-color`). React can't patch it up ("This won't be patched up").

## Likely cause

An inline `style={{…}}` whose value differs between SSR and CSR — commonly a style computed from a value that isn't stable across server/client (or a browser/devtools-normalized readback), or a `caret-color` set only on one side. The header renders on every route, so the warning is global.

## Suggested fix

Make the input's style deterministic across SSR/CSR: move the static styles to a CSS module / class (preferred) instead of an inline object, or ensure the inline object is a stable module-level constant with no server/client branching and consistent shorthand-vs-longhand. Confirm the `console.error` is gone via the E2E `_diagnostics.json`. Frontend-only (`web/src/components/PlayerSearchBar.tsx`).
