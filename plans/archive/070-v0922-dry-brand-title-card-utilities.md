# Plan 070 — v0.9.22: DRY — extract `.brand` + `.title` + `.card` utility classes to `globals.css`

## Drift base

`44ea862`. Refactor only — additive, no migration. The
visual output is unchanged.

## Surface

`web/src/app/globals.css` (NEW utility classes),
`web/src/app/page.module.css` (refactored to consume the
utilities),
`web/src/app/upload/page.module.css` (refactored to consume
the utilities).

## Finding

`page.module.css` and `upload/page.module.css` both define
the same 3 class blocks with minor differences:

### `.brand` (identical in both files)

```css
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--border);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
}
```

The 11 properties are byte-for-byte identical. Drift risk:
a future maintainer who changes `.brand` in one file (e.g.,
adds a `:hover` style) will forget to mirror it in the other.

### `.title` (gradient text — identical in both files)

```css
.title {
  font-size: 56px;            /* 56px in page.module.css, 40px in upload/page.module.css */
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.025em;
  background: linear-gradient(180deg, var(--foreground) 0%, var(--accent) 110%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
```

The gradient + the typography base are identical; only
the `font-size` differs (56px vs 40px — the landing page
title is larger than the upload page title). A
`.title` utility class with a `data-size` modifier (or
just a `font-size` override at the call site) would
deduplicate the gradient.

### `.card` (similar but not identical)

```css
/* page.module.css */
.card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 24px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  transition:
    border-color 0.15s ease-in-out,
    transform 0.15s ease-in-out;
}

.card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
}

/* upload/page.module.css */
.card {
  width: 100%;
  max-width: 560px;
  padding: 24px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: var(--surface);
}
```

The base surface (border + radius + padding + background)
is identical; the layout (flex vs width+max-width) and
the hover transition differ. A `.card-surface` utility
class (the base) + a `.card` modifier (the layout) would
deduplicate the base.

## Fix

1. **Add 3 utility classes** to `globals.css`:

   ```css
   /* Brand pill: the small uppercase accent label used
    * on the landing + upload pages. The `gap` is for an
    * optional icon sibling; the `display: inline-flex`
    * keeps the pill inline with surrounding text. */
   .brand {
     display: inline-flex;
     align-items: center;
     gap: 10px;
     padding: 6px 14px;
     border-radius: 999px;
     background: var(--surface);
     border: 1px solid var(--border);
     font-size: 12px;
     letter-spacing: 0.08em;
     text-transform: uppercase;
     color: var(--accent);
   }

   /* Title: the large gradient-text heading. The base
    * style is the gradient; the per-page `font-size`
    * override at the call site preserves the
    * landing-vs-upload size difference. */
   .title {
     font-weight: 700;
     line-height: 1.1;
     letter-spacing: -0.025em;
     background: linear-gradient(180deg, var(--foreground) 0%, var(--accent) 110%);
     -webkit-background-clip: text;
     background-clip: text;
     color: transparent;
   }

   /* Card surface: the base `border + border-radius +
    * background` triple used by all card-like containers
    * on the landing + upload pages. The layout (flex vs
    * width+max-width) is applied per-component via a
    * page-level CSS module class. */
   .card-surface {
     border: 1px solid var(--border);
     border-radius: 16px;
     background: var(--surface);
   }
   ```

