"use client";

/**
 * Tour 6 Wave 7 (Workstream F): Combat-readout Boons table
 * (per docs/v0.9.0-combat-readout-design.md §5).
 *
 * AG Grid Community 34 Client Component for per-player boon
 * output / intake. Renders the 9 boons-aspect columns
 * (``boons_out_rate`` / ``boons_in_rate`` + the 6 fixed boon
 * columns ``stability_out`` / ``alacrity_out`` /
 * ``resistance_out`` / ``aegis_out`` / ``superspeed_out`` /
 * ``stealth_out`` + an ``other_boons_total`` cell that
 * SUM-aggregates the ``other_boons_out: dict[str, int]``
 * per row) PREPENDED with the 5 SHARED_COLUMNS.
 *
 * §11 open-question resolution
 * ============================
 * The design doc §11 listed "Autres boons" rendering as open
 * (a) dynamic columns, (b) collapsed tooltip cell, (c) top-3
 * other boons. Per thinker's recommendation H + the project's
 * "compact-grid" precedent (SkillsTable omits dynamic columns),
 * we ship option (b) collapsed: a single "Other boons (total)"
 * column whose value is sum-of-dict-values. A future enhancement
 * can swap to option (c) without a wire-shape change (the
 * ``other_boons_out`` dict stays the source-of-truth).
 *
 * Default sort per design doc §13:
 * 1. ``subgroup`` ASC
 * 2. ``boons_out_rate`` DESC (top boon provider of each squad first)
 * 3. ``agent_id`` ASC tie-breaker
 */
import { AgGridReact } from "ag-grid-react";
import type { ColDef, SortModelItem } from "ag-grid-community";

import type { PlayerReadoutOut } from "@/lib/api";

import {
  AGENT_ID_TIEBREAKER,
  AG_GRID_PROPS,
  SHARED_COLUMNS,
} from "./PlayerReadoutBase";

/**
 * Sum all values in the ``other_boons_out`` dict for one row.
 * Renders zero when the dict is empty or undefined (the pre-
 * phase-6-v2 SCAFFOLD zero-fallback case).
 */
function sumOtherBoons(
  dict: Record<string, number> | undefined | null,
): number {
  if (!dict) return 0;
  let total = 0;
  for (const key of Object.keys(dict)) {
    const value = dict[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      total += value;
    }
  }
  return total;
}

const BOONS_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  { field: "boons.boons_out_rate", headerName: "Boons out/s", width: 130 },
  { field: "boons.boons_in_rate", headerName: "Boons in/s", width: 130 },
  { field: "boons.stability_out", headerName: "Stabilité", width: 100 },
  { field: "boons.alacrity_out", headerName: "Célérité", width: 100 },
  { field: "boons.resistance_out", headerName: "Résistance", width: 100 },
  { field: "boons.aegis_out", headerName: "Égide", width: 100 },
  { field: "boons.superspeed_out", headerName: "Superspeed", width: 110 },
  { field: "boons.stealth_out", headerName: "Stealth", width: 100 },
  {
    // Dynamic "other_boons_total" cell: SUM of all values in
    // boons.other_boons_out dict per row. Avoids the dynamic-
    // column complexity (per §11) while preserving the wire
    // source-of-truth.
    headerName: "Other boons (total)",
    width: 160,
    valueGetter: (params) =>
      sumOtherBoons(params.data?.boons.other_boons_out),
  },
];

// Default sort per design doc §13: subgroup ASC + boons_out_rate
// DESC + agent_id ASC tiebreaker. Array order = sort priority (AG
// Grid v34 ``SortModelItem`` does NOT carry ``sortIndex``).
const BOONS_DEFAULT_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "boons.boons_out_rate", sort: "desc" },
  { colId: "agent_id", sort: "asc" },
];

export function PlayerReadoutBoons({
  rows,
}: {
  rows: PlayerReadoutOut[];
}) {
  if (rows.length === 0) {
    return (
      <div
        data-testid="player-readout-boons-empty"
        style={{
          padding: "12px 16px",
          border: "1px solid var(--border)",
          borderRadius: 4,
          color: "var(--foreground)",
          opacity: 0.7,
          fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
        }}
      >
        No player rows in this readout.
      </div>
    );
  }

  return (
    <div
      data-testid="player-readout-boons"
      style={{ width: "100%" }}
    >
      <AgGridReact<PlayerReadoutOut>
        rowData={rows}
        columnDefs={[...SHARED_COLUMNS, ...BOONS_COLUMNS, AGENT_ID_TIEBREAKER]}
        defaultColDef={{ comparator: (a, b) => (Number(a ?? 0) - Number(b ?? 0)) || 0 }}
        {...AG_GRID_PROPS}
        initialState={{ sort: { sortModel: BOONS_DEFAULT_SORT } }}
        getRowId={(params) => String(params.data.agent_id)}
      />
    </div>
  );
}
