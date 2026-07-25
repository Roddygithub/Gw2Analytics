import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import { CompareReadoutTable } from "@/components/CompareReadoutTable";
import { buildPlayerReadoutRow } from "../fixtures/playerReadoutRow";

/**
 * Build a ``PlayerReadoutOut`` row with nonzero default values
 * suitable for data-rendering assertions.  The structural base
 * (zero defaults) comes from the shared fixture; the test-local
 * defaults here set the values that individual tests check
 * (e.g. ``presence_pct: 95`` → ``getByText("95%")``).
 */
function buildRow(
  overrides: Parameters<typeof buildPlayerReadoutRow>[0] = {},
) {
  return buildPlayerReadoutRow({
    name: "Test Player",
    elite_spec: "ELITE(27)",
    damage: {
      dps_total: 15000,
      dps_power: 10000,
      dps_condi: 5000,
      strips: 3,
      cc_applied: 5,
      down_contribution_dps: 200,
      kills: 2,
      cleave_targets: 8,
      kill_participation: 10,
    },
    heal: {
      heal_total: 50000,
      hps: 5000,
      barrier_total: 2000,
      barrier_ps: 200,
      cleanses: 15,
      stun_breaks: 3,
    },
    boons: {
      boons_out_rate: 30,
      boons_in_rate: 20,
      stability_out: 100,
      alacrity_out: 50,
      resistance_out: 25,
      aegis_out: 40,
      superspeed_out: 10,
      stealth_out: 5,
      might_uptime: 85,
      fury_uptime: 70,
      quickness_uptime: 60,
      alacrity_uptime: 55,
      protection_uptime: 40,
      regeneration_uptime: 30,
      vigor_uptime: 50,
      aegis_uptime: 35,
      stability_uptime: 45,
      swiftness_uptime: 65,
      resistance_uptime: 20,
      resolution_uptime: 25,
      superspeed_uptime: 10,
      stealth_uptime: 5,
      other_boons_out: {},
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
      damage_taken: 30000,
      cc_taken: 2,
      deaths: 1,
      time_downed_ms: 5000,
      dodges: 20,
      blocks: 10,
      interrupts: 3,
      barrier_absorbed: 8000,
      presence_pct: 95,
      dist_to_commander: 200,
      kill_participation: 10,
    },
    ...overrides,
  });
}