2. **Refactor `page.module.css`** to consume the utilities:

   ```css
   .page {
     display: flex;
     flex: 1;
     flex-direction: column;
     align-items: center;
     justify-content: center;
     padding: 64px 24px 96px;
     gap: 48px;
   }

   .hero {
     display: flex;
     flex-direction: column;
     align-items: center;
     gap: 16px;
     max-width: 720px;
     text-align: center;
   }

   /* `.title` + `.brand` are now in globals.css; the
    * landing page overrides `font-size` to 56px. */
   .title {
     font-size: 56px;
   }

   .tagline {
     font-size: 18px;
     line-height: 28px;
     color: var(--foreground);
     opacity: 0.75;
     text-wrap: balance;
   }

   .cards {
     display: grid;
     grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
     gap: 16px;
     width: 100%;
     max-width: 880px;
   }

   /* `.card` extends `.card-surface` with the flex layout +
    * hover transition. The base `border + border-radius +
    * background` is in globals.css. */
   .card {
     display: flex;
     flex-direction: column;
     gap: 12px;
     padding: 24px;
     transition:
       border-color 0.15s ease-in-out,
       transform 0.15s ease-in-out;
   }

   .card:hover {
     border-color: var(--accent);
     transform: translateY(-2px);
   }

   .cardTitle {
     font-size: 18px;
     font-weight: 600;
   }

   .cardBody {
     font-size: 14px;
     line-height: 22px;
     opacity: 0.75;
   }

   .cardArrow {
     font-size: 13px;
     color: var(--accent);
   }

   .footer {
     font-size: 12px;
     opacity: 0.6;
     text-align: center;
   }
   ```

3. **Refactor `upload/page.module.css`** similarly:

   ```css
   .main {
     display: flex;
     flex: 1;
     flex-direction: column;
     align-items: center;
     padding: 64px 24px 96px;
     gap: 32px;
   }

   .header {
     display: flex;
     flex-direction: column;
     align-items: center;
     gap: 12px;
     max-width: 640px;
     text-align: center;
   }

   /* `.brand` is in globals.css (no per-page override). */
   /* `.title` is in globals.css; the upload page overrides
    * `font-size` to 40px. */
   .title {
     font-size: 40px;
   }

   .lede { /* ... unchanged ... */ }
   .inlineLink { /* ... unchanged ... */ }
   .form { /* ... unchanged ... */ }
   /* ... etc ... */
   ```

