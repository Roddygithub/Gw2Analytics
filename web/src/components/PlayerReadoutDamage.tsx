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
 *    column is hidden by default but participates in sort
 *    priority via array order — AG Grid Community v34
 *    ``SortModelItem`` omits ``sortIndex``).
 *
 * The component is a thin wrapper around ``PlayerReadoutGrid``
 * -- the SCAFFOLD-getter plumbing we wired in Wave 6 PART-2 makes
 * the ``dps_power`` / ``dps_condi`` fields carry real phase-6-v2
 * values once the parser-side ``condi_portion`` table lands.
 * Pre-phase-6-v2 streams show ``dps_power=0.0`` + ``dps_condi=0.0``
 * for every row -- the byte-equivalent SCAFFOLD wire shape.
 */
import type { ColDef, SortModelItem } from "ag-grid-community";

import type { PlayerReadoutOut } from "@/lib/api";

import { PlayerReadoutGrid } from "./PlayerReadoutGrid";

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
// agent_id ASC tiebreaker. Array order is the sort priority (AG Grid
// Community v34's SortModelItem does NOT carry `sortIndex`; the
// multi-column sort priority is the array index).
const DAMAGE_DEFAULT_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "damage.dps_total", sort: "desc" },
  { colId: "agent_id", sort: "asc" },
];

export function PlayerReadoutDamage({ rows }: { rows: PlayerReadoutOut[] }) {
  return (
    <PlayerReadoutGrid
      testId="player-readout-damage"
      rows={rows}
      aspectColumns={DAMAGE_COLUMNS}
      defaultSort={DAMAGE_DEFAULT_SORT}
    />
  );
}
