"use client";

/**
 * Native HTML table component for the fight compare page.
 *
 * Replaces the 4 AG Grid ``PlayerReadout*`` components with
 * native HTML tables that match the ``ReadoutTabClient`` style.
 * Sortable by clicking column headers (per-table independent sort).
 *
 * Boon icons (14 official GW2 icons) are rendered alongside the
 * column headers for the Boons table.
 */
import React, { useCallback, useMemo, useState } from "react";

import type { PlayerReadoutOut } from "@/lib/api";
import {
  EliteSpecCellRenderer,
  CommanderCellRenderer,
} from "./PlayerReadoutCells";
import { ROLE_COLORS, ROLE_FALLBACK } from "@/lib/roleColors";

/* ------------------------------------------------------------------ *
 *  Constants
 * ------------------------------------------------------------------ */

type SortField = string;
type SortDir = "asc" | "desc";

const TABLE_STYLE: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 12,
  fontFamily: "var(--font-geist-sans, sans-serif)",
  background: "var(--surface, rgba(255,255,255,0.02))",
  borderRadius: 6,
  overflow: "hidden",
};

const TH_STYLE: React.CSSProperties = {
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
  background: "var(--surface-elevated, rgba(255,255,255,0.05))",
  borderBottom: "1px solid var(--border)",
  whiteSpace: "nowrap",
  cursor: "pointer",
  userSelect: "none",
};

const TD_STYLE: React.CSSProperties = {
  padding: "4px 8px",
  borderBottom: "1px solid var(--border)",
  color: "var(--foreground)",
  whiteSpace: "nowrap",
};

const BAR_BG = "rgba(255,255,255,0.05)";
const BAR_HEIGHT = 14;

/* ------------------------------------------------------------------ *
 *  Boon definitions
 * ------------------------------------------------------------------ */

interface BoonDef {
  key: string;
  label: string;
  iconFile: string | null;
}

