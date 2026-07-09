# Plan 069 — v0.9.22: a11y — `prefers-reduced-motion` + `:focus-visible` across CSS files

## Drift base

`44ea862`. A11y cleanup only — additive, no migration. The
visual output is unchanged for users without the
`prefers-reduced-motion: reduce` preference; the focus
indicators are added for keyboard users.

## Surface

`web/src/app/globals.css`,
`web/src/app/page.module.css`,
`web/src/app/upload/page.module.css`.

## Finding (part 1: no `prefers-reduced-motion` handling)

The CSS has multiple motion effects:
- `page.module.css::.card` has `transition: transform 0.15s ease-in-out`
  + `:hover { transform: translateY(-2px); }`.
- `upload/page.module.css::.fileChip` has `transition:
  border-color 0.15s ease-in-out, background 0.15s ease-in-out`.
- `upload/page.module.css::.submit` has `transition: background
  0.15s ease-in-out`.
- `globals.css::a` has `transition: opacity 0.15s ease-in-out`.
- `page.module.css::.card` has `:hover { border-color: var(--accent); }`
  with the border-color transition (also a motion effect).

None of these are gated on `prefers-reduced-motion: reduce`.
A user with the OS-level "Reduce motion" preference
(macOS System Settings → Accessibility → Display → Reduce
motion, Windows Settings → Accessibility → Visual effects →
Animation effects, iOS Settings → Accessibility → Motion →
Reduce motion) sees the same animations + transitions as
everyone else.

The WCAG 2.1 §2.3.3 (Animation from Interactions, AAA)
recommends disabling non-essential motion for users who
prefer reduced motion. The CSS Media Queries Level 5
`prefers-reduced-motion` is the canonical way to gate.

## Finding (part 2: no explicit `:focus-visible` outline)

The CSS has no explicit `:focus-visible` style. The
browser default focus outline (the blue ring on Chrome /
Firefox / Safari) is preserved (the CSS doesn't reset
`outline` to `none`), but:
- The `*` selector in `globals.css` resets `padding`,
  `margin`, `box-sizing` but NOT `outline`. So the browser
  default applies.
- The browser default focus outline is inconsistent across
  browsers (Chrome shows a blue ring, Firefox shows a
  dotted ring, Safari shows a blue ring with offset). The
  design system cannot control the focus indicator without
  an explicit `:focus-visible` rule.
- A keyboard user navigating the site (Tab key) sees the
  browser default focus ring on links, buttons, and form
  inputs. The focus ring is the canonical a11y signal for
  keyboard users (WCAG 2.1 §2.4.7, Focus Visible, AA).

The `upload/page.module.css::.fileChip:focus-within` is a
good a11y pattern (the chip gets a focus outline when the
visually-hidden input is focused) but it's a one-off — the
rest of the focusable elements (links, buttons) rely on
the browser default.

## Fix

1. **Add `prefers-reduced-motion` media query** in
   `globals.css`:

   ```css
   @media (prefers-reduced-motion: reduce) {
     *,
     *::before,
     *::after {
       animation-duration: 0.01ms !important;
       animation-iteration-count: 1 !important;
       transition-duration: 0.01ms !important;
       scroll-behavior: auto !important;
     }
   }
   ```

   The `!important` is needed to override the per-component
   `transition: ... 0.15s ...` rules (the cascade order
   matters; `!important` is the canonical pattern for
   `prefers-reduced-motion` per the MDN docs).

2. **Add explicit `:focus-visible` styles** in
   `globals.css`:

   ```css
   :focus-visible {
     outline: 2px solid var(--accent);
     outline-offset: 2px;
   }

   a:focus-visible {
     /* Override the default opacity hover for keyboard nav */
     opacity: 1;
   }
   ```

   The `:focus-visible` (not `:focus`) is the canonical
   pattern (`:focus-visible` only applies to keyboard
   focus, not mouse focus; the mouse user doesn't see a
   ring on every click).

