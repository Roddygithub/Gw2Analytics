/**
 * v0.10.x plan 010: top-level 404 page.
 *
 * Server Component (no "use client") — Next.js renders this when no
 * matching route segment is found. Inherits the layout from
 * app/layout.tsx so the global `<header>` (search bar + nav) is still
 * visible, matching the existing dark-theme design tokens.
 *
 * Style is the same branded panel pattern as `error.tsx` so the two
 * boundary surfaces feel like ONE consistent UX — both use the
 * --surface / --border / --accent / --foreground CSS custom properties
 * declared in app/globals.css. Future design system changes propagate
 * automatically.
 */
import React from "react";

import Link from "next/link";

const PANEL_STYLE: React.CSSProperties = {
  padding: "32px",
  maxWidth: "560px",
  margin: "64px auto",
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: "12px",
  color: "var(--foreground)",
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const TITLE_STYLE: React.CSSProperties = {
  fontSize: "48px",
  fontWeight: 700,
  color: "var(--accent)",
  marginBottom: "8px",
  lineHeight: 1,
};

const SUBTITLE_STYLE: React.CSSProperties = {
  fontSize: "18px",
  fontWeight: 500,
  marginBottom: "24px",
  color: "var(--foreground)",
};

const BODY_STYLE: React.CSSProperties = {
  fontSize: "14px",
  opacity: 0.85,
  marginBottom: "24px",
  lineHeight: 1.5,
};

const ACTIONS_STYLE: React.CSSProperties = {
  display: "flex",
  gap: "12px",
  flexWrap: "wrap",
};

const LINK_STYLE: React.CSSProperties = {
  padding: "10px 16px",
  borderRadius: "8px",
  background: "transparent",
  color: "var(--accent)",
  border: "1px solid var(--accent)",
  fontSize: "13px",
  fontWeight: 500,
  textDecoration: "none",
  display: "inline-flex",
  alignItems: "center",
};

export default function NotFound() {
  return (
    <main style={PANEL_STYLE} data-testid="not-found-panel">
      <h1 style={TITLE_STYLE}>404</h1>
      <h2 style={SUBTITLE_STYLE}>This page is not in the dataset</h2>
      <p style={BODY_STYLE}>
        Either the URL was mistyped, the fight or player that used to
        live here has been trimmed (1.0 will introduce retention
        controls), or someone shared a stale link. Pivot to a player via
        the search bar above, or browse the full datasets below.
      </p>
      <div style={ACTIONS_STYLE}>
        <Link href="/fights" style={LINK_STYLE}>
          Browse fights
        </Link>
        <Link href="/players" style={LINK_STYLE}>
          Browse players
        </Link>
        <Link href="/upload" style={LINK_STYLE}>
          Upload a replay
        </Link>
      </div>
    </main>
  );
}