const BOONS: BoonDef[] = [
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
 *  Sorting hook
 * ------------------------------------------------------------------ */

function useSortedPlayers(
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

/* ------------------------------------------------------------------ *
 *  Sub-components
 * ------------------------------------------------------------------ */

function MiniBar({ pct, color }: { pct: number; color: string }) {
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

function DpsBar({ power, condi, total }: { power: number; condi: number; total: number }) {
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

function HealBar({ hps, bps, total }: { hps: number; bps: number; total: number }) {
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

function RoleBadge({ role }: { role: string }) {
  const c = ROLE_COLORS[role] ?? ROLE_FALLBACK;
  return (
    <span
      title={role}
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

function IdentityCells({ player }: { player: PlayerReadoutOut }) {
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
            <RoleBadge key={r} role={r} />
          ))}
        </span>
      </td>
    </>
  );
}

function Th({
  children,
  field,
  currentSort,
  onSort,
  style,
  colSpan,
}: {
  children: React.ReactNode;
  field: string;
  currentSort: { field: SortField; dir: SortDir } | null;
  onSort: (field: SortField) => void;
  style?: React.CSSProperties;
  colSpan?: number;
}) {
  const active = currentSort?.field === field;
  return (
    <th
      style={{ ...TH_STYLE, ...style }}
      colSpan={colSpan}
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

/* ------------------------------------------------------------------ *
 *  Table wrapper
 * ------------------------------------------------------------------ */

function TableWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        width: "100%",
        overflowX: "auto",
        border: "1px solid var(--border)",
        borderRadius: 6,
        maxHeight: 400,
        overflowY: "auto",
      }}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Main component
 * ------------------------------------------------------------------ */

export type CompareTableKind = "damage" | "heal" | "boons" | "defense";

const TABLE_TITLE: Record<CompareTableKind, string> = {
  damage: "Dégâts",
  heal: "Soins",
  boons: "Boons",
  defense: "Défense & Positionnement",
};

interface CompareReadoutTableProps {
  kind: CompareTableKind;
  players: PlayerReadoutOut[];
}

/**
 * Native HTML table with per-table sort, matching the
 * ``ReadoutTabClient`` style.  Supports the 4 readout aspects:
 * damage, heal, boons, defense.
 */
export function CompareReadoutTable({ kind, players }: CompareReadoutTableProps) {
  if (players.length === 0) {
    return (
      <div style={{ padding: "12px 16px", border: "1px solid var(--border)", borderRadius: 4, color: "var(--foreground)", opacity: 0.7 }}>
        Aucun joueur dans ce tableau.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <h4 style={{ fontSize: 13, fontWeight: 600, margin: 0, opacity: 0.8 }}>
        {TABLE_TITLE[kind]}
      </h4>
      <TableWrapper>
        {kind === "damage" && <DamageTable players={players} />}
        {kind === "heal" && <HealTable players={players} />}
        {kind === "boons" && <BoonsTable players={players} />}
        {kind === "defense" && <DefenseTable players={players} />}
      </TableWrapper>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Damage table
 * ------------------------------------------------------------------ */

function DamageTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "dps_total", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          <Th field="dps_total" currentSort={sort} onSort={onSort} style={{ minWidth: 180 }}>DPS (power / condi)</Th>
          <Th field="strips" currentSort={sort} onSort={onSort}>Strips</Th>
          <Th field="cc_applied" currentSort={sort} onSort={onSort}>CC</Th>
          <Th field="down_contrib" currentSort={sort} onSort={onSort}>Down DPS</Th>
          <Th field="cleave" currentSort={sort} onSort={onSort}>Cleave</Th>
          <Th field="kills" currentSort={sort} onSort={onSort}>Kills</Th>
          <Th field="deaths" currentSort={sort} onSort={onSort}>Morts</Th>
          <Th field="kill_part" currentSort={sort} onSort={onSort}>Kill Part</Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
            <IdentityCells player={p} />
            <td style={TD_STYLE}><DpsBar power={p.damage.dps_power} condi={p.damage.dps_condi} total={p.damage.dps_total} /></td>
            <td style={TD_STYLE}>{p.damage.strips}</td>
            <td style={TD_STYLE}>{p.damage.cc_applied}</td>
            <td style={TD_STYLE}>{p.damage.down_contribution_dps.toFixed(1)}</td>
            <td style={TD_STYLE}>{p.damage.cleave_targets}</td>
            <td style={TD_STYLE}>{p.damage.kills}</td>
            <td style={TD_STYLE}>{p.defense.deaths}</td>
            <td style={TD_STYLE}>{p.damage.kill_participation}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ *
 *  Heal table
 * ------------------------------------------------------------------ */

function HealTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "hps", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          <Th field="hps" currentSort={sort} onSort={onSort} style={{ minWidth: 180 }}>Heal / Barrier</Th>
          <Th field="cleanses" currentSort={sort} onSort={onSort}>Cleanses</Th>
          <Th field="stun_breaks" currentSort={sort} onSort={onSort}>Breakstun</Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
            <IdentityCells player={p} />
            <td style={TD_STYLE}><HealBar hps={p.heal.hps} bps={p.heal.barrier_ps} total={p.heal.heal_total ?? 0} /></td>
            <td style={TD_STYLE}>{p.heal.cleanses}</td>
            <td style={TD_STYLE}>{p.heal.stun_breaks}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ *
 *  Boons table (with official GW2 icons)
 * ------------------------------------------------------------------ */

function BoonsTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "boon_in_might", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort} style={{ minWidth: 50 }}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          {BOONS.map((b) => (
            <th key={b.key} style={{ ...TH_STYLE, textAlign: "center", cursor: "default" }} colSpan={2} title={b.label}>
              {b.iconFile ? (
                <img
                  src={`/icons/boons/${b.iconFile}_tango.png`}
                  alt={b.label}
                  width={22}
                  height={22}
                  style={{ display: "block", margin: "0 auto" }}
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
              ) : (
                b.label
              )}
            </th>
          ))}
        </tr>
        <tr>
          {BOONS.map((b) => (
            <React.Fragment key={b.key}>
              <Th field={`boon_in_${b.key}`} currentSort={sort} onSort={onSort} style={{ width: 42, textAlign: "center" }}>
                In
              </Th>
              <Th field={`boon_out_${b.key}`} currentSort={sort} onSort={onSort} style={{ width: 42, textAlign: "center" }}>
                Out
              </Th>
            </React.Fragment>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
            <IdentityCells player={p} />
            {BOONS.map((b) => {
              const boons = p.boons as unknown as Record<string, number | null>;
              return (
                <React.Fragment key={b.key}>
                  <td style={{ ...TD_STYLE, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
                    {boons[`${b.key}_uptime`] != null ? `${boons[`${b.key}_uptime`]!.toFixed(0)}%` : "—"}
                  </td>
                  <td style={{ ...TD_STYLE, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
                    {boons[`outgoing_${b.key}`] != null ? boons[`outgoing_${b.key}`]!.toLocaleString() : "—"}
                  </td>
                </React.Fragment>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ *
 *  Defense table
 * ------------------------------------------------------------------ */

function DefenseTable({ players }: { players: PlayerReadoutOut[] }) {
  const { sorted, sort, onSort } = useSortedPlayers(players, "damage_taken", "desc");

  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <Th field="subgroup" currentSort={sort} onSort={onSort}>Groupe</Th>
          <Th field="name" currentSort={sort} onSort={onSort}>Nom</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Spé</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default", width: 40 }}>Cmd</Th>
          <Th field="" currentSort={null} onSort={() => {}} style={{ cursor: "default" }}>Rôles</Th>
          <Th field="damage_taken" currentSort={sort} onSort={onSort}>Dmg reçu</Th>
          <Th field="dodges" currentSort={sort} onSort={onSort}>Esquives</Th>
          <Th field="blocks" currentSort={sort} onSort={onSort}>Blocages</Th>
          <Th field="interrupts" currentSort={sort} onSort={onSort}>Interrupt</Th>
          <Th field="deaths" currentSort={sort} onSort={onSort}>Morts</Th>
          <Th field="time_downed" currentSort={sort} onSort={onSort}>Down (ms)</Th>
          <Th field="cc_taken" currentSort={sort} onSort={onSort}>CC reçus</Th>
          <Th field="barrier_absorbed" currentSort={sort} onSort={onSort}>Barrier abs.</Th>
          <Th field="presence_pct" currentSort={sort} onSort={onSort}>Présence %</Th>
          <Th field="dist_to_commander" currentSort={sort} onSort={onSort}>Dist. Cmd</Th>
          <Th field="kill_part" currentSort={sort} onSort={onSort}>Kill Part</Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p, i) => (
          <tr key={p.agent_id} style={{ background: i % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)" }}>
            <IdentityCells player={p} />
            <td style={TD_STYLE}>{p.defense.damage_taken.toLocaleString()}</td>
            <td style={TD_STYLE}>{p.defense.dodges}</td>
            <td style={TD_STYLE}>{p.defense.blocks}</td>
            <td style={TD_STYLE}>{p.defense.interrupts}</td>
            <td style={TD_STYLE}>{p.defense.deaths}</td>
            <td style={TD_STYLE}>{p.defense.time_downed_ms}</td>
            <td style={TD_STYLE}>{p.defense.cc_taken}</td>
            <td style={TD_STYLE}>{p.defense.barrier_absorbed.toLocaleString()}</td>
            <td style={{ ...TD_STYLE, fontVariantNumeric: "tabular-nums" }}>
              {p.defense.presence_pct != null ? `${p.defense.presence_pct.toFixed(0)}%` : "—"}
            </td>
            <td style={{ ...TD_STYLE, fontVariantNumeric: "tabular-nums" }}>
              {p.defense.dist_to_commander != null ? p.defense.dist_to_commander.toFixed(0) : "—"}
            </td>
            <td style={TD_STYLE}>{p.defense.kill_participation}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
