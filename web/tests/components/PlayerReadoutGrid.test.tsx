import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

import type { PlayerReadoutOut } from "@/lib/api";

/**
 * jsdom + AG Grid challenge
 * =========================
 * AG Grid Community 34 requires a real DOM + canvas + offsetWidth
 * for proper rendering. jsdom has none of these. We mock
 * ``ag-grid-react`` as a pass-through stub that captures the
 * props so we can assert on column-def shape + row-data without
 * actually rendering the grid.
 */
vi.mock("ag-grid-react", () => ({
  AgGridReact: (props: Record<string, unknown>) => {
    return (
      <div
        data-testid="ag-grid-mock"
        data-props={JSON.stringify({
          columnDefs: (props.columnDefs as unknown[]).length,
          rowData: (props.rowData as unknown[]).length,
          sortModel: (props.initialState as { sort: { sortModel: unknown[] } } | undefined)
            ?.sort?.sortModel ?? [],
          rowIdField: "agent_id",
        })}
      />
    );
  },
}));

import { PlayerReadoutGrid } from "@/components/PlayerReadoutGrid";
import type { ColDef, SortModelItem } from "ag-grid-community";

function buildRow(extra: Partial<PlayerReadoutOut> = {}): PlayerReadoutOut {
  return {
    agent_id: 10001,
    subgroup: 1,
    name: "Player One",
    account_name: "TestAccount.1234",
    profession: "GUARDIAN",
    elite_spec: "FIREBRAND",
    is_commander: true,
    roles: ["DPS"],
    damage: {
      dps_total: 4500,
      dps_power: 0,
      dps_condi: 0,
      strips: 0,
      cc_applied: 0,
      down_contribution_dps: 0,
      kills: 0,
    },
    heal: {
      heal_total: 0,
      hps: 0,
      barrier_total: 0,
      barrier_ps: 0,
      cleanses: 0,
      stun_breaks: 0,
    },
    boons: {
      boons_out_rate: 0,
      boons_in_rate: 0,
      stability_out: 0,
      alacrity_out: 0,
      resistance_out: 0,
      aegis_out: 0,
      superspeed_out: 0,
      stealth_out: 0,
      other_boons_out: {},
    },
    defense: {
      damage_taken: 0,
      cc_taken: 0,
      deaths: 0,
      time_downed_ms: 0,
      dodges: 0,
      blocks: 0,
      interrupts: 0,
      barrier_absorbed: 0,
    },
    ...extra,
  };
}

const ASPECT_COLUMNS: ColDef<PlayerReadoutOut>[] = [
  { field: "damage.dps_total", headerName: "DPS total" },
];

const DEFAULT_SORT: SortModelItem[] = [
  { colId: "subgroup", sort: "asc" },
  { colId: "damage.dps_total", sort: "desc" },
  { colId: "agent_id", sort: "asc" },
];

describe("PlayerReadoutGrid", () => {
  it("renders the empty-state panel when rows is empty", () => {
    const { container } = render(
      <PlayerReadoutGrid
        testId="player-readout-test"
        rows={[]}
        aspectColumns={ASPECT_COLUMNS}
        defaultSort={DEFAULT_SORT}
      />,
    );
    expect(
      container.querySelector('[data-testid="player-readout-test-empty"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("No player rows in this readout.");
  });

  it("renders AG Grid wrapper with shared + aspect + tie-breaker columns", () => {
    const rows = [buildRow()];
    const { container } = render(
      <PlayerReadoutGrid
        testId="player-readout-test"
        rows={rows}
        aspectColumns={ASPECT_COLUMNS}
        defaultSort={DEFAULT_SORT}
      />,
    );
    const mock = container.querySelector(
      '[data-testid="player-readout-test"] [data-testid="ag-grid-mock"]',
    );
    expect(mock).not.toBeNull();
    const props = JSON.parse(mock!.getAttribute("data-props") ?? "{}");
    // 5 SHARED + 1 aspect + 1 agent_id tiebreaker = 7 columns.
    expect(props.columnDefs).toBe(7);
    expect(props.rowData).toBe(1);
    expect(props.sortModel).toEqual(DEFAULT_SORT);
  });

  it("passes the test id through to the wrapper div", () => {
    const rows = [buildRow()];
    const { container } = render(
      <PlayerReadoutGrid
        testId="custom-readout"
        rows={rows}
        aspectColumns={ASPECT_COLUMNS}
        defaultSort={DEFAULT_SORT}
      />,
    );
    expect(
      container.querySelector('[data-testid="custom-readout"]'),
    ).not.toBeNull();
  });
});
