/* eslint-disable react-refresh/only-export-components */

import type { Metadata } from "next";
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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
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
      </body>
    </html>
  );
}
