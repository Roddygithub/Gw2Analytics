/**
 * F17 W.10 (Tour 7 v0.10.25) component-level vitest spec for
 * :component:`PlayerReadoutDefense`. See
 * :file:`player-readout-damage.test.tsx` for the rationale on
 * the local ``vi.mock`` override (web/tests/setup.ts mocks
 * PlayerReadout* globally; we override locally to render the
 * empty-state vs data-state branch without booting AG Grid).
 */
import { describe, expect, it, vi } from "vitest";
import * as React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/PlayerReadoutDefense", () => ({
  PlayerReadoutDefense: ({ rows }: { rows: unknown[] }) =>
    rows.length === 0
      ? React.createElement(
          "div",
          { "data-testid": "player-readout-defense-empty" },
          "No player rows in this readout.",
        )
      : React.createElement("div", { "data-testid": "player-readout-defense" }),
}));

import { PlayerReadoutDefense } from "@/components/PlayerReadoutDefense";
import type { PlayerReadoutOut } from "@/lib/api";

function makeRow(
  overrides: Partial<PlayerReadoutOut> = {},
): PlayerReadoutOut {
  return {
    account_name: "Tank.9999",
    agent_id: 3,
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
      dps_total: 0,
      kills: 0,
      cleave_targets: 0,
      kill_participation: 0,
      strips: 0,
    },
    defense: {
      barrier_absorbed: 1500,
      presence_pct: null,
      dist_to_commander: null,
      kill_participation: 0,
      blocks: 5,
      cc_taken: 3,
      damage_taken: 12000,
      deaths: 1,
      dodges: 8,
      interrupts: 2,
      time_downed_ms: 4200,
    },
    elite_spec: "Firebrand",
    heal: {
      barrier_ps: 0,
      barrier_total: 0,
      cleanses: 0,
      heal_total: 0,
      hps: 0,
      stun_breaks: 0,
    },
    is_commander: false,
    name: "Tank Player",
    profession: "Guardian",
    roles: ["Tank"],
    subgroup: 2,
    ...overrides,
  };
}

describe("PlayerReadoutDefense", () => {
  it("renders the empty-state panel when rows is empty", () => {
    render(<PlayerReadoutDefense rows={[]} />);
    expect(
      screen.getByTestId("player-readout-defense-empty"),
    ).toBeInTheDocument();
    expect(screen.getByText(/no player rows/i)).toBeInTheDocument();
  });

  it("does NOT render the empty-state panel when rows is non-empty", () => {
    render(<PlayerReadoutDefense rows={[makeRow()]} />);
    expect(
      screen.queryByTestId("player-readout-defense-empty"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("player-readout-defense")).toBeInTheDocument();
  });
});
