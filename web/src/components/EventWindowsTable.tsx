"use client";

/**
 * Per-bucket event roll-up table. Renders the Phase 7 v2
 * ``EventBucketOut`` rows from
 * ``GET /api/v1/fights/{fight_id}/events`` as a simple
 * ``<table>`` -- no AG Grid, no charts. The bucket count is bounded
 * by ``duration_s / window_s`` (e.g. a 60s fight at ``window_s=5``
 * is 12 rows), so the table stays human-scannable without
 * pagination.
 *
 * Why a plain HTML table (vs AG Grid)
 * ====================================
 * The bucket roll-up is a TIMELINE visualisation, not a sortable
 * data table. The natural sort order is by ``start_ms`` (which is
 * already monotonic in the response -- ``EventWindowAggregator``
 * emits buckets in chronological order with continuous fill), and
 * the analyst is looking for a fixed-window sample of damage /
 * healing activity over the fight. AG Grid's sort + filter
 * affordances would be wasted on this view.
 *
 * Why styling mirrors the AG Grid dark theme
 * ==========================================
 * The two ``TargetRollupsGrid`` instances on the same page use the
 * Quartz dark theme; the per-bucket table sits between them. A
 * matching dark surface (var(--background) + var(--border) +
 * var(--foreground) + var(--accent) for emphasis) keeps the
 * read-out visually cohesive.
 */

import type { EventBucket } from "@/lib/api";

const TABLE_STYLE: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 14,
  fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
};

const TH_STYLE: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  borderBottom: "1px solid var(--border)",
  color: "var(--foreground)",
  opacity: 0.7,
  fontWeight: 600,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const TD_STYLE: React.CSSProperties = {
  padding: "6px 12px",
  borderBottom: "1px solid var(--border)",
  color: "var(--foreground)",
};

const TH_RIGHT_STYLE: React.CSSProperties = {
  ...TH_STYLE,
  textAlign: "right",
};

const TD_RIGHT_STYLE: React.CSSProperties = {
  ...TD_STYLE,
  textAlign: "right",
};

const TD_ACCENT_STYLE: React.CSSProperties = {
  ...TD_STYLE,
  textAlign: "right",
  color: "var(--accent)",
};

const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

export function EventWindowsTable({ buckets }: { buckets: EventBucket[] }) {
  if (buckets.length === 0) {
    return <div style={EMPTY_STYLE}>No event windows.</div>;
  }

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <th style={TH_STYLE}>Start (ms)</th>
          <th style={TH_STYLE}>End (ms)</th>
          <th style={TH_RIGHT_STYLE}>Damage total</th>
          <th style={TH_RIGHT_STYLE}>Healing total</th>
          <th style={TH_RIGHT_STYLE}>Event count</th>
        </tr>
      </thead>
      <tbody>
        {buckets.map((b) => (
          <tr key={`${b.start_ms}-${b.end_ms}`}>
            <td style={TD_STYLE}>{b.start_ms}</td>
            <td style={TD_STYLE}>{b.end_ms}</td>
            <td style={TD_RIGHT_STYLE}>{b.damage_total}</td>
            <td style={TD_ACCENT_STYLE}>{b.healing_total}</td>
            <td style={TD_RIGHT_STYLE}>{b.event_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
