/* eslint-disable react-refresh/only-export-components */

import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import { Logo } from "@/components/Logo";
import { PlayerSearchBar } from "@/components/PlayerSearchBar";
import { API_BASE_URL } from "@/lib/env";
import "./globals.css";

// v0.9.9 plan 033: belt-and-braces fail-fast assertion at
// server boot. ``lib/env.ts`` already throws on a missing
// ``API_BASE_URL`` in production; this second check runs at
// module load time inside the layout so any server boot
// (including one that bypasses ``lib/env.ts`` callers via
// a future refactor) still surfaces the canonical error.
if (
  process.env.NODE_ENV === "production" &&
  (!API_BASE_URL || API_BASE_URL === "http://localhost:8000")
) {
  throw new Error(
    "API_BASE_URL is required in production and must NOT " +
      "fall back to localhost. Set it in your deployment " +
      "environment (e.g. Caddy, Docker, Kubernetes).",
  );
}

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "GW2Analytics",
  description:
    "Independent WvW combat analytics for Guild Wars 2. Local .zevtc parsing, world enrichment, multi-fight rollups.",
  icons: {
    icon: [
      { url: "/favicon.ico", type: "image/x-icon" },
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
    shortcut: "/favicon.ico",
    apple: "/favicon.ico",
  },
};

// v0.10.25 mobile audit: Next.js 14+ separates `viewport` + `themeColor`
// out of `metadata` into a sibling export. Sets the canonical mobile
// viewport so the AG Grid tables + the sticky header render correctly
// on a 360 px - 768 px viewport (the analyst phone / tablet envelope
// per the F17 §4 mobile risk). The themeColor matches `--background`
// at the canonical dark-Quartz value so the browser-chrome (status
// bar on iOS / Safari, address bar on Android Chrome) blends into
// the app surface.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0a0a0a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        {/*
          Skip-to-content link for keyboard / screen-reader users.
          Visually hidden by default; becomes visible on focus so a
          keyboard-only analyst can bypass the sticky header (the link
          strip + the player search bar) on every page.

          Uses a `<div role="main">` wrapper (NOT a `<main>` element)
          because every page already renders its own `<main>`; nesting
          two visible <main> elements would violate HTML5 (the spec
          mandates ONE visible <main> per page). The role="main"
          preserves the accessible landmark semantics.
        */}
        <a
          href="#main-content"
          data-testid="skip-to-content"
          className="skip-to-content"
          style={{
            position: "absolute",
            top: -40,
            left: 0,
            zIndex: 100,
            padding: "8px 16px",
            background: "var(--accent)",
            color: "var(--accent-foreground, #fff)",
            fontSize: 13,
            textDecoration: "none",
          }}
        >
          Aller au contenu principal
        </a>
        {/* 2026-07-16 mobile+a11y audit X1: removed the
            nested ``role="main"`` wrapper. Each page already
            renders its own ``<main>`` element; nesting two
            ``role="main"`` landmarks confuses screen-reader
            landmark navigation. The ``<div id="main-content">``
            remains so the skip-to-content anchor
            (``href="#main-content"``) still resolves to a
            focusable target. The actual landmark is provided
            by the page-level ``<main>`` element (which has
            the implicit role="main"). */}
        <div id="main-content">
        {/*
          v0.7.1 of web: a sticky header bar hosts the global
          player search affordance (the :class:`PlayerSearchBar`)
          so the analyst can pivot to a player profile from any
          page. The header is a Server Component (renders the
          Client Component sub-view); the sticky position keeps
          the search input always-visible on long-scroll pages
          (the /fights/[id] drill-down can be 100+ buckets at
          window_s=1). The bar's background + border pick up
          the canonical --surface / --border tokens so the
          header sits inside the existing dark theme.
        */}
        <header
          data-testid="global-header"
          style={{
            position: "sticky",
            top: 0,
            zIndex: 10,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 32px",
            background: "color-mix(in srgb, var(--background) 70%, transparent)",
            backdropFilter: "blur(12px)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <Link
            href="/"
            data-testid="brand-link"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              textDecoration: "none",
            }}
          >
            <Logo size={28} />
            <span
              style={{
                fontSize: 16,
                fontWeight: 700,
                color: "var(--foreground)",
                letterSpacing: "0.05em",
              }}
            >
              GW2<span style={{ color: "var(--accent)" }}>Analytics</span>
            </span>
          </Link>
          {/* v0.10.0 plan 032: secondary nav links between
              the brand and the search bar. ``/players`` and
              ``/players/compare`` are the 2 most common
              cross-fight destinations; the analyst can pivot
              from any page to either view without typing a
              URL. The link styles mirror the brand link so
              the nav reads as one consistent strip. */}
          <nav
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
            }}
            aria-label="Primary"
          >
            <Link
              href="/players"
              data-testid="nav-players"
              style={{
                fontSize: 13,
                color: "var(--link)",
                textDecoration: "none",
              }}
            >
              Players
            </Link>
            <Link
              href="/players/compare"
              data-testid="nav-compare"
              style={{
                fontSize: 13,
                color: "var(--link)",
                textDecoration: "none",
              }}
            >
              Compare
            </Link>
          </nav>
          <PlayerSearchBar />
        </header>
        {children}
        </div>
      </body>
    </html>
  );
}
