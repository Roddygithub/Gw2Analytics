"use client";

/**
 * Tour 6 Wave 7 (Workstream F): Combat-readout Damage table
 * (per docs/v0.9.0-combat-readout-design.md §3).
 *
 * AG Grid Community 34 Client Component. Renders the 7
 * damage-aspect columns (``dps_total`` / ``dps_power`` /
 * ``dps_condi`` / ``strips`` / ``cc_applied`` /
 * ``down_contribution_dps`` / ``kills`` + the agent_id hidden
 * tiebreaker) PREPENDED with the 5 SHARED_COLUMNS from
 * :module:`PlayerReadoutBase`.
 *
 * Default sort per design doc §13:
 * 1. ``subgroup`` ASC (squad-first grouping)
 * 2. ``dps_total`` DESC (top-damage-dealer of each squad first)
 * 3. ``agent_id`` ASC (final deterministic tie-breaker; the
 *    column is hidden by default but participates in sort)
 *
 * The component is a thin wrapper around ``AgGridReact`` -- the
 * SCAFFOLD-getter plumbing we wired in Wave 6 PART-2 makes the
 * ``dps_power`` / ``dps_condi`` fields carry real phase-6-v2
 * values once the parser-side ``condi_portion`` table lands.
 * Pre-phase-6-v2 streams show ``dps_power=0.0`` + ``dps_condi=0.0``
 * for every row -- the byte-equivalent SCAFFOLD wire shape.
 */
import { AgGridReact } from "ag-grid-react";
import type { ColDef, SortModelItem } from "ag-grid-community";

import type {
  PlayerReadoutOut,
} from "@/lib/api";

import "./ag-grid-setup";
import {
  AGENT_ID_TIEBREAKER,
  DEFAULT_GRID_OPTIONS,
  SHARED_COLUMNS,
} from "./PlayerReadoutBase";

const DAMAGE_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  { field: "damage.dps_total", headerName: "DPS total", width: 130 },
  { field: "damage.dps_power", headerName: "DPS power", width: 130 },
  { field: "damage.dps_condi", headerName: "DPS condi", width: 130 },
  { field: "damage.strips", headerName: "Strips", width: 110 },
  { field: "damage.cc_applied", headerName: "CC appliqués", width: 130 },
  {
    field: "damage.down_contribution_dps",
    headerName: "Down contrib DPS",
    width: 160,
  },
  { field: "damage.kills", headerName: "Kills", width: 100 },
];

// Default sort per design doc §13: subgroup ASC + dps_total DESC +
// agent_id ASC tiebreaker.
const DAMAGE_DEFAULT_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc", sortIndex: 0 },
  { colId: "damage.dps_total", sort: "desc", sortIndex: 1 },
  { colId: "agent_id", sort: "asc", sortIndex: 2 },
];

export function PlayerReadoutDamage({
  rows,
}: {
  rows: PlayerReadoutOut[];
}) {
  if (rows.length === 0) {
    return (
      <div
        data-testid="player-readout-damage-empty"
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
      data-testid="player-readout-damage"
      style={{ width: "100%" }}
    >
      <AgGridReact<PlayerReadoutOut>
        rowData={rows}
        columnDefs={[...SHARED_COLUMNS, ...DAMAGE_COLUMNS, AGENT_ID_TIEBREAKER]}
        defaultColDef={DEFAULT_GRID_OPTIONS}
        initialState={{ sort: { sortModel: DAMAGE_DEFAULT_SORT } }}
        getRowId={(params) => String(params.data.agent_id)}
      />
    </div>
  );
}
