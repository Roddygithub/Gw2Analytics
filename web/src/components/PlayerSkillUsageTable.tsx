"use client";

/**
 * Per-player skill roll-up table + loadout header.
 *
 * Tour 4 v0.10.13 plan 044: Skill build analyser. Rendered on
 * the per-fight drill-down page (``/fights/[id]``) below the
 * existing per-fight ``SkillUsageTable`` once the analyst
 * picks an account via the player dropdown.
 *
 * Two-panel layout:
 * - **Loadout header strip**: 4 cells (account, profession,
 *   elite spec, equipped skills). Equipped-skill display is
 *   the V1 empty-list stub ("parser extraction deferred — see
 *   plan 044"); the panel is always rendered so the empty-state
 *   is explicit (matches the v0.8.0 §8.4 always-render pattern
 *   the player-timeline section established).
 * - **Skill table**: per-skill rows (skill_id, skill_name,
 *   hit_count, totals). Same column layout as
 *   :component:`SkillUsageTable`; the CSV download button is
 *   optional via the ``filename`` prop. When ``skills`` is
 *   empty (the idle-player edge case -- player present but
 *   not registering outgoing damage/healing/strip events),
 *   the table renders an empty-state panel instead.
 *
 * Why not wrap :component:`SkillUsageTable`
 * =========================================
 * Wrapping would couple the loadout strip's data flow to the
 * skill-table's rendering (the existing component takes
 * ``rows: SkillUsageRow[]`` -- a per-fight array with no
 * player concept). Forwarding ``PlayerSkills.skills`` into
 * ``SkillUsageTable`` would lose the loadout data; the
 * loadout strip would need to be sibling-rendered anyway.
 * Two components keeps the props typed to their domain.
 *
 * Why Client Component
 * ====================
 * The component mounts as the body of an interactive
 * section (the player dropdown on the parent page mutates
 * the ``playerSkills`` prop). Pure-render only -- no
 * ``useState`` / ``useEffect`` here -- so the directive
 * is a forward-compat marker for any future interactions
 * (sortable columns, "Lock to player" sticky toggle).
 */
import React from "react";

import type { PlayerSkills } from "@/lib/api";

const LOADOUT_BAR_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "stretch",
  gap: 24,
  padding: 12,
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--surface)",
  marginBottom: 8,
  flexWrap: "wrap",
};

const LOADOUT_LABEL_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};

const LABEL_TEXT: React.CSSProperties = {
  opacity: 0.7,
  fontSize: 12,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const VALUE_TEXT: React.CSSProperties = {
  fontSize: 14,
  fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
};

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

/**
 * Format the equipped-skill-ids list for the loadout strip.
 *
 * The backend's V1 stub returns an empty list (parser
 * extraction deferred to v0.11.0). Render the empty state
 * explicitly instead of an empty string so the analyst sees
 * the parser extraction parity rather than assuming "the
 * parser loaded 0 skills".
 */
function _formatEquipped(ids: number[] | undefined): string {
  if (!ids || ids.length === 0) {
    return "(parser extraction deferred — see plan 044)";
  }
  return ids.join(", ");
}

function _downloadCsv(filename: string, skills: PlayerSkills["skills"]): void {
  const header = "skill_id,skill_name,hit_count,total_damage,total_healing,total_buff_removal";
  const rows = skills.map(
    (r) => `${r.skill_id},"${r.skill_name}",${r.hit_count},${r.total_damage},${r.total_healing},${r.total_buff_removal}`,
  );
  const blob = new Blob([header, ...rows].join("\n"), { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function PlayerSkillUsageTable({
  playerSkills,
  filename,
}: {
  playerSkills: PlayerSkills;
  filename?: string;
}) {
  const { account_name, loadout, skills } = playerSkills;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Loadout header strip (always rendered — matches the
          v0.8.0 §8.4 always-render pattern from the player-timeline
          section so the empty-state is explicit rather than implicit). */}
      <div style={LOADOUT_BAR_STYLE} data-testid="player-skill-loadout">
        <div style={LOADOUT_LABEL_STYLE}>
          <span style={LABEL_TEXT}>Account</span>
          <span style={VALUE_TEXT} data-testid="player-skill-account">
            {account_name}
          </span>
        </div>
        <div style={LOADOUT_LABEL_STYLE}>
          <span style={LABEL_TEXT}>Profession</span>
          <span style={VALUE_TEXT}>{loadout.profession}</span>
        </div>
        <div style={LOADOUT_LABEL_STYLE}>
          <span style={LABEL_TEXT}>Elite spec</span>
          <span style={VALUE_TEXT}>{loadout.elite_spec}</span>
        </div>
        <div style={LOADOUT_LABEL_STYLE}>
          <span style={LABEL_TEXT}>Equipped skills</span>
          <span style={VALUE_TEXT}>{_formatEquipped(loadout.equipped_skill_ids)}</span>
        </div>
      </div>

      {/* Skill table OR empty-state panel. */}
      {skills.length === 0 ? (
        <div style={EMPTY_STYLE} data-testid="player-skill-empty">
          No skill roll-up rows (this player did not register outgoing damage /
          healing / buff-strip events in this fight).
        </div>
      ) : (
        <table style={TABLE_STYLE} data-testid="player-skill-table">
          <thead>
            <tr>
              <th style={TH_STYLE}>Skill id</th>
              <th style={TH_STYLE}>Skill name</th>
              <th style={TH_RIGHT_STYLE}>Hit count</th>
              <th style={TH_RIGHT_STYLE}>Total damage</th>
              <th style={TH_RIGHT_STYLE}>Total healing</th>
              <th style={TH_RIGHT_STYLE}>Total strip</th>
            </tr>
          </thead>
          <tbody>
            {skills.map((r) => (
              <tr key={r.skill_id}>
                <td style={TD_STYLE}>{r.skill_id}</td>
                <td style={TD_STYLE}>{r.skill_name || "(unnamed)"}</td>
                <td style={TD_RIGHT_STYLE}>{r.hit_count.toLocaleString("en-US")}</td>
                <td style={TD_RIGHT_STYLE}>{r.total_damage.toLocaleString("en-US")}</td>
                <td style={TD_ACCENT_STYLE}>{r.total_healing.toLocaleString("en-US")}</td>
                <td style={TD_RIGHT_STYLE}>{r.total_buff_removal.toLocaleString("en-US")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {filename && (
          <button onClick={() => _downloadCsv(filename, skills)}>
            Download CSV
          </button>
        )}
      )}
    </div>
  );
}
