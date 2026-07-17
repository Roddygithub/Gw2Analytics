"use client";

/**
 * Reusable AG Grid Community wrapper for the per-subgroup (squad)
 * roll-up table on the ``/fights/[id]`` drill-down page.
 *
 * The squad roll-up has a structurally different row shape from
 * the per-target trio (keyed on ``subgroup`` string, not
 * ``target_agent_id`` number) so a dedicated grid component is
 * warranted. The page-level Server Component builds the column
 * spec (``SquadRollupColumn<TRow>[]``) and the grid does the rest.
 *
 * Why a separate component (vs reusing TargetRollupsGrid)
 * ======================================================
 * The row shape differs on the key column (``subgroup: string``
 * vs ``target_agent_id: number``) and on the rate column set
 * (``dps`` / ``hps`` / ``bps`` vs a single ``dps`` / ``hps`` /
 * ``bps``). A single generic component would need a conditional
 * branch on the key column type; two focused components keep the
 * column specs at the call site and avoid the type-narrowing
 * gymnastics.
 *
 * Module registration side-effect
 * ===============================
 * Importing ``./ag-grid-setup`` runs the
 * ``ModuleRegistry.registerModules([AllCommunityModule])`` call
 * exactly once across the whole module graph. The grid's
 * built-in features (sort, filter, pagination) are then
 * available without any explicit per-component wiring.
 */

import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  type ColDef,
  type ValueFormatterParams,
} from "ag-grid-community";
import { appGridTheme } from "./ag-grid-setup";
import { CsvDownloadButton } from "./CsvDownloadButton";
import {
  EMPTY_STYLE,
  FLEX_COLUMN_STYLE,
  FLEX_END_STYLE,
  gridContainerStyle,
} from "@/shared/styles";

const GRID_HEIGHT_PX = 280;

const GRID_CONTAINER_STYLE = gridContainerStyle(GRID_HEIGHT_PX);

export interface SquadRollupColumn<TRow> {
  /** Pydantic field name on the row model (e.g. ``"subgroup"``). */
  field: keyof TRow & string;
  /** Column header text shown in the grid header row. */
  headerName: string;
  /**
   * Optional fixed-decimal formatter for numeric rate columns
   * (``dps`` / ``hps`` / ``bps``). When set, the value is
   * rendered as ``value.toFixed(decimals)``; when unset, the raw
   * value is shown.
   */
  decimals?: number;
  /** Optional explicit column width in pixels. */
  width?: number;
}

export interface SquadRollupsGridProps<TRow> {
  rows: TRow[];
  columns: SquadRollupColumn<TRow>[];
  /**
   * Optional output filename for the "Download CSV" button. When
   * set, a button is rendered next to the grid (hidden when
   * ``rows`` is empty). The CSV column spec reuses the grid's
   * ``columns`` prop so the downloaded file matches the
   * on-screen column order + decimal formatting exactly.
   */
  filename?: string;
}

export function SquadRollupsGrid<TRow extends { subgroup: string }>({
  rows,
  columns,
  filename,
}: SquadRollupsGridProps<TRow>) {
  const colDefs = useMemo<ColDef<TRow>[]>(
    () =>
      columns.map((c) => {
        const def: ColDef<TRow> = {
          field: c.field as never,
          headerName: c.headerName,
          sortable: true,
          filter: true,
          width: c.width,
        };
        if (c.decimals !== undefined) {
          const decimals = c.decimals;
          def.valueFormatter = (params: ValueFormatterParams) => {
            const v = params.value;
            return typeof v === "number" ? v.toFixed(decimals) : String(v);
          };
        }
        return def;
      }),
    [columns],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      resizable: true,
      // ``suppressMenu`` was removed in AG Grid 34.x; see
      // PlayersGrid for the rationale.
    }),
    [],
  );

  if (rows.length === 0) {
    return (
      <div style={EMPTY_STYLE}>
        No squad roll-up rows.
      </div>
    );
  }

  return (
    <div style={FLEX_COLUMN_STYLE}>
      {filename ? (
        <div style={FLEX_END_STYLE}>
          <CsvDownloadButton rows={rows} columns={columns} filename={filename} />
        </div>
      ) : null}
      <div style={GRID_CONTAINER_STYLE}>
        <AgGridReact<TRow>
          theme={appGridTheme}
          rowData={rows}
          columnDefs={colDefs}
          defaultColDef={defaultColDef}
          animateRows
        />
      </div>
    </div>
  );
}
