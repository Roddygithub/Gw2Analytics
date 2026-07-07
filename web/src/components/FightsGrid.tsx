/**
 * Client Component wrapper around AG Grid Community for the fights
 * list. The Server Component (``app/fights/page.tsx``) fetches the
 * rows; this component hydrates them into the table.
 *
 * Why AG Grid Community
 * =====================
 * Zero-license permissive table for an analyst-facing WvW roster:
 * inline column sort, filter, and pagination are built in.
 *
 * Why two renders
 * ===============
 * ``AG Grid Community 33+`` ships in tree-shaken mode and requires
 * an explicit module registration (the framework refactor that
 * removed the implicit-everything bundle). We register the
 * AllCommunityModule once at module load so the grid's built-in
 * features are wired before the first render.
 */

"use client";

import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  type ColDef,
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

import type { FightRow } from "@/lib/api";

ModuleRegistry.registerModules([AllCommunityModule]);

const GRID_THEME = "ag-theme-quartz-dark";

export function FightsGrid({ rows }: { rows: FightRow[] }) {
  const columnDefs = useMemo<ColDef<FightRow>[]>(
    () => [
      {
        field: "id",
        headerName: "Fight ID",
        sortable: true,
        filter: true,
        minWidth: 240,
      },
      {
        field: "encounter_id",
        headerName: "Encounter",
        sortable: true,
        filter: true,
        maxWidth: 120,
      },
      {
        field: "agent_count",
        headerName: "Agents",
        sortable: true,
        filter: true,
        maxWidth: 100,
      },
      {
        field: "build_version",
        headerName: "Build",
        sortable: true,
        filter: true,
        maxWidth: 120,
      },
      {
        field: "started_at",
        headerName: "Started (UTC)",
        sortable: true,
        filter: true,
        maxWidth: 220,
      },
      {
        field: "game_type",
        headerName: "Game type",
        sortable: true,
        filter: true,
        maxWidth: 110,
      },
    ],
    [],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      resizable: true,
      suppressMenu: true,
    }),
    [],
  );

  return (
    <div
      className={GRID_THEME}
      style={{ height: 600, width: "100%" }}
    >
      <AgGridReact<FightRow>
        rowData={rows}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        pagination
        paginationPageSize={25}
        animateRows
      />
    </div>
  );
}
