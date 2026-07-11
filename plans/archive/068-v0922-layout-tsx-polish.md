# Plan 068 — v0.9.22: `web/src/app/layout.tsx` polish (inline styles → CSS module + missing metadata fields)

## Drift base

`44ea862`. Refactor only — additive, no migration. The wire
output is unchanged; only the code structure + the HTML
metadata block change.

## Surface

`web/src/app/layout.tsx` (the root layout),
NEW `web/src/app/layout.module.css` (the extracted header
styles).

## Finding (part 1: inline `style={{}}` in layout.tsx)

The root layout's `<header>` uses inline `style={{}}` for
all visual properties (sticky position, z-index, padding,
background, border, gap, flex-wrap, the link's color and
font-weight):

```tsx
<header
  style={{
    position: "sticky",
    top: 0,
    zIndex: 10,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "12px 32px",
    background: "var(--surface)",
    borderBottom: "1px solid var(--border)",
    gap: 16,
    flexWrap: "wrap",
  }}
>
  <a
    href="/"
    style={{
      fontSize: 14,
      fontWeight: 600,
      color: "var(--accent)",
      textDecoration: "none",
    }}
  >
    GW2Analytics
  </a>
  <PlayerSearchBar />
</header>
```

The inline `style` is a code smell:
- Breaks the design-token abstraction (the CSS variables
  `--surface` and `--border` are referenced, but the
  numeric values `12px 32px`, `16px`, `12px` are
  hard-coded inline; a future theme change requires editing
  the JS object, not the CSS).
- Makes the header impossible to theme per-page (a page
  that wants a different header background cannot override
  an inline style).
- Inconsistent with the rest of the codebase (all other
  components use CSS modules — see `page.module.css`,
  `upload/page.module.css`).
- The inline JS object is a Server-Component-compatible
  pattern (no client-side hydration cost), but the styling
  abstraction is still wrong.

## Finding (part 2: minimal `metadata` block)

The layout's `metadata` export has only `title` and
`description`:

```tsx
export const metadata: Metadata = {
  title: "GW2Analytics",
  description: "Independent WvW combat analytics for Guild Wars 2. ...",
};
```

Missing fields for a v0.9.x project with shareable URLs:
- `metadataBase` — required for absolute URL construction
  in OG images + the `alternates.canonical` field.
- `viewport` — required for proper mobile rendering (the
  current code relies on the Next.js default viewport,
  which is fine but explicit is better).
- `themeColor` — sets the browser chrome color on mobile
  (matches the `--accent` token).
- `openGraph` — for rich previews on Slack, Discord, X.
  The current code has no OG image, so a share link shows
  the URL bare.
- `twitter` — for X/Twitter card previews.
- `icons` — the canonical favicon + apple-touch-icon path.
  The current code has no `app/icon.png`; the browser
  auto-requests `/favicon.ico` which 404s.
- `manifest` — the PWA manifest path.
- `alternates.canonical` — the canonical URL of the site.
- `robots` — explicit `index, follow` (default but explicit
  is canonical).

## Fix

1. **Extract the header styles** to a new
   `web/src/app/layout.module.css`:

   ```css
   .header {
     position: sticky;
     top: 0;
     z-index: 10;
     display: flex;
     align-items: center;
     justify-content: space-between;
     padding: 12px 32px;
     background: var(--surface);
     border-bottom: 1px solid var(--border);
     gap: 16px;
     flex-wrap: wrap;
   }

   .brand {
     font-size: 14px;
     font-weight: 600;
     color: var(--accent);
     text-decoration: none;
   }
   ```

2. **Update `layout.tsx`** to import the CSS module and
   use `className`:

   ```tsx
   import styles from "./layout.module.css";

   // ...
   <header className={styles.header}>
     <a href="/" className={styles.brand}>
       GW2Analytics
     </a>
     <PlayerSearchBar />
   </header>
   ```

3. **Expand the `metadata` block** with the canonical
   Next.js 16 fields:

   ```tsx
   const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL
     ?? "https://gw2analytics.example.com";

   export const metadata: Metadata = {
     metadataBase: new URL(SITE_URL),
     title: {
       default: "GW2Analytics",
       template: "%s · GW2Analytics",
     },
     description: "Independent WvW combat analytics for Guild Wars 2. ...",
     applicationName: "GW2Analytics",
     keywords: ["GW2", "Guild Wars 2", "WvW", "combat analytics", "arcdps"],
     authors: [{ name: "GW2Analytics team" }],
     creator: "GW2Analytics",
     publisher: "GW2Analytics",
     robots: { index: true, follow: true },
     alternates: { canonical: "/" },
     icons: {
       icon: [
         { url: "/favicon.ico", sizes: "any" },
         { url: "/icon.svg", type: "image/svg+xml" },
       ],
       apple: "/apple-touch-icon.png",
     },
     manifest: "/manifest.webmanifest",
     openGraph: {
       type: "website",
       locale: "en_US",
       url: SITE_URL,
       siteName: "GW2Analytics",
       title: "GW2Analytics",
       description: "Independent WvW combat analytics for Guild Wars 2. ...",
     },
     twitter: {
       card: "summary_large_image",
       title: "GW2Analytics",
       description: "Independent WvW combat analytics for Guild Wars 2. ...",
     },
     viewport: {
       width: "device-width",
       initialScale: 1,
       themeColor: "#d4a64a", // matches the --accent CSS variable
     },
   };
   ```

