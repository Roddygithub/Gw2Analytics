"use client";

/**
 * Shared parts for native HTML readout tables.
 *
 * Extracted from ``ReadoutTabClient.tsx`` and
 * ``CompareReadoutTable.tsx`` so style constants, boon definitions,
 * sorting logic, and utility components live in ONE place.
 *
 * Import the components you need:
 *   import { TABLE_STYLE, TH_STYLE, TD_STYLE, BAR_BG, BAR_HEIGHT,
 *           BOONS, type BoonDef,
 *           useSortedPlayers, type SortField, type SortDir,
 *           MiniBar, DpsBar, HealBar, Th, TableWrapper,
 *           RoleBadge, IdentityCells } from "@/components/shared/readoutTableParts";
 */
import React, { useCallback, useMemo, useState } from "react";

import type { PlayerReadoutOut } from "@/lib/api";
import {
  EliteSpecCellRenderer,
  CommanderCellRenderer,
} from "@/components/PlayerReadoutCells";
import { ROLE_COLORS, ROLE_FALLBACK } from "@/lib/roleColors";

/* ------------------------------------------------------------------ *
 *  Types
 * ------------------------------------------------------------------ */

export type SortField = string;
export type SortDir = "asc" | "desc";

export interface BoonDef {
  key: string;
  label: string;
  iconFile: string | null;
}

/* ------------------------------------------------------------------ *
 *  Style constants
 * ------------------------------------------------------------------ */

export const TABLE_STYLE: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 12,
  fontFamily: "var(--font-geist-sans, sans-serif)",
  background: "var(--surface, rgba(255,255,255,0.02))",
  borderRadius: 6,
  overflow: "hidden",
};

export const TH_STYLE: React.CSSProperties = {
  position: "sticky",
  top: 0,
  padding: "6px 8px",
  textAlign: "left",
  fontWeight: 600,
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "var(--foreground)",
  opacity: 0.7,
  background: "var(--surface-elevated)",
  borderBottom: "1px solid var(--border)",
  whiteSpace: "nowrap",
  cursor: "pointer",
  userSelect: "none",
};

export const TD_STYLE: React.CSSProperties = {
  padding: "4px 8px",
  borderBottom: "1px solid var(--border)",
  color: "var(--foreground)",
  whiteSpace: "nowrap",
};

export const BAR_BG = "rgba(255,255,255,0.05)";
export const BAR_HEIGHT = 14;

/* ------------------------------------------------------------------ *
 *  Boon definitions (single source of truth)
 * ------------------------------------------------------------------ */

export const BOONS: BoonDef[] = [
  { key: "might", label: "Might", iconFile: "Might" },
  { key: "fury", label: "Fury", iconFile: "Fury" },
  { key: "quickness", label: "Quick", iconFile: "Quickness" },
  { key: "alacrity", label: "Alac", iconFile: "Alacrity" },
  { key: "protection", label: "Prot", iconFile: "Protection" },
  { key: "regeneration", label: "Regen", iconFile: "Regeneration" },
  { key: "vigor", label: "Vigor", iconFile: "Vigor" },
  { key: "aegis", label: "Aegis", iconFile: "Aegis" },
  { key: "stability", label: "Stab", iconFile: "Stability" },
  { key: "swiftness", label: "Swift", iconFile: "Swiftness" },
  { key: "resistance", label: "Resist", iconFile: "Resistance" },
  { key: "resolution", label: "Resol", iconFile: "Resolution" },
  { key: "superspeed", label: "Speed", iconFile: "Superspeed" },
  { key: "stealth", label: "Stealth", iconFile: "Stealth" },
];

/* ------------------------------------------------------------------ *
 *  Sorting hook + helpers
 * ------------------------------------------------------------------ */

function getSortValue(p: PlayerReadoutOut, field: string): number {
  if (field === "dps_total") return p.damage.dps_total;
  if (field === "dps_power") return p.damage.dps_power;
  if (field === "dps_condi") return p.damage.dps_condi;
  if (field === "strips") return p.damage.strips;
  if (field === "cc_applied") return p.damage.cc_applied;
  if (field === "down_contrib") return p.damage.down_contribution_dps;
  if (field === "cleave") return p.damage.cleave_targets;
  if (field === "kills") return p.damage.kills;
  if (field === "kill_part") return p.damage.kill_participation;
  if (field === "heal_total") return p.heal.heal_total ?? 0;
  if (field === "hps") return p.heal.hps;
  if (field === "barrier_ps") return p.heal.barrier_ps;
  if (field === "cleanses") return p.heal.cleanses;
  if (field === "stun_breaks") return p.heal.stun_breaks;
  if (field === "damage_taken") return p.defense.damage_taken;
  if (field === "deaths") return p.defense.deaths;
  if (field === "dodges") return p.defense.dodges;
  if (field === "blocks") return p.defense.blocks;
  if (field === "interrupts") return p.defense.interrupts;
  if (field === "cc_taken") return p.defense.cc_taken;
  if (field === "time_downed") return p.defense.time_downed_ms;
  if (field === "barrier_absorbed") return p.defense.barrier_absorbed;
  if (field === "presence_pct") return p.defense.presence_pct ?? 0;
  if (field === "dist_to_commander") return p.defense.dist_to_commander ?? -1;
  if (field === "subgroup") return p.subgroup;
  if (field.startsWith("boon_in_")) {
    const boonKey = field.replace("boon_in_", "");
    return (p.boons as unknown as Record<string, number | null>)[`${boonKey}_uptime`] ?? -1;
  }
  if (field.startsWith("boon_out_")) {
    const boonKey = field.replace("boon_out_", "");
    return (p.boons as unknown as Record<string, number | null>)[`outgoing_${boonKey}`] ?? -1;
  }
  if (field === "name") return (p.name || "").charCodeAt(0) || 0;
  return 0;
}

