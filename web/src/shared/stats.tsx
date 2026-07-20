/**
 * Shared helpers for cross-fight stats sections on Server Components.
 *
 * Exports ``formatLarge`` for human-readable number display, style
 * constants for stat cards, and ``TopListCard`` for rendering top-3
 * player lists with medal emojis.
 *
 * NOT a Client Component — no ``"use client"``, no hooks, no icon
 * imports. Safe to import from any Server Component page.
 */

import type { PlayerListRow } from "@/lib/api";

/* ------------------------------------------------------------------ *
 *  Number formatting
 * ------------------------------------------------------------------ */

/**
 * Format a number to human-readable form with K/M/B suffixes.
 *
 * - >= 1B: `1.0B`, `2.5B`, etc.
 * - >= 1M: `1.0M`, `2.5M`, etc.
 * - >= 1K: `1.0K`, `2.5K`, etc.
 * - < 1K: raw number (``1234`` → ``1234``)
 */
export function formatLarge(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1_000_000_000) return `${sign}${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(1)}K`;
  return `${sign}${Math.round(abs)}`;
}

/* ------------------------------------------------------------------ *
 *  Stat card style constants
 * ------------------------------------------------------------------ */

export const STAT_CARD = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "16px 20px",
  minWidth: 180,
} as const;

export const STAT_VALUE = {
  fontSize: 24,
  fontWeight: 700,
  lineHeight: 1.2,
  margin: 0,
} as const;

export const STAT_LABEL = {
  fontSize: 11,
  fontWeight: 600,
  opacity: 0.6,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  margin: "2px 0 0 0",
} as const;

/* ------------------------------------------------------------------ *
 *  Top-3 list card (server-renderable)
 * ------------------------------------------------------------------ */

/**
 * Render a top-3 player list card with medal emojis.
 *
 * Sorts the row array internally by ``getValue`` descending and
 * shows the top 3. When the array is empty, renders a muted
 * "No data" fallback.
 */
export function TopListCard({
  title,
  rows,
  getValue,
}: {
  title: string;
  rows: readonly PlayerListRow[];
  getValue: (r: PlayerListRow) => number;
}) {
  const sorted = [...rows]
    .sort((a, b) => getValue(b) - getValue(a))
    .slice(0, 3);
  const medals = ["🥇", "🥈", "🥉"];

  return (
    <div style={STAT_CARD}>
      <p
        style={{
          fontSize: 10,
          fontWeight: 700,
          opacity: 0.6,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          margin: "0 0 8px 0",
        }}
      >
        {title}
      </p>
      {sorted.length === 0 ? (
        <p style={{ fontSize: 12, opacity: 0.5, margin: 0 }}>No data</p>
      ) : (
        sorted.map((r, i) => (
          <div
            key={r.account_name}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "2px 0",
              fontSize: 12,
            }}
          >
            <span
              style={{
                fontWeight: i === 0 ? 600 : 400,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                minWidth: 0,
                marginRight: 8,
              }}
            >
              {medals[i]} {r.name}
            </span>
            <span style={{ fontWeight: 600, flexShrink: 0 }}>
              {formatLarge(getValue(r))}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
