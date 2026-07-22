"use client";

/**
 * Client-side tab that fetches the combat readout + positions + events
 * and renders the full fight analysis view:
 *   - Summary cards (Top 3 per category)
 *   - Timeline chart
 *   - 4 tables (Damage, Heal, Boons, Defense) with horizontal bars
 *
 * Fetches client-side using relative URLs (Next.js rewrite proxy)
 * to avoid the RSC → Client Component prop serialization gap that
 * caused "No Rows To Show" despite data being loaded.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ColDef, ICellRendererParams, SortModelItem } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";

import {
  fetchFightReadout,
  fetchFightPositions,
  fetchFightEvents,
  type FightReadoutOut,
  type FightPositionsOut,
  type FightEventsSummaryRow,
  type PlayerReadoutBoonsOut,
  type PlayerReadoutOut,
} from "@/lib/api";
import { appGridTheme } from "./ag-grid-setup";
import { FightSummaryCards } from "./FightSummaryCards";
import {
  EliteSpecCellRenderer,
  CommanderCellRenderer,
} from "./PlayerReadoutCells";
import { ROLE_COLORS, ROLE_FALLBACK } from "@/lib/roleColors";

/* ------------------------------------------------------------------ *
 *  Shared helpers
 * ------------------------------------------------------------------ */

const NUMERIC_COMPARATOR = (a: unknown, b: unknown) =>
  Number(a ?? 0) - Number(b ?? 0) || 0;

const GRID_CONTAINER_STYLE: React.CSSProperties = {
  width: "100%",
  height: 400,
};

const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
};

/* ------------------------------------------------------------------ *
 *  Bar cell renderers — with gradients, tooltips, and hover effects
 * ------------------------------------------------------------------ */

const BAR_BG = "rgba(255,255,255,0.04)";
const BAR_HEIGHT = 18;
const BAR_RADIUS = 4;

/**
 * Render a gradient bar segment with label on hover.
 * Uses inline gradients for smooth color transitions.
 */
function BarSegment({
  pct,
  gradient,
  label,
}: {
  pct: number;
  gradient: string;
  label: string;
}) {
  return (
    <div
      style={{
        width: `${Math.max(pct, 1.5)}%`,
        height: "100%",
        background: gradient,
        transition: "width 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s",
        opacity: pct > 1 ? 1 : 0.4,
        position: "relative",
      }}
      title={label}
    >
      {/* Subtle shimmer overlay on hover — visible via parent hover */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.08) 50%, transparent 100%)",
          transition: "opacity 0.3s",
          opacity: 0,
        }}
        className="bar-shimmer"
      />
    </div>
  );
}

/** Horizontal stacked bar with label */
function BarStack({
  segments,
  total,
}: {
  segments: { pct: number; gradient: string; label: string }[];
  total: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        height: "100%",
        padding: "2px 0",
      }}
    >
      {/* Bar track */}
      <div
        style={{
          flex: 1,
          height: BAR_HEIGHT,
          background: BAR_BG,
          borderRadius: BAR_RADIUS,
          overflow: "hidden",
          display: "flex",
          minWidth: 80,
          boxShadow: "inset 0 1px 2px rgba(0,0,0,0.3)",
        }}
        title={segments.map((s) => s.label).join(" · ")}
      >
        {segments.map((s, i) => (
          <BarSegment key={i} pct={s.pct} gradient={s.gradient} label={s.label} />
        ))}
      </div>

      {/* Total value */}
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          fontVariantNumeric: "tabular-nums",
          whiteSpace: "nowrap",
          minWidth: 52,
          textAlign: "right",
          letterSpacing: "0.01em",
          color: "var(--foreground)",
          opacity: 0.9,
        }}
      >
        {total}
      </span>
    </div>
  );
}

