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
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

import "./ag-grid-setup";

const GRID_THEME = "ag-theme-quartz-dark";
const GRID_HEIGHT_PX = 280;

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
}

export function SquadRollupsGrid<TRow extends { subgroup: string }>({
  rows,
  columns,
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
      suppressMenu: true,
    }),
    [],
  );

  if (rows.length === 0) {
    return (
      <div
        style={{
          padding: "12px 16px",
          border: "1px solid var(--border)",
          borderRadius: 4,
          color: "var(--foreground)",
          opacity: 0.7,
          fontSize: 14,
        }}
      >
        No squad roll-up rows.
      </div>
    );
  }

  return (
    <div
      className={GRID_THEME}
      style={{ height: GRID_HEIGHT_PX, width: "100%" }}
    >
      <AgGridReact<TRow>
        rowData={rows}
        columnDefs={colDefs}
        defaultColDef={defaultColDef}
        animateRows
      />
    </div>
  );
}