4. **Add a small `app/icon.svg` and `app/apple-touch-icon.png`**
   (a 1 KB SVG + a 256x256 PNG) to the repo so the
   `icons` block resolves to real assets instead of 404s.

5. **Add a `app/manifest.webmanifest`** with the minimal
   PWA fields (`name`, `short_name`, `start_url`,
   `display`, `background_color`, `theme_color`).

## Why template-based title

The `title.template = "%s · GW2Analytics"` lets each page
override its own title (e.g., `PlayerProfileOut.name`) and
the full title becomes `"Player Name · GW2Analytics"`. The
`title.default` is the site-wide fallback for pages that
don't override.

## Why `NEXT_PUBLIC_SITE_URL` (vs `API_BASE_URL`)

The `API_BASE_URL` env var (per plan 033 + 057) is the
backend gateway URL. The `NEXT_PUBLIC_SITE_URL` is the
public-facing frontend URL. The 2 are independent (the
frontend can be hosted on a different domain than the
backend, e.g., `app.gw2analytics.example.com` vs
`api.gw2analytics.example.com`). The `NEXT_PUBLIC_*` prefix
makes the env var available to Client Components (the OG
metadata is rendered server-side, so the var is also
available without the prefix; the `NEXT_PUBLIC_*` is a
belt-and-braces consistency with the existing client-side
alias).

## Risks

- The metadata block expansion adds ~30 lines to
  `layout.tsx`. The expansion is additive (no breaking
  change to the wire output; the new fields are
  informational).
- The `metadataBase` requires an absolute URL. A dev
  environment without `NEXT_PUBLIC_SITE_URL` falls back to
  `https://gw2analytics.example.com` (the canonical
  placeholder). A real deployment MUST set the env var
  to the production domain.
- The `themeColor` is a hard-coded `#d4a64a` (the same
  value as the `--accent` CSS variable). The duplication
  is intentional (the metadata is server-side rendered
  and cannot reference CSS variables). A future plan can
  add a build-time substitution if the accent color
  changes.
- The `icon.svg` + `apple-touch-icon.png` +
  `manifest.webmanifest` are NEW files in `app/`. The
  Next.js App Router auto-discovers these files (the
  `icons` + `manifest` metadata fields are documentation
  only; Next.js reads the files at build time).

## Tests

1. `test_layout_uses_css_module_for_header` — import
   `layout.tsx`; assert no `style={{}}` block remains for
   the `<header>` element; assert `className={styles.header}`
   is used.
2. `test_layout_metadata_has_metadata_base` — read the
   layout's metadata export; assert `metadataBase` is a
   `new URL(SITE_URL)` instance.
3. `test_layout_metadata_has_viewport` — assert the
   `viewport` field is present with `width: "device-width"`.
4. `test_layout_metadata_has_open_graph` — assert the
   `openGraph` block has `type: "website"`, `url`, `siteName`.
5. `test_layout_metadata_has_twitter_card` — assert the
   `twitter` block has `card: "summary_large_image"`.
6. `test_layout_metadata_has_icons` — assert the `icons`
   block references `/favicon.ico` + `/icon.svg` +
   `/apple-touch-icon.png`.
7. `test_app_icon_svg_exists` — read `app/icon.svg`; assert
   it's a valid SVG.
8. `test_app_manifest_exists` — read `app/manifest.webmanifest`;
   assert it has `name`, `short_name`, `start_url`, `display`.

## Rejected alternatives

- **Move the metadata to a separate `app/metadata.ts` file**:
  tempting (separation of concerns). The Next.js 16 App
  Router auto-discovers `metadata` exports from `layout.tsx`
  + `page.tsx`; moving to a separate file would break the
  convention. The metadata stays in `layout.tsx`.
- **Use a Next.js 15 `generateMetadata` function** instead
  of a static `metadata` export: tempting (more flexible).
  The current metadata is static (no per-request
  computation). A future plan can add `generateMetadata` if
  per-request metadata is needed (e.g., a per-account
  player profile title).
- **Skip the OG / Twitter cards** (no social sharing):
  tempting (the project is a personal analytics tool, not
  a marketing site). The OG / Twitter cards are
  informational; a future share of a fight URL on Discord
  shows a rich preview (the screenshot + the player
  name). The 5 lines of metadata are a low-cost forward-
  compat win.
- **Skip the `manifest.webmanifest`** (PWA support):
  the PWA is not a v0.9.x goal. The manifest is a
  forward-compat knob (a future plan can ship a Service
  Worker + the manifest becomes useful).
- **Use a `useEffect` + `document.head` injection for
  the metadata**: out of scope (the Next.js metadata API
  is the canonical pattern).
