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
 * All defense columns (``dodges``, ``blocks``, ``interrupts``,
 * ``time_downed_ms``) carry real values from the v0.12.x
 * Phase 6 v2 parser stream (statechange dispatch + down-state
 * lifecycle tracking). ``time_downed_ms`` may be 0 for fights
 * without captured down-state cycles.
 */
import type { ColDef, SortModelItem } from "ag-grid-community";

import type { PlayerReadoutOut } from "@/lib/api";

import { PlayerReadoutGrid } from "./PlayerReadoutGrid";

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

export function PlayerReadoutDefense({ rows }: { rows: PlayerReadoutOut[] }) {
  return (
    <PlayerReadoutGrid
      testId="player-readout-defense"
      rows={rows}
      aspectColumns={DEFENSE_COLUMNS}
      defaultSort={DEFENSE_DEFAULT_SORT}
    />
  );
}
