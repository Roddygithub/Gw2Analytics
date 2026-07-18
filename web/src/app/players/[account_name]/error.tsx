"use client";

/**
 * v0.10.x plan 010: segment-level error boundary for
 * /players/[account_name].
 *
 * Mirrors fights/[id]/error.tsx — catches the per-account roll-up or
 * the historical-timeline fetch failures and surfaces a domain-aware
 * message in place of the broken subtree.
 *
 * Common failure modes that surface here:
 *   - upstream /api/v1/players/{name:path} returns 5xx
 *   - upstream /api/v1/players/{name:path}/timeline returns 5xx
 *   - the parser-backed day-bucketing overflows the route's limit
 *     (rare; would manifest as 502 from the gateway aggregation step)
 *
 * Stays narrow: the per-account page is composed of 4 sections
 * (SSR-fetched summary, optional cross-account compare widget, the
 * timeline chart, and the per-fight breakdown) — only the failed
 * subtree gets the boundary. The page-level promise resolution above
 * keeps the surviving sections visible.
 */
import React from "react";

import { useEffect } from "react";
import Link from "next/link";

const PANEL_STYLE: React.CSSProperties = {
  marginTop: "32px",
  padding: "24px",
  borderRadius: "8px",
  background: "var(--surface)",
  border: "1px solid var(--border)",
};

const TITLE_STYLE: React.CSSProperties = {
  fontSize: "16px",
  fontWeight: 600,
  color: "var(--accent)",
  marginBottom: "8px",
};

const BODY_STYLE: React.CSSProperties = {
  fontSize: "13px",
  opacity: 0.85,
  marginBottom: "12px",
  lineHeight: 1.5,
};

const ACTIONS_STYLE: React.CSSProperties = {
  display: "flex",
  gap: "12px",
  alignItems: "center",
};

const RETRY_BTN_STYLE: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: "6px",
  background: "var(--accent)",
  color: "var(--background)",
  border: "none",
  fontSize: "12px",
  fontWeight: 500,
  cursor: "pointer",
};

const LINK_STYLE: React.CSSProperties = {
  color: "var(--accent)",
  fontSize: "13px",
  textDecoration: "none",
};

export default function PlayerError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Player profile error boundary caught:", error);
  }, [error]);

  return (
    <section style={PANEL_STYLE} data-testid="player-error-panel">
      <h3 style={TITLE_STYLE}>
        This player profile is temporarily unavailable
      </h3>
      <p style={BODY_STYLE}>
        The per-account roll-up or the historical-timeline data is
        currently unreachable. Retry below, or browse the full players
        list.
      </p>
      <div style={ACTIONS_STYLE}>
        <button
          type="button"
          onClick={() => reset()}
          style={RETRY_BTN_STYLE}
          data-testid="player-error-retry"
        >
          Try again
        </button>
        <Link href="/players" style={LINK_STYLE}>
          ← Browse players list
        </Link>
      </div>
    </section>
  );
}