/** DPS stacked bar: power (amber) + condi (red) */
function DpsBarCellRenderer(params: ICellRendererParams<PlayerReadoutOut>) {
  const d = params.data;
  if (!d) return null;
  const power = d.damage.dps_power;
  const condi = d.damage.dps_condi;
  const total = d.damage.dps_total || power + condi;
  const max = total || 1;
  return (
    <BarStack
      segments={[
        {
          pct: (power / max) * 100,
          gradient: "linear-gradient(135deg, #f59e0b, #d97706)",
          label: `Power DPS: ${power.toFixed(0)}`,
        },
        {
          pct: (condi / max) * 100,
          gradient: "linear-gradient(135deg, #ef4444, #dc2626)",
          label: `Condi DPS: ${condi.toFixed(0)}`,
        },
      ]}
      total={total.toFixed(0)}
    />
  );
}

/** Heal stacked bar: heal (green) + barrier (cyan) */
function HealBarCellRenderer(params: ICellRendererParams<PlayerReadoutOut>) {
  const d = params.data;
  if (!d) return null;
  const hps = d.heal.hps;
  const bps = d.heal.barrier_ps;
  const total = hps + bps || 1;
  return (
    <BarStack
      segments={[
        {
          pct: (hps / total) * 100,
          gradient: "linear-gradient(135deg, #22c55e, #16a34a)",
          label: `Heal/s: ${hps.toFixed(1)}`,
        },
        {
          pct: (bps / total) * 100,
          gradient: "linear-gradient(135deg, #06b6d4, #0891b2)",
          label: `Barrier/s: ${bps.toFixed(1)}`,
        },
      ]}
      total={(d.heal.heal_total ?? 0).toFixed(0)}
    />
  );
}

/** Boons stacked bar: out (purple) + in (indigo) */
function BoonsBarCellRenderer(params: ICellRendererParams<PlayerReadoutOut>) {
  const d = params.data;
  if (!d) return null;
  const outRate = d.boons.boons_out_rate ?? 0;
  const inRate = d.boons.boons_in_rate ?? 0;
  const max = Math.max(outRate, inRate, 1);
  return (
    <BarStack
      segments={[
        {
          pct: (outRate / max) * 100,
          gradient: "linear-gradient(135deg, #a855f7, #9333ea)",
          label: `Boons out/s: ${outRate.toFixed(1)}`,
        },
        {
          pct: (inRate / max) * 100,
          gradient: "linear-gradient(135deg, #6366f1, #4f46e5)",
          label: `Boons in/s: ${inRate.toFixed(1)}`,
        },
      ]}
      total={`${outRate.toFixed(1)}/s`}
    />
  );
}

/* ------------------------------------------------------------------ *
 *  Role badge cell renderer — coloured pills matching FightSummaryCards
 * ------------------------------------------------------------------ */

function RoleBadgeCellRenderer(params: ICellRendererParams<PlayerReadoutOut>) {
  const roles = params.value as string[] | undefined;
  if (!Array.isArray(roles) || roles.length === 0) return <span>—</span>;
  return (
    <span style={{ display: "inline-flex", gap: 2, flexWrap: "wrap", alignItems: "center", height: "100%" }}>
      {roles.map((role) => {
        const c = ROLE_COLORS[role] ?? ROLE_FALLBACK;
        return (
          <span
            key={role}
            style={{
              padding: "0 5px",
              borderRadius: 3,
              fontSize: 9,
              fontWeight: 700,
              lineHeight: "15px",
              background: c.bg,
              color: c.fg,
              letterSpacing: "0.03em",
            }}
          >
            {role}
          </span>
        );
      })}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 *  Shared column definitions
 * ------------------------------------------------------------------ */

const SHARED_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  {
    field: "subgroup",
    headerName: "Groupe",
    width: 80,
    valueFormatter: (p) => {
      const v = p.value;
      if (v == null) return "(no squad)";
      if (typeof v === "number") return v === 0 ? "(no squad)" : `Sub ${v}`;
      return String(v);
    },
  },
  { field: "name", headerName: "Nom", width: 160 },
  {
    field: "elite_spec",
    headerName: "Spécialisation",
    width: 180,
    cellRenderer: EliteSpecCellRenderer,
  },
  {
    field: "is_commander",
    headerName: "Cmd",
    width: 60,
    cellRenderer: CommanderCellRenderer,
  },
  {
    colId: "roles",
    headerName: "Rôles",
    width: 130,
    valueGetter: (params) => params.data?.roles ?? [],
    valueFormatter: () => "",
    cellRenderer: RoleBadgeCellRenderer,
  },
];

/* ------------------------------------------------------------------ *
 *  Damage columns
 * ------------------------------------------------------------------ */

const DAMAGE_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  {
    headerName: "DPS (power / condi)",
    width: 230,
    cellRenderer: DpsBarCellRenderer,
    comparator: (a: unknown, b: unknown, nodeA, nodeB) => {
      const aVal = nodeA.data?.damage.dps_total ?? 0;
      const bVal = nodeB.data?.damage.dps_total ?? 0;
      return bVal - aVal;
    },
  },
  { field: "damage.strips", headerName: "Strips", width: 90 },
  { field: "damage.cc_applied", headerName: "CC", width: 70 },
  { field: "damage.down_contribution_dps", headerName: "Down DPS", width: 110 },
  { field: "damage.cleave_targets", headerName: "Cleave", width: 80 },
  { field: "damage.kills", headerName: "Kills", width: 60 },
  { field: "defense.deaths", headerName: "Morts", width: 60 },
  { field: "damage.kill_participation", headerName: "Kill Part", width: 80 },
];

