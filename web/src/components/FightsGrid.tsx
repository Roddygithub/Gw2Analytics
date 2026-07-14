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
  type ColDef,
  type ICellRendererParams,
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

import type { FightRow } from "@/lib/api";
import {
  FIGHTS_GRID_COLUMN_AGENTS,
  FIGHTS_GRID_COLUMN_BUILD,
  FIGHTS_GRID_COLUMN_ENCOUNTER,
  FIGHTS_GRID_COLUMN_FIGHT_ID,
  FIGHTS_GRID_COLUMN_GAME_TYPE,
  FIGHTS_GRID_COLUMN_STARTED_UTC,
} from "@/lib/copy/fights-grid";

// Side-effect import: registers AllCommunityModule exactly once
// (see ag-grid-setup.ts). Importing here (rather than re-running
// ``ModuleRegistry.registerModules``) is what allows the new
// ``/fights/[id]`` page's TargetRollupsGrid to ship without
// re-registering the module on its own -- the module graph
// guarantees a single evaluation of the import side-effect.
import "./ag-grid-setup";

const GRID_THEME = "ag-theme-quartz-dark";

export function FightsGrid({ rows }: { rows: FightRow[] }) {
  const columnDefs = useMemo<ColDef<FightRow>[]>(
    () => [
      {
        field: "id",
        headerName: FIGHTS_GRID_COLUMN_FIGHT_ID,
        sortable: true,
        filter: true,
        minWidth: 240,
        // Phase 7 v1 of web: the fight id is the primary key into
        // the new drill-down page. Render it as an anchor so a
        // single click on the row carries the analyst to the
        // per-target damage + healing roll-up + time-bucketed
        // events surface. A plain anchor is intentional (not
        // ``next/link``) -- AG Grid renders the cell out of the
        // React tree, so the client-side router prefetch is not
        // available here; a full-page navigation on click is
        // acceptable for an analyst surface that's expected to be
        // ``force-dynamic`` + ``cache: no-store`` on the other end.
        cellRenderer: (params: ICellRendererParams<FightRow>) => {
          const id = params.value;
          if (typeof id !== "string") {
            return null;
          }
          return <a href={`/fights/${id}`}>{id}</a>;
        },
      },
      {
        field: "encounter_id",
        headerName: FIGHTS_GRID_COLUMN_ENCOUNTER,
        sortable: true,
        filter: true,
        maxWidth: 120,
      },
      {
        field: "agent_count",
        headerName: FIGHTS_GRID_COLUMN_AGENTS,
        sortable: true,
        filter: true,
        maxWidth: 100,
      },
      {
        field: "build_version",
        headerName: FIGHTS_GRID_COLUMN_BUILD,
        sortable: true,
        filter: true,
        maxWidth: 120,
      },
      {
        field: "started_at",
        headerName: FIGHTS_GRID_COLUMN_STARTED_UTC,
        sortable: true,
        filter: true,
        maxWidth: 220,
      },
      {
        field: "game_type",
        headerName: FIGHTS_GRID_COLUMN_GAME_TYPE,
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
