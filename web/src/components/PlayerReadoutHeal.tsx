"use client";

/**
 * Tour 6 Wave 7 (Workstream F): Combat-readout Heal table
 * (per docs/v0.9.0-combat-readout-design.md §4).
 *
 * AG Grid Community 34 Client Component for per-player healing
 * contribution. Renders the 6 heal-aspect columns (``heal_total``
 * / ``hps`` / ``barrier_total`` / ``barrier_ps`` / ``cleanses``
 * / ``stun_breaks``) PREPENDED with the 5 SHARED_COLUMNS.
 *
 * Default sort per design doc §13:
 * 1. ``subgroup`` ASC
 * 2. ``hps`` DESC (top-healer of each squad first)
 * 3. ``agent_id`` ASC tie-breaker
 *
 * Per design doc §7, barrier is a SEPARATE field from heal
 * (the canonical "barrier is separable" lock-in). The
 * SCAFFOLD-getter plumbing from Wave 6 PART-2 makes
 * ``barrier_total`` + ``barrier_ps`` carry real phase-6-v2
 * values once the parser-side ``barrier_portion`` table lands;
 * pre-phase-6-v2 streams show ``0`` for both columns.
 */
import type { ColDef, SortModelItem } from "ag-grid-community";

import type { PlayerReadoutOut } from "@/lib/api";

import { PlayerReadoutGrid } from "./PlayerReadoutGrid";

const HEAL_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  { field: "heal.heal_total", headerName: "Heal total", width: 130 },
  { field: "heal.hps", headerName: "HPS", width: 110 },
  { field: "heal.barrier_total", headerName: "Barrier total", width: 140 },
  { field: "heal.barrier_ps", headerName: "Barrier/s", width: 120 },
  { field: "heal.cleanses", headerName: "Cleanses", width: 110 },
  { field: "heal.stun_breaks", headerName: "Breakstunt", width: 110 },
];

// Default sort per design doc §13: subgroup ASC + hps DESC + agent_id
// ASC tiebreaker. Array order = sort priority (AG Grid v34
// ``SortModelItem`` does NOT carry ``sortIndex``).
const HEAL_DEFAULT_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "heal.hps", sort: "desc" },
  { colId: "agent_id", sort: "asc" },
];

export function PlayerReadoutHeal({ rows }: { rows: PlayerReadoutOut[] }) {
  return (
    <PlayerReadoutGrid
      testId="player-readout-heal"
      rows={rows}
      aspectColumns={HEAL_COLUMNS}
      defaultSort={HEAL_DEFAULT_SORT}
    />
  );
}