const DAMAGE_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "damage.down_contribution_dps", sort: "desc" },
];

/* ------------------------------------------------------------------ *
 *  Heal columns
 * ------------------------------------------------------------------ */

const HEAL_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  {
    headerName: "Heal / Barrier",
    width: 230,
    cellRenderer: HealBarCellRenderer,
    comparator: (a: unknown, b: unknown, nodeA, nodeB) => {
      const aVal =
        (nodeA.data?.heal.hps ?? 0) + (nodeA.data?.heal.barrier_ps ?? 0);
      const bVal =
        (nodeB.data?.heal.hps ?? 0) + (nodeB.data?.heal.barrier_ps ?? 0);
      return bVal - aVal;
    },
  },
  { field: "heal.cleanses", headerName: "Cleanses", width: 100 },
  { field: "heal.stun_breaks", headerName: "Breakstun", width: 110 },
];

const HEAL_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "heal.stun_breaks", sort: "desc" },
];

/* ------------------------------------------------------------------ *
 *  Boon uptime grouped bar renderer — shows a compact group average
 *  with a colored bar and individual values in the tooltip.
 * ------------------------------------------------------------------ */

interface BoonGroupDef {
  colId: string;
  headerName: string;
  fields: (keyof PlayerReadoutBoonsOut)[];
  gradient: string;
}

const BOON_GROUPS: BoonGroupDef[] = [
  {
    colId: "uptime_offensive",
    headerName: "Offensifs",
    fields: ["might_uptime", "fury_uptime", "quickness_uptime", "alacrity_uptime"],
    gradient: "linear-gradient(135deg, #f59e0b, #d97706)",
  },
  {
    colId: "uptime_defensive",
    headerName: "Défensifs",
    fields: [
      "protection_uptime",
      "regeneration_uptime",
      "vigor_uptime",
      "aegis_uptime",
      "stability_uptime",
      "resolution_uptime",
      "resistance_uptime",
    ],
    gradient: "linear-gradient(135deg, #22c55e, #16a34a)",
  },
  {
    colId: "uptime_mobility",
    headerName: "Mobilité",
    fields: ["swiftness_uptime", "superspeed_uptime"],
    gradient: "linear-gradient(135deg, #06b6d4, #0891b2)",
  },
  {
    colId: "uptime_stealth",
    headerName: "Furtivité",
    fields: ["stealth_uptime"],
    gradient: "linear-gradient(135deg, #a855f7, #7c3aed)",
  },
];

/**
 * Build an uptime group column definition for AG Grid.
 * Renders a horizontal bar showing the group average + individual
 * percentages on hover.
 */
