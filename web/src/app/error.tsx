"use client";

/**
 * v0.10.x plan 010: top-level Next.js App Router error boundary.
 * Catches any error that propagates UP from a Server Component below
 * (transitively: route segments, layouts, the root layout itself).
 *
 * Renders a brand-styled "Something went wrong" panel with a
 * "Try again" button that calls `reset()` to re-render the failed
 * subtree. Operators can route the `console.error` to Sentry/etc. by
 * extending the `useEffect` below — no other side effects.
 */

import { useEffect } from "react";
import Link from "next/link";
import { FIGHTS_GRID_LINK_ROOT } from "@/lib/copy/error-messages";

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
  fontSize: "20px",
  fontWeight: 600,
  color: "var(--accent)",
  marginBottom: "12px",
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

const PRIMARY_BTN_STYLE: React.CSSProperties = {
  padding: "10px 16px",
  borderRadius: "8px",
  background: "var(--accent)",
  color: "var(--background)",
  border: "none",
  fontSize: "13px",
  fontWeight: 500,
  cursor: "pointer",
};

const SECONDARY_BTN_STYLE: React.CSSProperties = {
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

const INLINE_LINK_STYLE: React.CSSProperties = {
  color: "var(--accent)",
  textDecoration: "underline",
};

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // The Next.js dev overlay already logs to the dev tools; in prod
    // this console line is the only output. Operators building toward
    // Sentry/etc. integration should wire the capture API here (the
    // `error.digest` field is the fingerprint Next.js gives us — same
    // digest = same render-path failure).
    console.error("Next.js global error boundary caught:", error);
  }, [error]);

  return (
    <main style={PANEL_STYLE}>
      <h1 style={TITLE_STYLE}>Something went wrong</h1>
      <p style={BODY_STYLE}>
        A request to the backend returned an unexpected error. This is
        usually transient (parsing pipeline hiccup, transient S3 outage,
        Alembic schema-drift guard triggering). Retry below; the dataset
        is still browsable from{" "}
        <Link href="/fights" style={INLINE_LINK_STYLE}>
          {FIGHTS_GRID_LINK_ROOT}
        </Link>{" "}
        or{" "}
        <Link href="/players" style={INLINE_LINK_STYLE}>
          the players list
        </Link>
        .
      </p>
      <div style={ACTIONS_STYLE}>
        <button
          type="button"
          onClick={() => reset()}
          style={PRIMARY_BTN_STYLE}
          data-testid="global-error-retry"
        >
          Try again
        </button>
        <Link href="/" style={SECONDARY_BTN_STYLE}>
          Back to landing
        </Link>
      </div>
    </main>
  );
}
