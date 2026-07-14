"use client";

/**
 * v0.10.x plan 010: segment-level error boundary for /fights/[id].
 *
 * Catches errors thrown DURING the rendering of fights/[id]/page.tsx
 * AND its Server Component fetches (fetchFightEvents / fetchFightSquads /
 * fetchFightSkills / fetchFightTimeline / fetchFightPlayerTimeline).
 *
 * Common failure modes that surface here:
 *   - 502 Bad Gateway from fetchFightEvents (corrupt gz blob)
 *   - 404 from any of the 5 fetches (unknown fight_id)
 *   - zlib decompression failure (truncated blob)
 *   - schema drift between FastAPI response and schema.d.ts (caught by
 *     the OpenAPI drift gate but still surfaces as a runtime error)
 *
 * Domain-aware message ("This fight is temporarily unavailable") instead
 * of the generic Next.js error page. Stays narrow: render the boundary
 * IN PLACE of the failed subtree (the Promise.allSettled cascade in
 * the page above keeps the sibling sections alive, so the analyst sees
 * a partial view + a retry here, never a fully blank page).
 */

import { useEffect } from "react";
import Link from "next/link";
import { FIGHTS_GRID_BROWSE_FIGHT_PAGE, TRY_AGAIN_BUTTON_LABEL } from "@/lib/copy/error-messages";

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

export default function FightError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Fight drill-down error boundary caught:", error);
  }, [error]);

  return (
    <section style={PANEL_STYLE} data-testid="fight-error-panel">
      <h3 style={TITLE_STYLE}>This fight is temporarily unavailable</h3>
      <p style={BODY_STYLE}>
        The fight row or its events blob is currently unreachable (502
        upstream, 404 missing blob, zlib decompression failure, or
        FastAPI schema drift between this build and the gateway).
        Retry below, or browse the full grid for other matches.
      </p>
      <div style={ACTIONS_STYLE}>
        <button
          type="button"
          onClick={() => reset()}
          style={RETRY_BTN_STYLE}
          data-testid="fight-error-retry"
        >
          {TRY_AGAIN_BUTTON_LABEL}
        </button>
        <Link href="/fights" style={LINK_STYLE}>
          {FIGHTS_GRID_BROWSE_FIGHT_PAGE}
        </Link>
      </div>
    </section>
  );
}