function buildUptimeGroupCol(group: BoonGroupDef): ColDef<PlayerReadoutOut> {
  const BOON_LABELS: Record<string, string> = {
    might_uptime: "Might",
    fury_uptime: "Fury",
    quickness_uptime: "Quickness",
    alacrity_uptime: "Alacrity",
    protection_uptime: "Protection",
    regeneration_uptime: "Regen",
    vigor_uptime: "Vigor",
    aegis_uptime: "Aegis",
    stability_uptime: "Stability",
    swiftness_uptime: "Swiftness",
    resistance_uptime: "Resistance",
    resolution_uptime: "Resolution",
    superspeed_uptime: "Superspeed",
    stealth_uptime: "Stealth",
  };

  return {
    colId: group.colId,
    headerName: group.headerName,
    width: 160,
    valueGetter: (params) => {
      const b = params.data?.boons;
      if (!b) return null;
      const vals = group.fields
        .map((f) => (b as unknown as Record<string, number | null>)[f as string])
        .filter((v): v is number => v != null);
      if (vals.length === 0) return null;
      return vals.reduce((a, c) => a + c, 0) / vals.length;
    },
    cellRenderer: (params: ICellRendererParams<PlayerReadoutOut>) => {
      const pct = params.value as number | null;
      return (
        <BarStack
          segments={
            pct != null
              ? [{ pct: Math.min(100, Math.max(0, pct)), gradient: group.gradient, label: `${group.headerName}: ${pct.toFixed(0)}%` }]
              : []
          }
          total={pct != null ? `${pct.toFixed(0)}%` : "—"}
        />
      );
    },
    tooltipValueGetter: (params) => {
      const b = params.data?.boons;
      if (!b) return null;
      const bRec = b as unknown as Record<string, number | null>;
      return group.fields
        .map((f) => {
          const v = bRec[f as string];
          return `${BOON_LABELS[f as string] ?? f}: ${v != null ? `${v.toFixed(0)}%` : "—"}`;
        })
        .join("\n");
    },
    comparator: (a: unknown, b: unknown) =>
      Number(a ?? -1) - Number(b ?? -1) || 0,
  };
}

/* ------------------------------------------------------------------ *
 *  Boons columns
 * ------------------------------------------------------------------ */

const BOONS_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  {
    colId: "boons",
    headerName: "Boons in / out",
    width: 220,
    cellRenderer: BoonsBarCellRenderer,
    comparator: (a: unknown, b: unknown, nodeA, nodeB) => {
      const aVal = nodeA.data?.boons.boons_out_rate ?? 0;
      const bVal = nodeB.data?.boons.boons_out_rate ?? 0;
      return bVal - aVal;
    },
  },
  // Plan 173: uptime bars replacing the 6 raw-count columns.
  // Raw counts (stability_out, etc.) are still available in the
  // API payload but hidden from the default column set.
  ...BOON_GROUPS.map(buildUptimeGroupCol),
  // Plan 173 Phase F: outgoing boons total (sum of all 14 outgoing_*).
  {
    colId: "outgoing_boons",
    headerName: "Boons générés",
    width: 140,
    valueGetter: (params) => {
      const b = params.data?.boons;
      if (!b) return null;
      const fields = [
        "outgoing_might", "outgoing_fury", "outgoing_quickness",
        "outgoing_alacrity", "outgoing_protection", "outgoing_regeneration",
        "outgoing_vigor", "outgoing_aegis", "outgoing_stability",
        "outgoing_swiftness", "outgoing_resistance", "outgoing_resolution",
        "outgoing_superspeed", "outgoing_stealth",
      ] as const;
      const bRec = b as unknown as Record<string, number | null>;
      let total = 0;
      let hasAny = false;
      for (const f of fields) {
        const v = bRec[f as string];
        if (v != null) { total += v; hasAny = true; }
      }
      return hasAny ? total : null;
    },
    valueFormatter: (params) =>
      params.value != null ? (params.value as number).toLocaleString() : "—",
    comparator: NUMERIC_COMPARATOR,
  },
];

