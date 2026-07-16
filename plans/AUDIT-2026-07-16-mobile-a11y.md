# Mobile + A11y Audit — 2026-07-16

Pages audited: `/fights` (list + `[id]`), `/upload`, `/players` (list + `/players/compare`).

Severity: **critical** = fails WCAG AA or blocks mobile use; **moderate** = degrades experience but not blocking; **minor** = polish.

---

## Cross-cutting issues

| # | Severity | Description | Affects |
|---|----------|-------------|---------|
| X1 | critical | Nested `<main>` landmarks: layout.tsx wraps in `<div role="main">`, each page adds another `<main>`. Two main landmarks confuse screen-reader landmark navigation. | All pages |
| X2 | moderate | Zero `@media` queries or `clamp()` in inline styles across all pages. Fixed `padding: 32px` consumes 64px on a 320px viewport. | All pages |
| X3 | minor | `opacity: 0.7` used as a muted-color pattern (5+ instances). Fragile against theme changes; may drop below 4.5:1 contrast. A `--foreground-muted` CSS var would fix all at once. | `/fights/[id]`, `/players`, `/players/compare` |

---

## `/fights` — Fight list page

| # | Severity | Line | Issue | Fix |
|---|----------|------|-------|-----|
| F1 | critical | FightsGrid L70 | Fight-ID `<a>` contrast: `--link` is `rgba(255,255,255,0.38)` (~3.6:1 on `#050914`). Fails WCAG AA (4.5:1). | Bump `--link` to `rgba(255,255,255,0.52)` (~5.1:1). |
| F2 | critical | FightsGrid L70 | Fight-ID `<a>` has no `aria-label`. SR announces only raw ID hash. | Add `aria-label={`View fight ${id}`}`. |
| F3 | moderate | FightsGrid L121 | Grid height `600px` overflows short mobile viewports. | Use `height: min(600px, 70vh)`. |
| F4 | minor | FightsGrid L54 | Column `minWidth: 240` exceeds 320px viewport content area. | Lower to ~180 or ensure wrapper has `overflow-x: auto`. |

## `/fights/[id]` — Fight detail page

| # | Severity | Line | Issue | Fix |
|---|----------|------|-------|-----|
| D1 | moderate | page.tsx L452 | Error `<p>` missing `role="alert"`. SR doesn't announce fetch failures. | Add `role="alert"`. |
| D2 | minor | page.tsx L596-601 | Readout tab header: fixed padding, no responsive clamp. | Use `clamp(16px, 5vw, 32px)`. |

## `/upload` — Upload wizard

| # | Severity | Line | Issue | Fix |
|---|----------|------|-------|-----|
| U1 | moderate | CSS L316 | Spinner `rotate(360deg)` infinite animation with no `prefers-reduced-motion`. | Add `@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }`. |
| U2 | moderate | page.tsx L328-364 | Focus lost on every wizard step transition. Keyboard/SR users lose position. | Add `useRef` + `useEffect` to move focus to the new step heading. |
| U3 | minor | page.tsx L444-468 | File-rejection error not linked to input via `aria-describedby`. | Add `aria-describedby` + `id` on the error `<p>`. |
| U4 | minor | CSS L34 | `.title` font-size `40px` not responsive. | Use `clamp(1.75rem, 5vw, 2.5rem)`. |
| U5 | minor | CSS L124, L336 | Buttons hit 44px by a hair; browser-dependent. | Add explicit `min-height: 44px`. |

## `/players` — Players list

| # | Severity | Line | Issue | Fix |
|---|----------|------|-------|-----|
| P1 | critical | page.tsx L53-68 | CompareCta `<a>` touch target ~24px. Fails WCAG 2.5.8. | Increase padding to `"14px 16px"`, fontSize to `14`. |
| P2 | minor | page.tsx L118 | `opacity: 0.7` on description text — contrast risk. | Use `--foreground-muted`. |

## `/players/compare` — Compare page

| # | Severity | Line | Issue | Fix |
|---|----------|------|-------|-----|
| C1 | critical | L114-123, 162-171, 244-253 | "Back to players" `<a>` has zero padding — touch target ~18px. | Add `padding: "12px 0"`. |
| C2 | minor | L62-69 | Empty/hint text at `opacity: 0.7` — contrast risk. | Use `--foreground-muted`. |

---

## Prioritised fix order

1. **X1** — Nested `<main>` landmarks (layout-level, one fix for all pages)
2. **F1** — `--link` contrast bump (one-line CSS change, global)
3. **F2** — Fight-ID `aria-label` (one-line)
4. **P1** — CompareCta touch target (one-line)
5. **C1** — "Back to players" touch target (one-line × 3 branches)
6. **U1** — Spinner `prefers-reduced-motion` (3 lines CSS)
7. **U2** — Wizard focus management (~10 lines TSX)
8. **D1** — Error `role="alert"` (one-line)
9. **X2** — Responsive padding clamp (replace fixed values)
10. **X3** — `--foreground-muted` CSS var + replace opacity pattern

Items 1-5 are the highest-impact, lowest-effort fixes. Items 6-10 are moderate-effort polish.
