import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

/**
 * Tour 6 Wave 7 (Workstream F): combined component-level spec
 * for the 4 Combat-readout tables + PlayerReadoutBase helpers.
 *
 * jsdom + AG Grid challenge
 * =========================
 * AG Grid Community 34 requires a real DOM + canvas + offsetWidth
 * for proper rendering. jsdom has none of these. We mock
 * ``ag-grid-react`` as a pass-through stub that captures the
 * props so we can assert on column-def shape + row-data without
 * actually rendering the grid. This is the canonical
 * precedent: the existing setup.ts mocks ``@/components/TargetRollupsGrid``
 * + ``@/components/SquadRollupsGrid`` similarly to keep page-level
 * tests fast + canvas-free.
 */
vi.mock("ag-grid-react", () => ({
  AgGridReact: (props: Record<string, unknown>) => {
    // Mock as a stable div carrying the props JSON in data-props
    // so component specs can assert on column / row / sort state.
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

/**
 * ``tests/setup.ts`` mocks all 4 ``PlayerReadout*`` Client Components
 * (Damage / Heal / Boons / Defense) as no-op ``() => null`` so the
 * page-level Server Component tests can render the wrapper without
 * booting AG Grid's full runtime in jsdom (no canvas, no offsetWidth).
 * The component-level test in THIS file needs the real implementations:
 * the empty-state panels (rendered when ``rows`` is empty) + the AG
 * Grid wrappers (which the per-test ``vi.mock("ag-grid-react", ...)``
 * stub above captures props from). ``vi.unmock`` is hoisted by
 * vitest's transformer to the same module-init boundary as
 * ``vi.mock``.
 */
vi.unmock("@/components/PlayerReadoutDamage");
vi.unmock("@/components/PlayerReadoutHeal");
vi.unmock("@/components/PlayerReadoutBoons");
vi.unmock("@/components/PlayerReadoutDefense");

import {
  formatSubgroup,
  formatRoles,
  formatCommanderIcon,
} from "@/components/PlayerReadoutBase";
import { PlayerReadoutDamage } from "@/components/PlayerReadoutDamage";
import { PlayerReadoutHeal } from "@/components/PlayerReadoutHeal";
import { PlayerReadoutBoons } from "@/components/PlayerReadoutBoons";
import { PlayerReadoutDefense } from "@/components/PlayerReadoutDefense";
import type { PlayerReadoutOut } from "@/lib/api";

/**
 * Build a fully-populated PlayerReadoutOut row for component
 * tests. Defaults to "all zeros" so the per-field assertions can
 * spot-check the wiring.
 */
function buildRow(extra: Partial<PlayerReadoutOut> = {}): PlayerReadoutOut {
  return {
    agent_id: 10001,
    subgroup: 1,
    name: "Player One",
    account_name: "TestAccount.1234",
    profession: "GUARDIAN",
    elite_spec: "FIREBRAND",
    is_commander: true,
    roles: ["DPS", "STRIP"],
    damage: {
      dps_total: 4500,
      dps_power: 0,
      dps_condi: 0,
      strips: 12,
      cc_applied: 450,
      down_contribution_dps: 1200,
      kills: 3,
      cleave_targets: 0,
    },
    heal: {
      heal_total: 120000,
      hps: 15000,
      barrier_total: 0,
      barrier_ps: 0,
      cleanses: 150,
      stun_breaks: 5,
    },
    boons: {
      boons_out_rate: 45.2,
      boons_in_rate: 20.1,
      stability_out: 450,
      alacrity_out: 0,
      resistance_out: 12,
      aegis_out: 35,
      superspeed_out: 15,
      stealth_out: 0,
      might_uptime: null,
      fury_uptime: null,
      quickness_uptime: null,
      alacrity_uptime: null,
      protection_uptime: null,
      regeneration_uptime: null,
      vigor_uptime: null,
      aegis_uptime: null,
      stability_uptime: null,
      swiftness_uptime: null,
      resistance_uptime: null,
      resolution_uptime: null,
      superspeed_uptime: null,
      stealth_uptime: null,
      other_boons_out: { might: 4503, fury: 34 },
      outgoing_might: null,
      outgoing_fury: null,
      outgoing_quickness: null,
      outgoing_alacrity: null,
      outgoing_protection: null,
      outgoing_regeneration: null,
      outgoing_vigor: null,
      outgoing_aegis: null,
      outgoing_stability: null,
      outgoing_swiftness: null,
      outgoing_resistance: null,
      outgoing_resolution: null,
      outgoing_superspeed: null,
      outgoing_stealth: null,
    },
    defense: {
      damage_taken: 45000,
      cc_taken: 2,
      deaths: 0,
      time_downed_ms: 0,
      dodges: 14,
      blocks: 45,
      interrupts: 1,
      barrier_absorbed: 15015,
      presence_pct: null,
    },
    ...extra,
  };
}

describe("PlayerReadoutBase formatters", () => {
  it("formatSubgroup maps int to 'Sub N' label", () => {
    expect(formatSubgroup(1)).toBe("Sub 1");
    expect(formatSubgroup(2)).toBe("Sub 2");
    expect(formatSubgroup(0)).toBe("(no squad)");
  });

  it("formatSubgroup tolerates null + string shapes (subgroup type drift)", () => {
    expect(formatSubgroup(null)).toBe("(no squad)");
    expect(formatSubgroup(undefined)).toBe("(no squad)");
    expect(formatSubgroup("Sub 1")).toBe("Sub 1");
    expect(formatSubgroup("")).toBe("(no squad)");
  });

  it("formatRoles renders multi-role as slash-delimited chip list", () => {
    expect(formatRoles(["DPS", "STRIP"])).toBe("DPS/STRIP");
    expect(formatRoles(["HEAL"])).toBe("HEAL");
    expect(formatRoles([])).toBe("");
    expect(formatRoles(null)).toBe("");
  });

  it("formatCommanderIcon returns crown for true commander", () => {
    expect(formatCommanderIcon(true)).toBe("★");
    expect(formatCommanderIcon(false)).toBe("");
  });
});

describe("PlayerReadoutDamage", () => {
  it("renders the empty-state panel when rows is empty", () => {
    const { container } = render(<PlayerReadoutDamage rows={[]} />);
    expect(
      container.querySelector('[data-testid="player-readout-damage-empty"]'),
    ).not.toBeNull();
  });

  it("renders AG Grid wrapper with 13 columns + default sort when rows present", () => {
    const rows = [buildRow()];
    const { container } = render(<PlayerReadoutDamage rows={rows} />);
    const mock = container.querySelector(
      '[data-testid="player-readout-damage"] [data-testid="ag-grid-mock"]',
    );
    expect(mock).not.toBeNull();
    const props = JSON.parse(mock!.getAttribute("data-props") ?? "{}");
    // 5 SHARED + 7 damage + 1 agent_id tiebreaker = 13 columns.
    expect(props.columnDefs).toBe(13);
    expect(props.rowData).toBe(1);
    // Default sort per design doc §13.
    expect(props.sortModel).toEqual([
      { colId: "subgroup", sort: "asc" },
      { colId: "damage.dps_total", sort: "desc" },
      { colId: "agent_id", sort: "asc" }
    ]);
  });
});

describe("PlayerReadoutHeal", () => {
  it("renders the empty-state panel when rows is empty", () => {
    const { container } = render(<PlayerReadoutHeal rows={[]} />);
    expect(
      container.querySelector('[data-testid="player-readout-heal-empty"]'),
    ).not.toBeNull();
  });

  it("renders AG Grid wrapper with 12 columns + hps-desc default sort", () => {
    const rows = [buildRow()];
    const { container } = render(<PlayerReadoutHeal rows={rows} />);
    const mock = container.querySelector(
      '[data-testid="player-readout-heal"] [data-testid="ag-grid-mock"]',
    );
    expect(mock).not.toBeNull();
    const props = JSON.parse(mock!.getAttribute("data-props") ?? "{}");
    expect(props.columnDefs).toBe(12);
    expect(props.sortModel).toEqual([
      { colId: "subgroup", sort: "asc" },
      { colId: "heal.hps", sort: "desc" },
      { colId: "agent_id", sort: "asc" }
    ]);
  });
});

describe("PlayerReadoutBoons", () => {
  it("renders the empty-state panel when rows is empty", () => {
    const { container } = render(<PlayerReadoutBoons rows={[]} />);
    expect(
      container.querySelector('[data-testid="player-readout-boons-empty"]'),
    ).not.toBeNull();
  });

  it("renders AG Grid wrapper with 14 columns + boons_out_rate-desc sort", () => {
    const rows = [buildRow()];
    const { container } = render(<PlayerReadoutBoons rows={rows} />);
    const mock = container.querySelector(
      '[data-testid="player-readout-boons"] [data-testid="ag-grid-mock"]',
    );
    expect(mock).not.toBeNull();
    const props = JSON.parse(mock!.getAttribute("data-props") ?? "{}");
    // 5 SHARED + 9 boons (boons_out/in + 6 fixed + other_total) + 1 tiebreaker = 15.
    // Wait: 5 + 8 (2 + 6) + 0 (other_total is a valueGetter NOT a column) = ?
    // Counting precisely: boons_out_rate, boons_in_rate, 6 fixed, other_boons_total = 9 aspect cols.
    // 5 + 9 + 1 = 15.
    expect(props.columnDefs).toBe(15);
    expect(props.sortModel).toEqual([
      { colId: "subgroup", sort: "asc" },
      { colId: "boons.boons_out_rate", sort: "desc" },
      { colId: "agent_id", sort: "asc" }
    ]);
  });
});

describe("PlayerReadoutDefense", () => {
  it("renders the empty-state panel when rows is empty", () => {
    const { container } = render(<PlayerReadoutDefense rows={[]} />);
    expect(
      container.querySelector('[data-testid="player-readout-defense-empty"]'),
    ).not.toBeNull();
  });

  it("renders AG Grid wrapper with 15 columns + damage_taken-desc sort", () => {
    const rows = [buildRow()];
    const { container } = render(<PlayerReadoutDefense rows={rows} />);
    const mock = container.querySelector(
      '[data-testid="player-readout-defense"] [data-testid="ag-grid-mock"]',
    );
    expect(mock).not.toBeNull();
    const props = JSON.parse(mock!.getAttribute("data-props") ?? "{}");
    // 5 SHARED + 9 defense (incl. presence_pct) + 1 tiebreaker = 15.
    expect(props.columnDefs).toBe(15);
    expect(props.sortModel).toEqual([
      { colId: "subgroup", sort: "asc" },
      { colId: "defense.damage_taken", sort: "desc" },
      { colId: "agent_id", sort: "asc" }
    ]);
  });
});
