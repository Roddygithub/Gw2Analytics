"use client";

/**
 * Reusable AG Grid Community wrapper for the per-target damage +
 * healing roll-up tables.
 *
 * The two roll-ups have structurally identical row shapes
 * (target_agent_id + total + rate), so a single generic component
 * covers both kinds. The page-level Server Component builds the
 * column spec (``TargetRollupColumn<TRow>[]``) for the kind it
 * wants to render and the grid does the rest.
 *
 * Why a generic component
 * =======================
 * The codebase has two small focused aggregators
 * (:class:`gw2_analytics.target_dps.TargetDpsAggregator` and
 * :class:`gw2_analytics.target_healing.TargetHealingAggregator`)
 * that share the same shape. A single reusable grid component
 * matches that surface: one Client Component, two column specs.
 * Adding a Phase 8 ``BuffRemovalRollup`` (or similar) only needs a
 * new column spec + a new field on the route response, not a new
 * Client Component.
 *
 * Why AG Grid Community (vs a plain HTML table)
 * ==============================================
 * Analyst-facing roll-up tables want sortable + filterable columns
 * out of the box; a plain ``<table>`` would force every consumer
 * to hand-roll those. AG Grid Community is permissively licensed
 * (no seat fee) and the existing ``/fights`` page already uses it,
 * so we share the dark Quartz theme + module registration
 * (``./ag-grid-setup``) for visual + behavioural consistency.
 *
 * Module registration side-effect
 * ===============================
 * Importing ``./ag-grid-setup`` is a side-effect import: it runs
 * the ``ModuleRegistry.registerModules([AllCommunityModule])``
 * call exactly once across the whole module graph. The grid's
 * built-in features (sort, filter, pagination) are then available
 * without any explicit per-component wiring.
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
import { CsvDownloadButton } from "./CsvDownloadButton";

const GRID_THEME = "ag-theme-quartz-dark";
const GRID_HEIGHT_PX = 320;

export interface TargetRollupColumn<TRow> {
  /** Pydantic field name on the row model (e.g. ``"target_agent_id"``). */
  field: keyof TRow & string;
  /** Column header text shown in the grid header row. */
  headerName: string;
  /**
   * Optional fixed-decimal formatter for numeric columns (the
   * ``dps`` / ``hps`` rate column). When set, the value is rendered
   * as ``value.toFixed(decimals)``; when unset, the raw value is
   * shown (suitable for the integer id / total columns).
   */
  decimals?: number;
  /** Optional explicit column width in pixels. */
  width?: number;
}

export interface TargetRollupsGridProps<TRow> {
  rows: TRow[];
  columns: TargetRollupColumn<TRow>[];
  /**
   * Human-friendly grid caption rendered above the table. Helps
   * distinguish the two parallel grids on the page (e.g. "Per-target
   * damage" vs "Per-target healing"). When empty, no caption is
   * rendered -- the page-level ``<h2>`` carries the label.
   */
  caption?: string;
  /**
   * Optional output filename for the "Download CSV" button. When
   * set, a button is rendered next to the grid (hidden when
   * ``rows`` is empty). The CSV column spec reuses the grid's
   * ``columns`` prop, so the downloaded file matches the
   * on-screen column order + decimal formatting exactly.
   */
  filename?: string;
}

export function TargetRollupsGrid<TRow extends { target_agent_id: number }>({
  rows,
  columns,
  caption,
  filename,
}: TargetRollupsGridProps<TRow>) {
  const colDefs = useMemo<ColDef<TRow>[]>(
    () =>
      columns.map((c) => {
        // Build the column definition imperatively so the
        // ``ColDef<TRow>`` type is asserted on every property
        // assignment (TypeScript otherwise widens the inferred
        // array element type, which collides with AG Grid's
        // ``ValueFormatterParams<TRow, any>`` generic at the
        // colDefs array type slot). The ``decimals`` const-rebind
        // inside the closure captures the value once so the
        // formatter does not need a non-null assertion.
        // The `field: c.field as never` assertion bypasses the
        // `keyof TRow & string` -> `ColDefField<TRow, any> | undefined`
        // variance mismatch. At runtime ``c.field`` is a plain string
        // key of ``TRow`` (the constraint is enforced at the column
        // spec construction site); AG Grid's own runtime checks then
        // resolve the column value via the row object. The assertion
        // is a TYPE-only escape hatch with no runtime effect.
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
        {caption ? `${caption}: ` : ""}no rows.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }}>
      {filename ? (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <CsvDownloadButton rows={rows} columns={columns} filename={filename} />
        </div>
      ) : null}
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
    </div>
  );
}
