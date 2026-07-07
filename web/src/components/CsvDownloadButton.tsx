"use client";

/**
 * Small Client Component that renders a one-click "Download
 * CSV" button.
 *
 * The button is intentionally styled to match the existing
 * dark surface (var(--background) + var(--border) +
 * var(--foreground) + var(--accent) on hover) so it sits
 * naturally next to the AG Grid / table it accompanies. A
 * 1-line ``onClick`` triggers the browser download via
 * :func:`downloadCsv`; the CSV string is computed lazily on
 * click (not at render time) so the button is cheap to mount
 * even on large grids.
 *
 * Hidden when ``rows`` is empty (the typical "no data to
 * export" affordance).
 */

import type { CsvColumn } from "@/lib/csv";
import { toCsv, downloadCsv } from "@/lib/csv";

const BUTTON_STYLE: React.CSSProperties = {
  fontSize: 12,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
  padding: "6px 12px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--background)",
  color: "var(--foreground)",
  cursor: "pointer",
  fontWeight: 500,
};

export interface CsvDownloadButtonProps<TRow> {
  rows: readonly TRow[];
  columns: readonly CsvColumn<TRow>[];
  /** Output filename (e.g. ``"players.csv"`` or ``"fight-001-squads.csv"``). */
  filename: string;
  /** Optional override for the button label (default: "Download CSV"). */
  label?: string;
}

export function CsvDownloadButton<TRow>({
  rows,
  columns,
  filename,
  label,
}: CsvDownloadButtonProps<TRow>) {
  if (rows.length === 0) return null;
  return (
    <button
      type="button"
      style={BUTTON_STYLE}
      onClick={() => downloadCsv(filename, toCsv(rows, columns))}
    >
      {label ?? "Download CSV"}
    </button>
  );
}
