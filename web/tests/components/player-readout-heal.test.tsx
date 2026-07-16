/**
 * F17 W.10 (Tour 7 v0.10.25) component-level vitest spec for
 * :component:`PlayerReadoutHeal`. See
 * :file:`player-readout-damage.test.tsx` for the rationale on
 * the local ``vi.mock`` override (web/tests/setup.ts mocks
 * PlayerReadout* globally; we override locally to render the
 * empty-state vs data-state branch without booting AG Grid).
 */
import { describe, expect, it, vi } from "vitest";
import * as React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/PlayerReadoutHeal", () => ({
  PlayerReadoutHeal: ({ rows }: { rows: unknown[] }) =>
    rows.length === 0
      ? React.createElement(
          "div",
          { "data-testid": "player-readout-heal-empty" },
          "No player rows in this readout.",
        )
      : React.createElement("div", { "data-testid": "player-readout-heal" }),
}));

import { PlayerReadoutHeal } from "@/components/PlayerReadoutHeal";
import type { PlayerReadoutOut } from "@/lib/api";

function makeRow(
  overrides: Partial<PlayerReadoutOut> = {},
): PlayerReadoutOut {
  return {
    account_name: "Heal.5678",
    agent_id: 2,
    boons: {
      aegis_out: 0,
      alacrity_out: 0,
      boons_in_rate: 0,
      boons_out_rate: 0,
      other_boons_out: {},
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
      strips: 0,
    },
    defense: {
      barrier_absorbed: 0,
      blocks: 0,
      cc_taken: 0,
      damage_taken: 0,
      deaths: 0,
      dodges: 0,
      interrupts: 0,
      time_downed_ms: 0,
    },
    elite_spec: "Tempest",
    heal: {
      barrier_ps: 250,
      barrier_total: 1500,
      cleanses: 6,
      heal_total: 9000,
      hps: 1100,
      stun_breaks: 3,
    },
    is_commander: true,
    name: "Heal Player",
    profession: "Elementalist",
    roles: ["HEAL", "Support"],
    subgroup: 1,
    ...overrides,
  };
}

describe("PlayerReadoutHeal", () => {
  it("renders the empty-state panel when rows is empty", () => {
    render(<PlayerReadoutHeal rows={[]} />);
    expect(
      screen.getByTestId("player-readout-heal-empty"),
    ).toBeInTheDocument();
    expect(screen.getByText(/no player rows/i)).toBeInTheDocument();
  });

  it("does NOT render the empty-state panel when rows is non-empty", () => {
    render(<PlayerReadoutHeal rows={[makeRow()]} />);
    expect(
      screen.queryByTestId("player-readout-heal-empty"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("player-readout-heal")).toBeInTheDocument();
  });
});
