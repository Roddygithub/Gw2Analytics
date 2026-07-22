import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

// Mock the icon components since they depend on static image assets
vi.mock("@/components/icons/Professions", () => ({
  EliteSpecIcon: ({ size }: { size?: number }) => (
    <span data-testid="mock-elite-icon" data-size={size} />
  ),
  ProfessionIcon: ({ size }: { size?: number }) => (
    <span data-testid="mock-profession-icon" data-size={size} />
  ),
  getEliteLabel: () => "Firebrand",
  getProfessionLabel: () => "Guardian",
  parseWireFormat: () => ({ kind: "elite" as const, int: 62 }),
}));

vi.mock("@/components/icons/Commander", () => ({
  CommanderCrown: ({ size }: { size?: number }) => (
    <span data-testid="mock-commander-crown" data-size={size} />
  ),
}));

import { FightSummaryCards } from "@/components/FightSummaryCards";
import type { PlayerReadoutOut } from "@/lib/api";

function buildPlayer(extra: Partial<PlayerReadoutOut> = {}): PlayerReadoutOut {
  return {
    agent_id: 10001,
    subgroup: 1,
    name: "Player One",
    account_name: "TestAccount.1234",
    profession: "PROF(1)",
    elite_spec: "ELITE(62)",
    is_commander: true,
    roles: ["DPS"],
    damage: {
      dps_total: 4500,
      dps_power: 0,
      dps_condi: 0,
      strips: 12,
      cc_applied: 450,
      down_contribution_dps: 1200,
      kills: 3,
      cleave_targets: 0,
      kill_participation: 0,
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
      damage_taken: 45000,
      cc_taken: 2,
      deaths: 0,
      time_downed_ms: 0,
      dodges: 14,
      blocks: 45,
      interrupts: 1,
      barrier_absorbed: 15015,
      presence_pct: null,
      dist_to_commander: null,
      kill_participation: 0,
    },
    ...extra,
  };
}

describe("FightSummaryCards", () => {
  it("renders nothing when players array is empty", () => {
    const { container } = render(<FightSummaryCards players={[]} />);
    expect(container.textContent).toBe("");
  });

  it("renders the fight-summary section with 6 cards", () => {
    const players = [buildPlayer()];
    const { container } = render(<FightSummaryCards players={players} />);
    const section = container.querySelector('[data-testid="fight-summary"]');
    expect(section).not.toBeNull();
    // Should show all 6 card headers
    expect(container.textContent).toContain("Fight Summary");
    expect(container.textContent).toContain("Top DPS");
    expect(container.textContent).toContain("Top Heal");
    expect(container.textContent).toContain("Top Strips");
    expect(container.textContent).toContain("Top Cleanses");
    expect(container.textContent).toContain("Top CC");
    expect(container.textContent).toContain("Down Contrib");
  });

  it("renders player name and subgroup badge", () => {
    const players = [buildPlayer({ name: "Alpha", subgroup: 2 })];
    const { container } = render(<FightSummaryCards players={players} />);
    expect(container.textContent).toContain("Alpha");
    expect(container.textContent).toContain("Sub 2");
  });

  it("shows commander crown for commanders", () => {
    const players = [buildPlayer({ is_commander: true })];
    const { container } = render(<FightSummaryCards players={players} />);
    expect(
      container.querySelector('[data-testid="mock-commander-crown"]'),
    ).not.toBeNull();
  });

  it("renders elite icon when elite_spec is present", () => {
    const players = [buildPlayer({ elite_spec: "ELITE(62)" })];
    const { container } = render(<FightSummaryCards players={players} />);
    expect(
      container.querySelector('[data-testid="mock-elite-icon"]'),
    ).not.toBeNull();
  });

  it("handles multiple players and shows medal emojis", () => {
    const players = [
      buildPlayer({ agent_id: 1, name: "A", damage: { ...buildPlayer().damage, dps_total: 1000 } }),
      buildPlayer({ agent_id: 2, name: "B", damage: { ...buildPlayer().damage, dps_total: 2000 } }),
      buildPlayer({ agent_id: 3, name: "C", damage: { ...buildPlayer().damage, dps_total: 3000 } }),
    ];
    const { container } = render(<FightSummaryCards players={players} />);
    // Top DPS should show 🥇🥈🥉
    expect(container.textContent).toContain("🥇");
    expect(container.textContent).toContain("🥈");
    expect(container.textContent).toContain("🥉");
  });
});