const BOONS_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "boons", sort: "desc" },
];

/* ------------------------------------------------------------------ *
 *  Defense columns — built as a function so we can inject
 *  the positionMap (from the positions fetch) at render time.
 * ------------------------------------------------------------------ */

function buildDefenseColumns(
  positionMap: Map<string, { stack_dist: number | null; dist_to_com: number | null; dist_to_commander: number | null }>,
): ColDef<PlayerReadoutOut>[] {
  return [
    { field: "defense.damage_taken", headerName: "Dmg reçu", width: 110 },
    { field: "defense.dodges", headerName: "Esquives", width: 90 },
    { field: "defense.blocks", headerName: "Blocages", width: 100 },
    { field: "defense.interrupts", headerName: "Interrupt", width: 100 },
    { field: "defense.deaths", headerName: "Morts", width: 70 },
    { field: "defense.time_downed_ms", headerName: "Down (ms)", width: 110 },
    { field: "defense.cc_taken", headerName: "CC reçus", width: 100 },
    { field: "defense.barrier_absorbed", headerName: "Barrier abs.", width: 120 },
    // Plan 173 Phase E: presence percentage from event-window buckets.
    {
      field: "defense.presence_pct",
      headerName: "Présence %",
      width: 110,
      valueFormatter: (params) =>
        params.value != null ? `${(params.value as number).toFixed(0)}%` : "—",
      comparator: NUMERIC_COMPARATOR,
    },
    // Position data — merged from the /positions endpoint by account_name
    {
      colId: "stack_dist",
      headerName: "Stack dist",
      width: 100,
      valueGetter: (params) => {
        const account = params.data?.account_name;
        if (!account) return null;
        const pos = positionMap.get(account);
        return pos?.stack_dist;
      },
      valueFormatter: (params) =>
        params.value != null ? `${(params.value as number).toFixed(1)}u` : "—",
      comparator: NUMERIC_COMPARATOR,
    },
    {
      colId: "dist_to_com",
      headerName: "Dist COM",
      width: 100,
      valueGetter: (params) => {
        const account = params.data?.account_name;
        if (!account) return null;
        const pos = positionMap.get(account);
        return pos?.dist_to_com;
      },
      valueFormatter: (params) =>
        params.value != null ? `${(params.value as number).toFixed(1)}u` : "—",
      comparator: NUMERIC_COMPARATOR,
    },
    {
      colId: "dist_to_commander",
      headerName: "Dist Cmd",
      width: 100,
      valueGetter: (params) => {
        const account = params.data?.account_name;
        if (!account) return null;
        const pos = positionMap.get(account);
        return pos?.dist_to_commander;
      },
      valueFormatter: (params) =>
        params.value != null ? `${(params.value as number).toFixed(1)}u` : "—",
      comparator: NUMERIC_COMPARATOR,
      tooltipValueGetter: () => "Distance moyenne au commandant de l'escouade",
    },
  ];
}

const DEFENSE_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "defense.damage_taken", sort: "desc" },
];

/* ------------------------------------------------------------------ *
 *  Timeline mini chart component
 * ------------------------------------------------------------------ */