3. **Override the `.fileChip:focus-within` style** in
   `upload/page.module.css` to use the canonical
   `--accent` ring (already in the current code):

   ```css
   .fileChip:focus-within {
     border-color: var(--accent);
     outline: 2px solid var(--accent);
     outline-offset: 2px;
   }
   ```

   The existing code already has this rule; the plan
   keeps it as-is (no change). The canonical `:focus-visible`
   in `globals.css` is the fallback for the file input's
   parent chip.

4. **Document the a11y intent** in `globals.css` with a
   comment block at the top of the file.

## Why `0.01ms` (not `0s`)

`0.01ms` is the canonical pattern per the MDN docs §
"prefers-reduced-motion". The `0s` would completely remove
the transition (some browsers + some JS-driven animations
rely on the `transitionend` event to fire; a `0s` transition
may not fire the event correctly). The `0.01ms` is a
near-zero duration that preserves the event semantics while
visually disabling the motion.

## Why the `*::before, *::after` selectors

The `*, *::before, *::after` selector catches:
- The element's own transition
- The element's `::before` and `::after` pseudo-element
  transitions (e.g., a `::before` content that fades in
  on hover)
- Any child element's transition (the `*` selector applies
  to all descendants)

## Risks

- The `!important` is heavy-handed but canonical. A future
  audit may flag the `!important` as a smell, but the
  `prefers-reduced-motion` pattern is the documented
  exception (per the a11y community + the MDN docs).
- The `:focus-visible` outline (`2px solid var(--accent)`)
  is visible on all focusable elements (links, buttons,
  inputs). A mouse user does NOT see the ring (the
  `:focus-visible` only fires for keyboard focus). A
  keyboard user sees the ring on every Tab press.
- The override of `a:hover { opacity: 0.85; }` to
  `a:focus-visible { opacity: 1; }` is a small DX win
  (the focus state is full-opacity, not dimmed).

## Tests

1. `test_globals_has_prefers_reduced_motion_media_query` —
   read `globals.css`; assert the
   `@media (prefers-reduced-motion: reduce)` block is
   present.
2. `test_globals_reduced_motion_overrides_all_transitions` —
   read the reduced-motion block; assert the `*,
   *::before, *::after` selector is used + the
   `transition-duration: 0.01ms` rule is set.
3. `test_globals_has_focus_visible_outline` — read
   `globals.css`; assert the `:focus-visible` selector
   with `outline: 2px solid var(--accent)` is present.
4. `test_globals_focus_visible_keeps_link_opacity` — read
   the `a:focus-visible` rule; assert the `opacity: 1`
   override is present.
5. `test_file_chip_focus_within_preserved` — read
   `upload/page.module.css`; assert the
   `.fileChip:focus-within` rule still has the canonical
   `--accent` outline (no regression).
6. `test_no_outline_reset_in_global_star_selector` — read
   the `*` selector in `globals.css`; assert it does NOT
   include `outline: none` (the browser default focus
   ring is preserved).

## Rejected alternatives

- **Add `prefers-reduced-motion` per-component** (not
  global): tempting (more granular). The MDN-canonical
  pattern is the global `*` selector override. Per-
  component rules are easy to miss (a future component
  author forgets to add the rule).
- **Use `prefers-reduced-motion: no-preference`** (gate
  the motion ON for users WITHOUT the preference, instead
  of OFF for users WITH the preference): tempting
  (preserves the default). The `reduce` media query is
  the canonical pattern per the WCAG 2.1 §2.3.3
  recommendation + the MDN docs.
- **Use JS to detect the `prefers-reduced-motion` media
  query and disable CSS transitions imperatively**: out
  of scope (the CSS media query is the canonical pattern;
  a JS-based approach is a fallback for legacy browsers
  that don't support the media query — not a v0.9.x
  concern).
- **Skip the `*:focus-visible` rule** (rely on browser
  defaults): tempting (less code). The browser default
  is inconsistent across browsers; the explicit rule
  ensures a consistent focus indicator.
- **Use `outline: 3px solid var(--accent)`** (thicker
  ring): the `2px` is the canonical Tailwind + Material
  UI default; the `3px` is heavier without a
  corresponding legibility win.
