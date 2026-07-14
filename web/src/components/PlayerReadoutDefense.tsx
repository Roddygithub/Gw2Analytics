"use client";

/**
 * Tour 6 Wave 7 (Workstream F): Combat-readout Defense table
 * (per docs/v0.9.0-combat-readout-design.md §6: "Defense &
 * Positioning").
 *
 * AG Grid Community 34 Client Component for per-player defense
 * roll-up. Renders the 8 defense-aspect columns
 * (``damage_taken`` / ``cc_taken`` / ``deaths`` /
 * ``time_downed_ms`` / ``dodges`` / ``blocks`` / ``interrupts``
 * / ``barrier_absorbed``) PREPENDED with the 5 SHARED_COLUMNS.
 *
 * Default sort per design doc §13 ("defensive load is the
 * leading indicator"):
 * 1. ``subgroup`` ASC
 * 2. ``damage_taken`` DESC (most-targeted player of each squad
 *    first; this surfaces tank / bunker identification at a
 *    glance)
 * 3. ``agent_id`` ASC tie-breaker
 *
 * Pre-phase-6-v2 SCAFFOLD-zero note
 * =================================
 * ``time_downed_ms`` requires the parser to track the per-
 * target down-state lifecycle across events (Phase 6 v2 work);
 * the SCAFFOLD-zero contract leaves it at ``0`` until that
 * lands. The Wave 6 PART-2 wire-shape keeps the column on the
 * grid so a future phase-6-v2 stream automatically picks up the
 * real value without a UI change. ``dodges`` + ``blocks`` +
 * ``interrupts`` await the statechange event subclasses
 * (DodgeEvent / BlockEvent / InterruptEvent) which the
 * Wave 5 SCAFFOLD shipped but whose parser yield paths remain
 * Phase 6 v2 work.
 */
import { AgGridReact } from "ag-grid-react";
import type { ColDef, SortModelItem } from "ag-grid-community";

import type { PlayerReadoutOut } from "@/lib/api";

import "./ag-grid-setup";
import {
  AGENT_ID_TIEBREAKER,
  AG_GRID_PROPS,
  SHARED_COLUMNS,
} from "./PlayerReadoutBase";

const DEFENSE_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  { field: "defense.damage_taken", headerName: "Damage reçu", width: 130 },
  { field: "defense.cc_taken", headerName: "CC reçus", width: 110 },
  { field: "defense.deaths", headerName: "Morts", width: 100 },
  { field: "defense.time_downed_ms", headerName: "Temps down (ms)", width: 150 },
  { field: "defense.dodges", headerName: "Esquives", width: 110 },
  { field: "defense.blocks", headerName: "Blocages", width: 110 },
  { field: "defense.interrupts", headerName: "Interruptions", width: 130 },
  { field: "defense.barrier_absorbed", headerName: "Barrier abs.", width: 130 },
];

// Default sort per design doc §13: subgroup ASC + damage_taken DESC
// + agent_id ASC tiebreaker ("defensive load is the leading
// indicator"). Array order = sort priority (AG Grid v34
// ``SortModelItem`` does NOT carry ``sortIndex``).
const DEFENSE_DEFAULT_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "defense.damage_taken", sort: "desc" },
  { colId: "agent_id", sort: "asc" },
];

export function PlayerReadoutDefense({
  rows,
}: {
  rows: PlayerReadoutOut[];
}) {
  if (rows.length === 0) {
    return (
      <div
        data-testid="player-readout-defense-empty"
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
      data-testid="player-readout-defense"
      style={{ width: "100%" }}
    >
      <AgGridReact<PlayerReadoutOut>
        rowData={rows}
        columnDefs={[...SHARED_COLUMNS, ...DEFENSE_COLUMNS, AGENT_ID_TIEBREAKER]}
        defaultColDef={{ comparator: (a, b) => (Number(a ?? 0) - Number(b ?? 0)) || 0 }}
        {...AG_GRID_PROPS}
        initialState={{ sort: { sortModel: DEFENSE_DEFAULT_SORT } }}
        getRowId={(params) => String(params.data.agent_id)}
      />
    </div>
  );
}
