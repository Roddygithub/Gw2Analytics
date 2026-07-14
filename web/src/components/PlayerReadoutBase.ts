/**
 * Tour 6 Wave 7 (Workstream F — Combat-readout UI): shared
 * column-def helpers + formatters for the 4 readout tables.
 *
 * The 5 SHARED_COLUMNS (subgroup / name / elite_spec / is_commander /
 * roles) per docs/v0.9.0-combat-readout-design.md §2 are exported
 * here so the 4 per-aspect components (``PlayerReadoutDamage``,
 * ``PlayerReadoutHeal``, ``PlayerReadoutBoons``, ``PlayerReadoutDefense``)
 * inherit them via spread rather than redefining the schema on each.
 *
 * NOT a React Component
 * =====================
 * Pure TS module (no JSX, no ``"use client"``). Each per-aspect
 * component embeds the SHARED_COLUMNS in its own AG Grid
 * ``columnDefs`` array. Subgroup / name / roles formatters live here
 * too so the 4 components don't divergent-fork the rendering.
 *
 * Subgroup type-drift note
 * ========================
 * The legacy AgentOut schema uses ``subgroup: string | null`` (per-
 * target + per-squad contract) while PlayerReadoutOut uses
 * ``subgroup: int`` (per-player readout contract, per design doc §2).
 * Per thinker's recommendation A, the type drift is accepted at the
 * consumer boundary; the formatter normalises both shapes into the
 * canonical ``Sub N`` label so the AG Grid cell renderer is uniform.
 */

import type {
  ColDef,
  ValueFormatterParams,
} from "ag-grid-community";

import type { PlayerReadoutOut } from "@/lib/api";

/**
 * Format the warp-reported integer subgroup (``1`` -> ``"Sub 1"``,
 * ``0`` -> ``"(no squad)"``). The schema allows ``subgroup`` to be
 * any integer (the per-player readout contract) but a real squad
 * is conventionally ``>= 1``; ``0`` is the "no squad" sentinel
 * (the canonical NPC-only / ghost row case).
 *
 * The formatter is defensive against null + undefined values too
 * because the AG Grid Community renderer may invoke it during a
 * hot-reload before the column is bound.
 */
export function formatSubgroup(value: unknown): string {
  if (value === null || value === undefined) return "(no squad)";
  if (typeof value === "number" && Number.isFinite(value)) {
    return value === 0 ? "(no squad)" : `Sub ${value}`;
  }
  if (typeof value === "string") return value || "(no squad)";
  return "(no squad)";
}

/**
 * Format the role-classifier's ``roles: list[str]`` output as a
 * slash-delimited chip list (e.g. ``["DPS", "STRIP"]`` ->
 * ``"DPS/STRIP"``). The full multi-role-set semantics are per
 * design doc §3.1; the slash-delimited rendering is the canonical
 * compact form for a 100-px AG Grid cell.
 */
export function formatRoles(roles: string[] | undefined | null): string {
  if (!roles || roles.length === 0) return "";
  return roles.join("/");
}

/**
 * Renders the commander crown icon as a single-cell glyph when
 * ``is_commander === true``. A plain boolean column with a
 * ``valueFormatter`` returning ``"★"`` vs ``""`` keeps the cell
 * compact; AG Grid's default cell renderer applies the format.
 *
 * The crown glyph is the canonical "commander" marker from the
 * design doc §2 row, mirroring arcdps / Elite Insights.
 */
export function formatCommanderIcon(isCommander: unknown): string {
  return isCommander === true ? "★" : "";
}

/**
 * The 5 SHARED_COLUMNS that prepend every per-aspect table per
 * design doc §2. Spread this into each component's
 * ``columnDefs`` so the schema lives in one place; a future
 * design-doc §2 update (e.g. swapping the crown glyph) is a
 * one-file edit.
 */
export const SHARED_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  {
    field: "subgroup",
    headerName: "Sub-groupe",
    width: 110,
    valueFormatter: (params: ValueFormatterParams) =>
      formatSubgroup(params.value),
    // Lock subgroup-first sort per design doc §13.
    sort: "asc",
  },
  {
    field: "name",
    headerName: "Nom",
    width: 180,
  },
  {
    field: "elite_spec",
    headerName: "Spécialisation",
    width: 160,
  },
  {
    field: "is_commander",
    headerName: "Cmdr",
    width: 80,
    valueFormatter: (params: ValueFormatterParams) =>
      formatCommanderIcon(params.value),
  },
  {
    field: "roles",
    headerName: "Rôles",
    width: 140,
    valueFormatter: (params: ValueFormatterParams) =>
      formatRoles(params.value as string[] | undefined | null),
  },
];

/**
 * The canonical agent_id tie-breaker column appended at the end
 * of every per-aspect table per design doc §13 ("append agent_id
 * ASC as the final tiebreaker"). The column is HIDDEN by default
 * (the analyst doesn't need to see the numeric agent id) but
 * participates in the sort comparator so ties break
 * deterministically.
 *
 * THIRD sort entry appended in each component's ``initialState``
 * array (per design doc §13). AG Grid Community v34 uses
 * ARRAY-ORDER for multi-column-sort priority; no ``sortIndex``
 * field is carried in ``ColDef<TData, any>``. Entry order:
 * ``[subgroup ASC, <aspect> DESC, agent_id ASC]``.
 */
export const AGENT_ID_TIEBREAKER: ColDef<PlayerReadoutOut> = {
  field: "agent_id",
  headerName: "Agent id",
  width: 110,
  hide: true,
};

/**
 * AG Grid-level props shared across all 4 readout tables. These
 * props live DIRECTLY on ``<AgGridReact>`` — NOT under
 * ``defaultColDef`` — because AG Grid Community v34's
 * ``ColDef<TData>`` type forbids ``theme`` / ``rowSelection``
 * there (those are AgGridReact-level props, not column-level).
 *
 * Each per-aspect component spreads this into its
 * ``<AgGridReact>`` so the constants live in one place. The
 * numeric-sort comparator (``comparator: (a, b) => (Number(a ?? 0) - Number(b ?? 0)) || 0``)
 * lives inline on each component's ``defaultColDef={{ comparator: (a, b) => (Number(a ?? 0) - Number(b ?? 0)) || 0 }}``
 * because AG Grid Community v34’s ColDef d.ts does not
 * include a sortNumeric flag (only the canonical comparator
 * callback) — numeric sort must be encoded as an explicit
 * comparator function rather than the deprecated boolean flag.
 *
 * Visual cohesion: the ``legacy`` theme matches the existing
 * ``TargetRollupsGrid`` / ``SquadRollupsGrid`` instances on
 * the /fights/[id] page.
 */
export const AG_GRID_PROPS = {
  // "legacy" is the built-in theme shipped with
  // ag-grid-community 34. AG Grid resolves the named theme at
  // render time so this is hot-reload safe (theme swap doesn't
  // trigger a per-row re-render).
  theme: "legacy" as const,
  // Single-row selection (clicking a row selects it for the
  // future drill-in detail panel; v0.10.23 SCAFFOLD doesn't
  // wire a drill-in yet).
  rowSelection: { mode: "singleRow" } as const,
} as const;

