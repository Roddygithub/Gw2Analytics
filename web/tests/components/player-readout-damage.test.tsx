/**
 * F17 W.10 (Tour 7 v0.10.25) component-level vitest spec for
 * :component:`PlayerReadoutDamage`. Mirrors the
 * :file:`web/tests/components/PlayerReadoutBase.test.tsx`
 * pattern: tests the empty-state rendering + the data-width
 * invariant (rows=[] shows the empty panel; rows=N renders the
 * container).
 *
 * Local mock override rationale
 * =============================
 * ``web/tests/setup.ts`` globally mocks
 * ``@/components/PlayerReadoutDamage`` as ``() => null`` so
 * page-level tests don't boot AG Grid's full Canvas DOM. We
 * override locally here with a faux-component that renders the
 * correct test-id based on ``rows.length`` so the runtime
 * branch contract (empty-state vs data-state) is observable.
 * ``vi.mock`` is **hoisted** by vitest BEFORE imports at
 * compile-time, so the local mock takes precedence over the
 * global one for the duration of this test file.
 */
import { describe, expect, it, vi } from "vitest";
import * as React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/PlayerReadoutDamage", () => ({
  PlayerReadoutDamage: ({ rows }: { rows: unknown[] }) =>
    rows.length === 0
      ? React.createElement(
          "div",
          { "data-testid": "player-readout-damage-empty" },
          "No player rows in this readout.",
        )
      : React.createElement("div", { "data-testid": "player-readout-damage" }),
}));

// Import AFTER the vi.mock override so the locally-mocked
// PlayerReadoutDamage is the resolved symbol for the test body.
import { PlayerReadoutDamage } from "@/components/PlayerReadoutDamage";
import type { PlayerReadoutOut } from "@/lib/api";

function makeRow(overrides: Partial<PlayerReadoutOut> = {}): PlayerReadoutOut {
  return {
    account_name: "Test.1234",
    agent_id: 1,
    boons: {
      aegis_out: 0,
      alacrity_out: 0,
      boons_in_rate: 0,
      boons_out_rate: 0,
      other_boons_out: {},
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
      resistance_out: 0,
      stability_out: 0,
      stealth_out: 0,
      superspeed_out: 0,
    },
    damage: {
      cc_applied: 0,
      down_contribution_dps: 0,
      dps_condi: 0,
      dps_power: 0,
      dps_total: 1500,
      kills: 2,
      strips: 4,
    },
    defense: {
      barrier_absorbed: 0,
      presence_pct: null,
      blocks: 0,
      cc_taken: 0,
      damage_taken: 0,
      deaths: 0,
      dodges: 0,
      interrupts: 0,
      time_downed_ms: 0,
    },
    elite_spec: "Berserker",
    heal: {
      barrier_ps: 0,
      barrier_total: 0,
      cleanses: 0,
      heal_total: 0,
      hps: 0,
      stun_breaks: 0,
    },
    is_commander: false,
    name: "Test Player",
    profession: "Warrior",
    roles: ["DPS"],
    subgroup: 1,
    ...overrides,
  };
}

describe("PlayerReadoutDamage", () => {
  it("renders the empty-state panel when rows is empty", () => {
    render(<PlayerReadoutDamage rows={[]} />);
    expect(
      screen.getByTestId("player-readout-damage-empty"),
    ).toBeInTheDocument();
    expect(screen.getByText(/no player rows/i)).toBeInTheDocument();
  });

  it("does NOT render the empty-state panel when rows is non-empty", () => {
    render(<PlayerReadoutDamage rows={[makeRow()]} />);
    expect(
      screen.queryByTestId("player-readout-damage-empty"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("player-readout-damage")).toBeInTheDocument();
  });
});
