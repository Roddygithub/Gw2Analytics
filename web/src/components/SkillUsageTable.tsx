"use client";

/**
 * Per-skill roll-up table. Renders the v0.7.0
 * :class:`SkillUsageRow` rows from
 * ``GET /api/v1/fights/{fight_id}/skills`` as a simple
 * ``<table>`` -- no AG Grid, no charts. The skill count is
 * bounded by the parser's skill table size (typically 5-100
 * rows for a single fight), so the table stays human-scannable
 * without pagination.
 *
 * Why a plain HTML table (vs AG Grid)
 * ===================================
 * The skill roll-up is a "top skills by impact" view, not a
 * sortable data table. The natural sort order is by
 * ``-total_damage`` (the aggregator's deterministic-ordering
 * contract), and the analyst is looking for the dominant skill
 * IDs / names. AG Grid's sort + filter affordances would be
 * wasted on this view -- the page-level ``/fights/[id]`` page
 * can offer an AG Grid swap as a future enhancement if
 * analysts request it.
 *
 * Why styling mirrors the AG Grid dark theme
 * ==========================================
 * The two ``TargetRollupsGrid`` + ``SquadRollupsGrid`` instances
 * on the same page use the Quartz dark theme; the per-skill
 * table sits between them. A matching dark surface
 * (var(--background) + var(--border) + var(--foreground) +
 * var(--accent) for emphasis) keeps the read-out visually
 * cohesive.
 */

import type { SkillUsageRow } from "@/lib/api";
import type { CsvColumn } from "@/lib/csv";
import { CsvDownloadButton } from "./CsvDownloadButton";

/**
 * CSV column spec for the per-skill roll-up. Order matches the
 * on-screen table; ``hit_count`` + the 3 totals are unformatted
 * integers (raw values). The skill_id + skill_name pair is the
 * canonical join key for analysts who want to look up the
 * official description on the wiki.
 */
const CSV_COLUMNS: CsvColumn<SkillUsageRow>[] = [
  { field: "skill_id", headerName: "Skill id" },
  { field: "skill_name", headerName: "Skill name" },
  { field: "hit_count", headerName: "Hit count" },
  { field: "total_damage", headerName: "Total damage" },
  { field: "total_healing", headerName: "Total healing" },
  { field: "total_buff_removal", headerName: "Total strip" },
];

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

const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

export function SkillUsageTable({
  rows,
  filename,
}: {
  rows: SkillUsageRow[];
  /**
   * Optional output filename for the "Download CSV" button. When
   * set, a button is rendered above the table (hidden when
   * ``rows`` is empty). The CSV column spec is the inline
   * ``CSV_COLUMNS`` constant above so the downloaded file
   * matches the on-screen column order.
   */
  filename?: string;
}) {
  if (rows.length === 0) {
    return <div style={EMPTY_STYLE}>No skill roll-up rows.</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {filename ? (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <CsvDownloadButton rows={rows} columns={CSV_COLUMNS} filename={filename} />
        </div>
      ) : null}
      <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <th style={TH_STYLE}>Skill id</th>
          <th style={TH_STYLE}>Skill name</th>
          <th style={{ ...TH_STYLE, textAlign: "right" }}>Hit count</th>
          <th style={{ ...TH_STYLE, textAlign: "right" }}>Total damage</th>
          <th style={{ ...TH_STYLE, textAlign: "right" }}>Total healing</th>
          <th style={{ ...TH_STYLE, textAlign: "right" }}>Total strip</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.skill_id}>
            <td style={TD_STYLE}>{r.skill_id}</td>
            <td style={TD_STYLE}>{r.skill_name || "(unnamed)"}</td>
            <td style={{ ...TD_STYLE, textAlign: "right" }}>{r.hit_count}</td>
            <td style={{ ...TD_STYLE, textAlign: "right" }}>{r.total_damage}</td>
            <td style={{ ...TD_STYLE, textAlign: "right", color: "var(--accent)" }}>
              {r.total_healing}
            </td>
            <td style={{ ...TD_STYLE, textAlign: "right" }}>{r.total_buff_removal}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