4. **Update `app/page.tsx`** to import the global
   `styles` from `globals.css` (the global CSS is
   auto-applied via the `import "./globals.css"` in
   `layout.tsx`; no change to `page.tsx` is needed for
   the utility classes to be available):

   ```tsx
   // No change; the global `.brand` + `.title` + `.card-surface`
   // classes are auto-applied to any matching element via the
   // global CSS cascade.
   ```

   Wait — this is wrong. The `globals.css` is a global
   stylesheet, not a CSS module. The utility classes are
   global, so any element with `className="brand"` (or
   `className={styles.brand}` from a CSS module) gets the
   global styles. The page components currently use
   `className={styles.brand}` (the CSS module); they need
   to be updated to `className={\`${styles.brand} brand\`}`
   (or to use the global class directly without the CSS
   module's hashed class name).

   The cleanest approach: **drop the per-page `.brand`
   + `.title` + `.card-surface` from the CSS modules
   entirely** + use the global class names directly in
   the page components:

   ```tsx
   // app/page.tsx
   <div className={styles.brand}>GW2Analytics</div>
   // becomes:
   <div className="brand">GW2Analytics</div>
   ```

   But this requires updating `app/page.tsx` +
   `app/upload/page.tsx` to use the global class names.
   The plan covers this in step 5.

5. **Update `app/page.tsx` and `app/upload/page.tsx`** to
   use the global class names for the extracted utilities:

   ```tsx
   // app/page.tsx
   import styles from "./page.module.css";

   <div className={`brand ${styles.hero}`}>...</div>
   <h1 className={`title ${styles.title}`}>GW2 Analytics</h1>
   <div className={`${styles.cards} ${styles.cardSurfaceWrapper}`}>
     <a className={`card-surface ${styles.card}`}>...</a>
   </div>
   ```

   The `styles.title` from the CSS module adds the
   `font-size: 56px` override; the global `.title` adds
   the gradient + typography base.

   The `styles.cardSurfaceWrapper` is unused (the `.card`
   page-level class includes the layout); only the base
   `card-surface` from `globals.css` is used.

6. **Document the utility class intent** in `globals.css`
   with a comment block above the utility section.

## Why a `card-surface` class (not just `.card`)

The `.card` class in each page module has a layout
component (flex direction, gap, padding, hover transition).
The base `border + border-radius + background` is the
"surface" — the same across all card-like containers. A
`card-surface` utility class separates the surface (global)
from the layout (per-page). The `card-surface` name is
descriptive ("a card-like surface") vs `.card` (which
implies the full card semantics).

## Why `font-size` is a per-page override (not a `data-size` modifier)

The `font-size` is the only property that differs between
the 2 `.title` uses (56px vs 40px). A `data-size="lg" |
md` modifier would add complexity (an attribute selector
+ a per-size rule) for a 1-property difference. The
per-page override (`styles.title { font-size: 56px; }`)
is the canonical CSS pattern (the override applies only
where the page needs a non-default size).

## Risks

- The refactor changes the class name on the HTML elements
  (from `className={styles.brand}` to
  `className="brand ${styles.brand}"`). The visual output
  is unchanged; the class names are an internal
  implementation detail.
- The global utility classes are unscoped (no CSS module
  hashing). A future maintainer who creates a `<div
  className="brand">` in a different context (e.g., a
  third-party widget) will get the global styles. This is
  a known trade-off of the global CSS approach; the
  alternative (CSS modules) is the per-component scoping
  the project already uses.
- The `.title` + `.card-surface` utilities are
  canonical-but-could-be-overridden. A future maintainer
  who wants a different gradient or a different border
  color can override at the per-page level.

## Tests

1. `test_globals_has_brand_utility` — read `globals.css`;
   assert the `.brand` selector is present with the 11
   canonical properties.
2. `test_globals_has_title_utility` — read `globals.css`;
   assert the `.title` selector is present with the
   `linear-gradient` + `background-clip: text` + `color:
   transparent` triple.
3. `test_globals_has_card_surface_utility` — read
   `globals.css`; assert the `.card-surface` selector
   has `border + border-radius + background` but NOT
   `display` (the layout is per-page).
4. `test_page_module_does_not_define_brand` — read
   `page.module.css`; assert the `.brand` selector is
   NOT present (it's now in globals.css).
5. `test_upload_page_module_does_not_define_brand` —
   same for `upload/page.module.css`.
6. `test_page_uses_brand_utility` — read
   `app/page.tsx`; assert the page uses `className="brand"`
   (or `className={\`brand ...\`}`) and not the CSS
   module's `styles.brand`.
7. `test_page_module_title_has_font_size_override` — read
   `page.module.css`; assert the `.title` selector has
   only `font-size: 56px` (the gradient + typography are
   in globals.css).
8. `test_upload_page_module_title_has_font_size_override` —
   same for `upload/page.module.css` with `font-size:
   40px`.

## Rejected alternatives

- **Move all CSS modules to global stylesheets** (no CSS
  modules): out of scope (the per-page CSS modules are
  the canonical Next.js 16 pattern for per-page styles;
  the global utility classes are an additive layer for
  shared styles).
- **Use a CSS-in-JS library** (e.g., `styled-components`):
  out of scope (the project standardizes on CSS modules;
  the CSS-in-JS migration is a future cycle).
- **Drop the `card-surface` utility class** (let the
  per-page `.card` define the full surface): tempting
  (simpler). The 3 lines of `border + border-radius +
  background` are duplicated in 2 files (and will be
  duplicated in 3+ files as the project grows). The
  utility class is the canonical DRY fix.
- **Use CSS `@layer`** to control the cascade order:
  out of scope (the `@layer` system is a modern CSS
  feature with limited browser support for the
  `!important` interaction; the current code's
  cascade order is fine).
- **Use Tailwind CSS** instead of CSS modules: out of
  scope (the project standardizes on CSS modules; the
  Tailwind migration is a future cycle).