describe("CompareReadoutTable", () => {
  describe("empty state", () => {
    it.each(["damage", "heal", "boons", "defense"] as const)(
      "shows empty message for %s table when no players",
      (kind) => {
        render(<CompareReadoutTable kind={kind} players={[]} />);
        expect(screen.getByText("Aucun joueur dans ce tableau.")).toBeInTheDocument();
      },
    );
  });

  describe("damage table", () => {
    it("renders player data with DPS bars", () => {
      const players = [buildRow({ name: "Player One", damage: { ...buildRow().damage, dps_total: 20000 } })];
      const { container } = render(<CompareReadoutTable kind="damage" players={players} />);

      expect(container.querySelector("table")).toBeInTheDocument();
      expect(screen.getByText("Dégâts")).toBeInTheDocument();
      expect(screen.getByText("Player One")).toBeInTheDocument();
      expect(screen.getByText("20000")).toBeInTheDocument();
    });

    it("renders multiple players", () => {
      const players = [
        buildRow({ agent_id: 1, name: "Top DPS", damage: { ...buildRow().damage, dps_total: 30000 } }),
        buildRow({ agent_id: 2, name: "Mid DPS", damage: { ...buildRow().damage, dps_total: 15000 } }),
      ];
      render(<CompareReadoutTable kind="damage" players={players} />);
      expect(screen.getByText("Top DPS")).toBeInTheDocument();
      expect(screen.getByText("Mid DPS")).toBeInTheDocument();
    });
  });

  describe("heal table", () => {
    it("renders player data with Heal bars", () => {
      const players = [buildRow({ heal: { ...buildRow().heal, hps: 8000 } })];
      render(<CompareReadoutTable kind="heal" players={players} />);

      expect(screen.getByText("Soins")).toBeInTheDocument();
      expect(screen.getByText("Test Player")).toBeInTheDocument();
    });
  });

  describe("boons table", () => {
    it("renders boon uptime percentages and outgoing values", () => {
      // Set outgoing values so they render (default is null → "—")
      const players = [buildRow({
        boons: {
          ...buildRow().boons,
          outgoing_might: 450,
          outgoing_stability: 100,
        },
      })];
      render(<CompareReadoutTable kind="boons" players={players} />);

      expect(screen.getByText("Boons")).toBeInTheDocument();
      // Should show might uptime
      expect(screen.getByText("85%")).toBeInTheDocument();
      // Should show outgoing might
      expect(screen.getByText("450")).toBeInTheDocument();
      // Should show outgoing stability
      expect(screen.getByText("100")).toBeInTheDocument();
    });

    it("renders boon icon images in the table header", () => {
      const players = [buildRow()];
      const { container } = render(<CompareReadoutTable kind="boons" players={players} />);

      // Check for boon icon images (14 boons = 14 images)
      const imgs = container.querySelectorAll('img[src^="/icons/boons/"]');
      expect(imgs.length).toBeGreaterThanOrEqual(14);
      // Verify a specific icon
      const mightIcon = container.querySelector('img[alt="Might"]');
      expect(mightIcon).toBeInTheDocument();
      const furyIcon = container.querySelector('img[alt="Fury"]');
      expect(furyIcon).toBeInTheDocument();
    });
  });

  describe("defense table", () => {
    it("renders defense stats with presence percentage", () => {
      const players = [buildRow()];
      render(<CompareReadoutTable kind="defense" players={players} />);

      expect(screen.getByText("Défense & Positionnement")).toBeInTheDocument();
      // ``toLocaleString()`` adds thousands separator, so 30000 becomes "30,000"
      expect(screen.getByText("30,000")).toBeInTheDocument();
      expect(screen.getByText("95%")).toBeInTheDocument();
    });
  });

  describe("sorting", () => {
    it("sorts damage table by dps_total descending by default", () => {
      const players = [
        buildRow({ agent_id: 1, name: "Low", damage: { ...buildRow().damage, dps_total: 5000 } }),
        buildRow({ agent_id: 2, name: "High", damage: { ...buildRow().damage, dps_total: 30000 } }),
        buildRow({ agent_id: 3, name: "Mid", damage: { ...buildRow().damage, dps_total: 15000 } }),
      ];
      render(<CompareReadoutTable kind="damage" players={players} />);

      // Get all rows - first data cell after header should be "High" (top DPS)
      const cells = screen.getAllByText(/High|Mid|Low/);
      expect(cells[0]).toHaveTextContent("High");
      expect(cells[1]).toHaveTextContent("Mid");
      expect(cells[2]).toHaveTextContent("Low");
    });
  });

  describe("identity cells", () => {
    it("renders subgroup, name, roles for each player", () => {
      const players = [
        buildRow({ subgroup: 3, name: "Squad Leader", roles: ["DPS", "CC"] }),
      ];
      render(<CompareReadoutTable kind="damage" players={players} />);

      expect(screen.getByText("Sub 3")).toBeInTheDocument();
      expect(screen.getByText("Squad Leader")).toBeInTheDocument();
    });
  });

  describe("table headers", () => {
    it.each(["damage", "heal", "defense"] as const)(
      "renders column headers for %s table",
      (kind) => {
        const players = [buildRow()];
        render(<CompareReadoutTable kind={kind} players={players} />);
        // All tables should have these shared headers
        expect(screen.getByText("Groupe")).toBeInTheDocument();
        expect(screen.getByText("Nom")).toBeInTheDocument();
        expect(screen.getByText("Rôles")).toBeInTheDocument();
      },
    );
  });
});
