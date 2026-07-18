"use client";

/**
 * Shared grid wrapper for the 4 per-aspect readout tables.
 *
 * Owns the empty-state panel and the ``AgGridReact`` boilerplate
 * so each aspect component only supplies its domain-specific
 * columns + default sort.
 */
import React from "react";

import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, SortModelItem } from "ag-grid-community";

import type { PlayerReadoutOut } from "@/lib/api";

import {
  AGENT_ID_TIEBREAKER,
  AG_GRID_PROPS,
  SHARED_COLUMNS,
} from "./PlayerReadoutBase";

const EMPTY_STATE_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const NUMERIC_COMPARATOR = (a: unknown, b: unknown) =>
  Number(a ?? 0) - Number(b ?? 0) || 0;

const DEFAULT_COL_DEF = { comparator: NUMERIC_COMPARATOR };

export interface PlayerReadoutGridProps {
  testId: string;
  rows: PlayerReadoutOut[];
  aspectColumns: ColDef<PlayerReadoutOut>[];
  defaultSort: SortModelItem[];
}

/**
 * Shared grid wrapper for the 4 per-aspect readout tables.
 *
 * Owns the empty-state panel and the ``AgGridReact`` boilerplate
 * so each aspect component only declares its columns + sort.
 */
export function PlayerReadoutGrid({
  testId,
  rows,
  aspectColumns,
  defaultSort,
}: PlayerReadoutGridProps) {
  // Keep the hook before the early return so the call order stays
  // unconditional. ``aspectColumns`` is stable for each aspect
  // component (module-level const), so the memo is cheap.
  const columnDefs = useMemo(
    () => [...SHARED_COLUMNS, ...aspectColumns, AGENT_ID_TIEBREAKER],
    [aspectColumns],
  );

  if (rows.length === 0) {
    return (
      <div data-testid={`${testId}-empty`} style={EMPTY_STATE_STYLE}>
        No player rows in this readout.
      </div>
    );
  }

  return (
    <div data-testid={testId} style={{ width: "100%" }}>
      <AgGridReact<PlayerReadoutOut>
        rowData={rows}
        columnDefs={columnDefs}
        defaultColDef={DEFAULT_COL_DEF}
        {...AG_GRID_PROPS}
        initialState={{ sort: { sortModel: defaultSort } }}
        getRowId={(params) => String(params.data.agent_id)}
      />
    </div>
  );
}