export function useSortedPlayers(
  players: PlayerReadoutOut[],
  defaultField: SortField,
  defaultDir: SortDir,
) {
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir }>({
    field: defaultField,
    dir: defaultDir,
  });

  const onSort = useCallback(
    (field: SortField) => {
      setSort((prev) => ({
        field,
        dir: prev.field === field && prev.dir === "desc" ? "asc" : "desc",
      }));
    },
    [],
  );

  const sorted = useMemo(() => {
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...players].sort((a, b) => {
      const va = getSortValue(a, sort.field);
      const vb = getSortValue(b, sort.field);
      if (va === vb) return 0;
      return va < vb ? -dir : dir;
    });
  }, [players, sort]);

  return { sorted, sort, onSort };
}

/* ------------------------------------------------------------------ *
 *  Utility components
 * ------------------------------------------------------------------ */

export function MiniBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div
      style={{
        width: `${Math.max(pct, 1)}%`,
        height: "100%",
        background: color,
        borderRadius: 2,
        transition: "width 0.3s",
        minWidth: 4,
      }}
    />
  );
}

export function DpsBar({ power, condi, total }: { power: number; condi: number; total: number }) {
  const max = Math.max(total, 1);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: BAR_HEIGHT, background: BAR_BG, borderRadius: 3, overflow: "hidden", display: "flex", minWidth: 60 }}>
        <MiniBar pct={(power / max) * 100} color="linear-gradient(90deg, #f59e0b, #d97706)" />
        <MiniBar pct={(condi / max) * 100} color="linear-gradient(90deg, #ef4444, #dc2626)" />
      </div>
      <span style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums", minWidth: 48, textAlign: "right" }}>
        {total.toFixed(0)}
      </span>
    </div>
  );
}

export function HealBar({ hps, bps, total }: { hps: number; bps: number; total: number }) {
  const max = Math.max(hps + bps, 1);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: BAR_HEIGHT, background: BAR_BG, borderRadius: 3, overflow: "hidden", display: "flex", minWidth: 60 }}>
        <MiniBar pct={(hps / max) * 100} color="linear-gradient(90deg, #22c55e, #16a34a)" />
        <MiniBar pct={(bps / max) * 100} color="linear-gradient(90deg, #06b6d4, #0891b2)" />
      </div>
      <span style={{ fontWeight: 700, fontVariantNumeric: "tabular-nums", minWidth: 48, textAlign: "right" }}>
        {total.toFixed(0)}
      </span>
    </div>
  );
}

export function Th({
  children,
  field,
  currentSort,
  onSort,
  style,
  colSpan,
  rowSpan,
}: {
  children: React.ReactNode;
  field: string;
  currentSort: { field: SortField; dir: SortDir } | null;
  onSort: (field: SortField) => void;
  style?: React.CSSProperties;
  colSpan?: number;
  rowSpan?: number;
}) {
  const active = currentSort?.field === field;
  return (
    <th
      style={{ ...TH_STYLE, ...style }}
      colSpan={colSpan}
      rowSpan={rowSpan}
      onClick={() => onSort(field)}
    >
      {children}
      {active && (
        <span style={{ marginLeft: 2, fontSize: 9 }}>
          {currentSort?.dir === "asc" ? " ▲" : " ▼"}
        </span>
      )}
    </th>
  );
}

export function TableWrapper({ children, maxHeight }: { children: React.ReactNode; maxHeight?: number }) {
  return (
    <div
      style={{
        width: "100%",
        overflowX: "auto",
        border: "1px solid var(--border)",
        borderRadius: 6,
        maxHeight: maxHeight ?? 600,
        overflowY: "auto",
      }}
    >
      {children}
    </div>
  );
}

/** Role badge. Accepts optional title for tooltip. */
export function RoleBadge({ role, title }: { role: string; title?: string }) {
  const c = ROLE_COLORS[role] ?? ROLE_FALLBACK;
  return (
    <span
      title={title ?? role}
      style={{
        padding: "0 5px",
        borderRadius: 3,
        fontSize: 9,
        fontWeight: 700,
        lineHeight: "15px",
        background: c.bg,
        color: c.fg,
        letterSpacing: "0.03em",
        cursor: "help",
      }}
    >
      {role}
    </span>
  );
}

/**
 * Identity cells (Groupe, Nom, Spé, Cmd, Rôles).
 * Renders the 5 shared columns that prepend every readout table.
 *
 * Accepts an optional ``roleTooltips`` map so ReadoutTabClient
 * can pass detailed role descriptions without the shared module
 * needing to know about them.
 */
export function IdentityCells({
  player,
  roleTooltips,
}: {
  player: PlayerReadoutOut;
  roleTooltips?: Record<string, string>;
}) {
  return (
    <>
      <td style={TD_STYLE}>
        {player.subgroup === 0 ? "—" : `Sub ${player.subgroup}`}
      </td>
      <td style={{ ...TD_STYLE, fontWeight: 500 }}>{player.name}</td>
      <td style={TD_STYLE}>
        <EliteSpecCellRenderer data={player} />
      </td>
      <td style={{ ...TD_STYLE, textAlign: "center" }}>
        <CommanderCellRenderer data={player} />
      </td>
      <td style={TD_STYLE}>
        <span style={{ display: "inline-flex", gap: 2, flexWrap: "wrap" }}>
          {player.roles.map((r) => (
            <RoleBadge key={r} role={r} title={roleTooltips?.[r]} />
          ))}
        </span>
      </td>
    </>
  );
}
