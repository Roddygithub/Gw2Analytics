"use client";

/**
 * AG Grid Community wrapper for the ``/players`` paginated list.
 *
 * Mirrors the visual + behavioural contract of :class:`FightsGrid`
 * (Quartz dark theme, sortable + filterable columns, 25-row
 * pagination) but with a column spec tailored to the cross-fight
 * roll-up. The ``account_name`` column is rendered as an anchor
 * to ``/players/{URL-encoded-account_name}`` so a single click
 * carries the analyst to the per-account drill-down page.
 *
 * Why a dedicated grid (vs reusing FightsGrid)
 * ============================================
 * The row shape differs on every column (account_name + name +
 * profession + elite_spec + fights_attended + 3 totals vs fight
 * id + build_version + encounter_id + agent_count + started_at
 * + game_type). A single generic grid with a conditional branch
 * on the column set would couple two unrelated affordances; a
 * focused grid keeps the column spec at the call site.
 *
 * Module registration side-effect
 * ===============================
 * Importing ``./ag-grid-setup`` runs the
 * ``ModuleRegistry.registerModules([AllCommunityModule])`` call
 * exactly once across the whole module graph.
 */

import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  type ColDef,
  type ValueFormatterParams,
  type ICellRendererParams,
} from "ag-grid-community";
import { appGridTheme } from "./ag-grid-setup";
import type { PlayerListRow } from "@/lib/api";
import type { CsvColumn } from "@/lib/csv";
import { CsvDownloadButton } from "./CsvDownloadButton";
import {
  EMPTY_STYLE,
  FLEX_COLUMN_STYLE,
  FLEX_END_STYLE,
  gridContainerStyle,
  LINK_STYLE,
} from "@/shared/styles";

const GRID_HEIGHT_PX = 480;

const GRID_CONTAINER_STYLE = gridContainerStyle(GRID_HEIGHT_PX);

/**
 * CSV column spec for the ``/players`` paginated list. The order
 * matches the on-screen column order so the downloaded file
 * reads naturally. ``fights_attended`` + the 3 totals are
 * unformatted integers (raw values); the column spec deliberately
 * omits ``decimals`` for these.
 */
const CSV_COLUMNS: CsvColumn<PlayerListRow>[] = [
  { field: "account_name", headerName: "Account" },
  { field: "name", headerName: "Character" },
  { field: "profession", headerName: "Profession" },
  { field: "elite_spec", headerName: "Elite spec" },
  { field: "fights_attended", headerName: "Fights" },
  { field: "total_damage", headerName: "Total damage" },
  { field: "total_healing", headerName: "Total healing" },
  { field: "total_buff_removal", headerName: "Total strip" },
];

export function PlayersGrid({
  rows,
  filename,
}: {
  rows: PlayerListRow[];
  /**
   * Optional output filename for the "Download CSV" button. When
   * set, a button is rendered next to the grid (hidden when
   * ``rows`` is empty). The CSV column spec is the inline
   * ``CSV_COLUMNS`` constant above so the downloaded file
   * matches the on-screen column order.
   */
  filename?: string;
}) {
  const colDefs = useMemo<ColDef<PlayerListRow>[]>(
    () => [
      {
        field: "account_name",
        headerName: "Account",
        width: 220,
        cellRenderer: (params: ICellRendererParams<PlayerListRow>) => {
          const value = params.value as string;
          if (!value) return "";
          return (
            <a
              href={`/players/${encodeURIComponent(value)}`}
              style={LINK_STYLE}
            >
              {value}
            </a>
          );
        },
      },
      { field: "name", headerName: "Character", width: 200 },
      { field: "profession", headerName: "Profession", width: 140 },
      { field: "elite_spec", headerName: "Elite spec", width: 140 },
      {
        field: "fights_attended",
        headerName: "Fights",
        width: 100,
        type: "numericColumn",
      },
      {
        field: "total_damage",
        headerName: "Total damage",
        width: 160,
        type: "numericColumn",
      },
      {
        field: "total_healing",
        headerName: "Total healing",
        width: 160,
        type: "numericColumn",
        valueFormatter: (params: ValueFormatterParams) => {
          const v = params.value;
          return typeof v === "number" ? String(v) : "";
        },
      },
      {
        field: "total_buff_removal",
        headerName: "Total strip",
        width: 140,
        type: "numericColumn",
      },
    ],
    [],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      resizable: true,
      sortable: true,
      filter: true,
      // ``suppressMenu`` was removed in AG Grid 34.x (the
      // legacy column menu was dropped; the modern header
      // doesn't render a menu button by default). The
      // property used to hide the kebab menu in the legacy
      // header; today it's a no-op (and a console warning)
      // so we omit it. If a future AG Grid release adds a
      // new "show menu" affordance, the right replacement
      // is ``suppressHeaderMenuButton: true``.
    }),
    [],
  );

  if (rows.length === 0) {
    return <div style={EMPTY_STYLE}>No players in the cross-fight roll-up.</div>;
  }

  return (
    <div style={FLEX_COLUMN_STYLE}>
      {filename ? (
        <div style={FLEX_END_STYLE}>
          <CsvDownloadButton rows={rows} columns={CSV_COLUMNS} filename={filename} />
        </div>
      ) : null}
      <div style={GRID_CONTAINER_STYLE}>
        <AgGridReact<PlayerListRow>
          theme={appGridTheme}
          rowData={rows}
          columnDefs={colDefs}
          defaultColDef={defaultColDef}
          pagination
          paginationPageSize={25}
          paginationPageSizeSelector={false}
          animateRows
        />
      </div>
    </div>
  );
}
