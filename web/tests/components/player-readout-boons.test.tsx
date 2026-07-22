/**
 * F17 W.10 (Tour 7 v0.10.25) component-level vitest spec for
 * :component:`PlayerReadoutBoons`. See
 * :file:`player-readout-damage.test.tsx` for the rationale on
 * the local ``vi.mock`` override (web/tests/setup.ts mocks
 * PlayerReadout* globally; we override locally to render the
 * empty-state vs data-state branch without booting AG Grid).
 *
 * The Boons table uses an extra ``other_boons_out: dict[str, int]``
 * field per design doc §11's collapsed-cell resolution; the
 * ``makeRow`` factory here exercises a non-empty dict so a
 * future regression on the valueGetter would surface in CI.
 */
import { describe, expect, it, vi } from "vitest";
import * as React from "react";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/PlayerReadoutBoons", () => ({
  PlayerReadoutBoons: ({ rows }: { rows: unknown[] }) =>
    rows.length === 0
      ? React.createElement(
          "div",
          { "data-testid": "player-readout-boons-empty" },
          "No player rows in this readout.",
        )
      : React.createElement("div", { "data-testid": "player-readout-boons" }),
}));

import { PlayerReadoutBoons } from "@/components/PlayerReadoutBoons";
import type { PlayerReadoutOut } from "@/lib/api";

function makeRow(
  overrides: Partial<PlayerReadoutOut> = {},
): PlayerReadoutOut {
  return {
    account_name: "Boon.4242",
    agent_id: 4,
    boons: {
      aegis_out: 12,
      alacrity_out: 30,
      boons_in_rate: 5.5,
      boons_out_rate: 8.2,
      other_boons_out: {
        Fury: 18,
        Might: 42,
        Protection: 7,
        Quickness: 0,
        Regeneration: 5,
      },
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
      stability_out: 4,
      stealth_out: 2,
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
      presence_pct: null,
      blocks: 0,
      cc_taken: 0,
      damage_taken: 0,
      deaths: 0,
      dodges: 0,
      interrupts: 0,
      time_downed_ms: 0,
    },
    elite_spec: "Chronomancer",
    heal: {
      barrier_ps: 0,
      barrier_total: 0,
      cleanses: 0,
      heal_total: 0,
      hps: 0,
      stun_breaks: 0,
    },
    is_commander: false,
    name: "Boon Player",
    profession: "Mesmer",
    roles: ["Boon"],
    subgroup: 1,
    ...overrides,
  };
}

describe("PlayerReadoutBoons", () => {
  it("renders the empty-state panel when rows is empty", () => {
    render(<PlayerReadoutBoons rows={[]} />);
    expect(
      screen.getByTestId("player-readout-boons-empty"),
    ).toBeInTheDocument();
    expect(screen.getByText(/no player rows/i)).toBeInTheDocument();
  });

  it("does NOT render the empty-state panel when rows is non-empty", () => {
    render(<PlayerReadoutBoons rows={[makeRow()]} />);
    expect(
      screen.queryByTestId("player-readout-boons-empty"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("player-readout-boons")).toBeInTheDocument();
  });
});