function TimelineMiniChart({ events }: { events: FightEventsSummaryRow | null }) {
  if (!events || events.event_windows.length === 0) {
    return (
      <div style={EMPTY_STYLE}>
        Aucune donnée temporelle disponible.
      </div>
    );
  }

  const windows = events.event_windows;
  const maxDmg = Math.max(...windows.map((w) => w.damage_total), 1);
  const maxHeal = Math.max(...windows.map((w) => w.healing_total), 1);
  const durationMin = (windows[windows.length - 1]?.end_ms ?? 0) / 60000;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 12 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: "#f59e0b" }} />
          Damage
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: 2, background: "#22c55e" }} />
          Heal
        </span>
        <span style={{ marginLeft: "auto", opacity: 0.6 }}>
          {windows.length} buckets · {durationMin.toFixed(1)} min
        </span>
      </div>
      <div
        style={{
          width: "100%",
          height: 80,
          display: "flex",
          alignItems: "flex-end",
          gap: 1,
          background: "rgba(255,255,255,0.03)",
          borderRadius: 4,
          padding: "4px 0",
          overflow: "hidden",
        }}
      >
        {windows.map((w, i) => {
          const dmgPct = (w.damage_total / maxDmg) * 100;
          const healPct = (w.healing_total / maxHeal) * 100;
          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: "100%",
                display: "flex",
                flexDirection: "column-reverse",
                alignItems: "center",
                gap: 1,
                minWidth: 2,
              }}
              title={`${(w.start_ms / 1000).toFixed(0)}s: dmg=${w.damage_total}, heal=${w.healing_total}`}
            >
              <div
                style={{
                  width: "100%",
                  height: `${Math.max(healPct, 1)}%`,
                  background: "#22c55e",
                  opacity: 0.6,
                  borderRadius: "1px 1px 0 0",
                  transition: "height 0.2s",
                }}
              />
              <div
                style={{
                  width: "100%",
                  height: `${Math.max(dmgPct, 1)}%`,
                  background: "#f59e0b",
                  opacity: 0.8,
                  borderRadius: "1px 1px 0 0",
                  transition: "height 0.2s",
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  Positions summary
 * ------------------------------------------------------------------ */

function PositionsSummary({
  positions,
}: {
  positions: FightPositionsOut | null;
}) {
  if (!positions || positions.players.length === 0) {
    return <div style={EMPTY_STYLE}>Aucune donnée de position.</div>;
  }

  const closePlayers = [...positions.players]
    .sort((a, b) => (a.stack_dist ?? 9999) - (b.stack_dist ?? 9999))
    .slice(0, 5);

  return (
    <div style={{ fontSize: 13, display: "flex", flexDirection: "column", gap: 8 }}>
      <p style={{ opacity: 0.7, margin: 0 }}>
        {positions.players.length} joueurs trackés ·{" "}
        {closePlayers[0]?.stack_dist
          ? `Plus proche stack: ${closePlayers[0].name} (${closePlayers[0].stack_dist?.toFixed(1)}u)`
          : ""}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 *  ReadoutTabClient — main component
 * ------------------------------------------------------------------ */

interface ReadoutTabClientProps {
  fightId: string;
}

export function ReadoutTabClient({ fightId }: ReadoutTabClientProps) {
  // Grid refs for CSV export
  const damageGridRef = useRef<AgGridReact<PlayerReadoutOut>>(null);
  const healGridRef = useRef<AgGridReact<PlayerReadoutOut>>(null);
  const boonsGridRef = useRef<AgGridReact<PlayerReadoutOut>>(null);
  const defenseGridRef = useRef<AgGridReact<PlayerReadoutOut>>(null);

  // State
  const [readout, setReadout] = useState<FightReadoutOut | null>(null);
  const [positions, setPositions] = useState<FightPositionsOut | null>(null);
  const [events, setEvents] = useState<FightEventsSummaryRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch all data on mount
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [r, p, e] = await Promise.all([
        fetchFightReadout(fightId),
        fetchFightPositions(fightId).catch(() => null), // non-fatal
        fetchFightEvents(fightId).catch(() => null), // non-fatal
      ]);
      setReadout(r);
      setPositions(p);
      setEvents(e);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load combat data",
      );
    } finally {
      setLoading(false);
    }
  }, [fightId]);

  useEffect(() => {
    load();
  }, [load]);

  // Build lookup map from positions data (BEFORE early returns — hooks
  // must always be called in the same order regardless of state)
  const positionMap = useMemo(() => {
    const map = new Map<
      string,
      { stack_dist: number | null; dist_to_com: number | null; dist_to_commander: number | null }
    >();
    for (const p of positions?.players ?? []) {
      if (p.account_name) {
        map.set(p.account_name, {
          stack_dist: p.stack_dist,
          dist_to_com: p.dist_to_com,
          dist_to_commander: p.dist_to_commander,
        });
      }
    }
    return map;
  }, [positions]);

  const defenseColumns = useMemo(
    () => buildDefenseColumns(positionMap),
    [positionMap],
  );

  // Loading state
  if (loading) {
    return (
      <div
        style={{
          padding: "24px 0",
          display: "flex",
          alignItems: "center",
          gap: 12,
          opacity: 0.7,
        }}
      >
        <span aria-label="Chargement">⏳</span>
        Chargement des données de combat…
      </div>
    );
  }

  // Error state
  if (error || !readout) {
    return (
      <div
        style={{
          padding: "16px 20px",
          border: "1px solid var(--accent)",
          borderRadius: 4,
          color: "var(--accent)",
        }}
        role="alert"
      >
        {error ?? "Impossible de charger les données de combat."}
      </div>
    );
  }

  const players = readout.players;

  // Role filter state
  const [roleFilter, setRoleFilter] = useState<string | null>(null);
  const allRoles = useMemo(() => {
    const seen = new Set<string>();
    for (const p of players) {
      for (const r of p.roles) seen.add(r);
    }
    return [...seen].sort();
  }, [players]);
  const filteredPlayers = useMemo(() => {
    if (!roleFilter) return players;
    return players.filter((p) => p.roles.includes(roleFilter));
  }, [players, roleFilter]);

  const exportCsv = (gridRef: React.RefObject<AgGridReact<PlayerReadoutOut> | null>, filename: string) => {
    const api = gridRef.current?.api;
    if (!api) return;
    api.exportDataAsCsv({ fileName: filename });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Role filter */}
      {allRoles.length > 1 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <label style={{ fontSize: 12, opacity: 0.7 }}>Filtrer par rôle :</label>
          <select
            value={roleFilter ?? ""}
            onChange={(e) => setRoleFilter(e.target.value || null)}
            style={{
              padding: "3px 8px",
              borderRadius: 4,
              border: "1px solid var(--border)",
              background: "var(--surface)",
              color: "var(--foreground)",
              fontSize: 12,
              fontFamily: "var(--font-geist-sans, sans-serif)",
            }}
          >
            <option value="">Tous ({players.length})</option>
            {allRoles.map((r) => (
              <option key={r} value={r}>
                {r} ({players.filter((p) => p.roles.includes(r)).length})
              </option>
            ))}
          </select>
          {/* X/Y counter — visible when a role filter is active */}
          {roleFilter && (
            <span
              style={{
                fontSize: 11,
                opacity: 0.6,
                fontVariantNumeric: "tabular-nums",
                padding: "1px 8px",
                borderRadius: 3,
                background: "var(--surface)",
                border: "1px solid var(--border)",
              }}
            >
              {filteredPlayers.length}&nbsp;/&nbsp;{players.length} joueurs
            </span>
          )}
        </div>
      )}

      {/* Status banner */}
      <p
        style={{
          padding: "10px 14px",
          border: "1px solid var(--border)",
          borderRadius: 4,
          fontSize: 13,
          opacity: 0.8,
        }}
      >
        {players.length} joueurs · durée {readout.duration_s.toFixed(1)}s
      </p>

      {/* Summary cards */}
      <FightSummaryCards players={players} />

      {/* Timeline */}
      <section>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>
          Timeline des événements
        </h2>
        <TimelineMiniChart events={events} />
      </section>

      {/* Positions */}
      {positions && (
        <section>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px 0" }}>
            Positions
          </h2>
          <PositionsSummary positions={positions} />
        </section>
      )}

      {/* Tableau 1: Damage */}
      <section>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>Dégâts</h2>
          <button
            onClick={() => exportCsv(damageGridRef, `${fightId}-damage.csv`)}
            style={{
              padding: "2px 8px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "var(--surface)",
              color: "var(--foreground)",
              cursor: "pointer",
              fontSize: 11,
              fontFamily: "var(--font-geist-sans, sans-serif)",
              opacity: 0.7,
            }}
            title="Télécharger en CSV"
          >
            ⬇ CSV
          </button>
        </div>
        <div style={GRID_CONTAINER_STYLE}>
          <AgGridReact<PlayerReadoutOut>
            ref={damageGridRef}
            theme={appGridTheme}
            rowData={filteredPlayers}
            columnDefs={[...SHARED_COLUMNS, ...DAMAGE_COLUMNS]}
            defaultColDef={{ comparator: NUMERIC_COMPARATOR, resizable: true }}
            animateRows
            getRowId={(p) => String(p.data.agent_id)}
            initialState={{ sort: { sortModel: DAMAGE_SORT } }}
          />
        </div>
      </section>

      {/* Tableau 2: Heal */}
      <section>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>Soins</h2>
          <button
            onClick={() => exportCsv(healGridRef, `${fightId}-heal.csv`)}
            style={{
              padding: "2px 8px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "var(--surface)",
              color: "var(--foreground)",
              cursor: "pointer",
              fontSize: 11,
              fontFamily: "var(--font-geist-sans, sans-serif)",
              opacity: 0.7,
            }}
            title="Télécharger en CSV"
          >
            ⬇ CSV
          </button>
        </div>
        <div style={GRID_CONTAINER_STYLE}>
          <AgGridReact<PlayerReadoutOut>
            ref={healGridRef}
            theme={appGridTheme}
            rowData={filteredPlayers}
            columnDefs={[...SHARED_COLUMNS, ...HEAL_COLUMNS]}
            defaultColDef={{ comparator: NUMERIC_COMPARATOR, resizable: true }}
            animateRows
            getRowId={(p) => String(p.data.agent_id)}
            initialState={{ sort: { sortModel: HEAL_SORT } }}
          />
        </div>
      </section>

      {/* Tableau 3: Boons */}
      <section>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>Boons</h2>
          <button
            onClick={() => exportCsv(boonsGridRef, `${fightId}-boons.csv`)}
            style={{
              padding: "2px 8px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "var(--surface)",
              color: "var(--foreground)",
              cursor: "pointer",
              fontSize: 11,
              fontFamily: "var(--font-geist-sans, sans-serif)",
              opacity: 0.7,
            }}
            title="Télécharger en CSV"
          >
            ⬇ CSV
          </button>
        </div>
        <div style={GRID_CONTAINER_STYLE}>
          <AgGridReact<PlayerReadoutOut>
            ref={boonsGridRef}
            theme={appGridTheme}
            rowData={filteredPlayers}
            columnDefs={[...SHARED_COLUMNS, ...BOONS_COLUMNS]}
            defaultColDef={{ comparator: NUMERIC_COMPARATOR, resizable: true }}
            animateRows
            getRowId={(p) => String(p.data.agent_id)}
            initialState={{ sort: { sortModel: BOONS_SORT } }}
          />
        </div>
      </section>

      {/* Tableau 4: Defense */}
      <section>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>Défense &amp; Positionnement</h2>
          <button
            onClick={() => exportCsv(defenseGridRef, `${fightId}-defense.csv`)}
            style={{
              padding: "2px 8px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "var(--surface)",
              color: "var(--foreground)",
              cursor: "pointer",
              fontSize: 11,
              fontFamily: "var(--font-geist-sans, sans-serif)",
              opacity: 0.7,
            }}
            title="Télécharger en CSV"
          >
            ⬇ CSV
          </button>
        </div>
        <div style={GRID_CONTAINER_STYLE}>
          <AgGridReact<PlayerReadoutOut>
            ref={defenseGridRef}
            theme={appGridTheme}
            rowData={filteredPlayers}
            columnDefs={[...SHARED_COLUMNS, ...defenseColumns]}
            defaultColDef={{ comparator: NUMERIC_COMPARATOR, resizable: true }}
            animateRows
            getRowId={(p) => String(p.data.agent_id)}
            initialState={{ sort: { sortModel: DEFENSE_SORT } }}
          />
        </div>
      </section>
    </div>
  );
}
