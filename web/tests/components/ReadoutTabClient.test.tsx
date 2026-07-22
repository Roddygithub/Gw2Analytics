/**
 * Unit tests for ReadoutTabClient sub-components: GlobalStatsBar
 * and TimelineMiniChart activity toggle.
 *
 * Verifies:
 *  1. GlobalStatsBar renders squad aggregate badges (DPS, Heal/s, etc.)
 *  2. GlobalStatsBar shows healer/support counts only when present
 *  3. TimelineMiniChart toggle switches between "Toute la durée" and
 *     "Activité seulement" modes
 *  4. TimelineMiniChart shows activity stats in activity mode
 */

import { describe, expect, it, vi } from "vitest";
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// We test the components as part of the full ReadoutTabClient.
// Mock the API fetchers so we can render the client without network.
const mockFetchReadout = vi.fn();
const mockFetchPositions = vi.fn().mockResolvedValue({ players: [] });
const mockFetchEvents = vi.fn();

vi.mock("@/lib/api", () => ({
  fetchFightReadout: (...args: unknown[]) => mockFetchReadout(...args),
  fetchFightPositions: (...args: unknown[]) => mockFetchPositions(...args),
  fetchFightEvents: (...args: unknown[]) => mockFetchEvents(...args),
}));

// Mock PlayerPositionHeatmap (heavy canvas component)
vi.mock("@/components/PlayerPositionHeatmap", () => ({
  PlayerPositionHeatmap: () =>
    React.createElement("div", { "data-testid": "mock-heatmap" }, "Heatmap"),
}));

// Mock FightSummaryCards
vi.mock("@/components/FightSummaryCards", () => ({
  FightSummaryCards: () =>
    React.createElement("div", { "data-testid": "mock-summary" }, "Summary"),
}));

// Mock PlayerReadoutCells (icon components)
vi.mock("@/components/PlayerReadoutCells", () => ({
  EliteSpecCellRenderer: () =>
    React.createElement("span", { "data-testid": "mock-elite" }, "Spec"),
  CommanderCellRenderer: () =>
    React.createElement("span", { "data-testid": "mock-cmd" }, "Cmd"),
}));

import { ReadoutTabClient } from "@/components/ReadoutTabClient";
import type { PlayerReadoutOut, FightReadoutOut } from "@/lib/api";

/* ------------------------------------------------------------------ *
 *  Factory helpers
 * ------------------------------------------------------------------ */

function makePlayer(overrides: Partial<PlayerReadoutOut> = {}): PlayerReadoutOut {
  return {
    account_name: "Test.1234",
    agent_id: 1,
    boons: {
      aegis_out: 0,
      alacrity_out: 0,
      boons_in_rate: 0,
      boons_out_rate: 0,
      other_boons_out: {},
      might_uptime: 50,
      fury_uptime: 30,
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
      cc_applied: 5,
      down_contribution_dps: 1200,
      dps_condi: 500,
      dps_power: 1000,
      dps_total: 1500,
      kills: 2,
      strips: 4,
      cleave_targets: 0,
      kill_participation: 0,
    },
    defense: {
      barrier_absorbed: 0,
      presence_pct: 90,
      blocks: 1,
      cc_taken: 2,
      damage_taken: 5000,
      deaths: 0,
      dodges: 3,
      interrupts: 1,
      time_downed_ms: 0,
      dist_to_commander: 200,
      kill_participation: 0,
    },
    elite_spec: "Berserker",
    heal: {
      barrier_ps: 100,
      barrier_total: 5000,
      cleanses: 3,
      heal_total: 800,
      hps: 200,
      stun_breaks: 1,
    },
    is_commander: false,
    name: "Test Player",
    profession: "Warrior",
    roles: ["DPS"],
    subgroup: 1,
    ...overrides,
  };
}

function makeReadout(players: PlayerReadoutOut[]): FightReadoutOut {
  return {
    fight_id: "test-fight",
    duration_s: 600,
    players,
  };
}

function makeEvents(activeCount: number): unknown {
  // Build event_windows with N active (non-zero) windows and many zero windows.
  const windows = [];
  for (let i = 0; i < activeCount; i++) {
    windows.push({
      start_ms: i * 5000,
      end_ms: (i + 1) * 5000,
      damage_total: 5000 + i * 100,
      healing_total: 1000 + i * 50,
      strip_total: 0,
    });
  }
  // Add many zero windows to simulate WvW idle periods
  for (let i = activeCount; i < 200; i++) {
    windows.push({
      start_ms: i * 5000,
      end_ms: (i + 1) * 5000,
      damage_total: 0,
      healing_total: 0,
      strip_total: 0,
    });
  }
  return { event_windows: windows };
}

/* ------------------------------------------------------------------ *
 *  GlobalStatsBar tests
 * ------------------------------------------------------------------ */

describe("GlobalStatsBar", () => {
  it("renders squad DPS, Heal/s, Strips, Cleanses, CC badges", async () => {
    const p1 = makePlayer({ name: "DPS1", damage: { ...makePlayer().damage, dps_total: 2000, strips: 10, cc_applied: 7 }, heal: { ...makePlayer().heal, cleanses: 5 } });
    const p2 = makePlayer({ name: "DPS2", agent_id: 2, damage: { ...makePlayer().damage, dps_total: 1000, strips: 3, cc_applied: 2 }, heal: { ...makePlayer().heal, cleanses: 2 } });

    mockFetchReadout.mockResolvedValueOnce(makeReadout([p1, p2]));
    mockFetchEvents.mockResolvedValueOnce(makeEvents(5));

    render(<ReadoutTabClient fightId="test-fight" />);

    await waitFor(() => {
      expect(screen.queryByText("Chargement")).toBeNull();
    });

    // Check squad DPS total via data-testid
    const dpsBadge = screen.getByTestId("stat-badge-dps");
    expect(dpsBadge).toBeInTheDocument();
    expect(dpsBadge).toHaveTextContent("3000");
    // Check Heal/s
    const healBadge = screen.getByTestId("stat-badge-heal-s");
    expect(healBadge).toHaveTextContent("400");
    // Check strips
    const stripBadge = screen.getByTestId("stat-badge-strips");
    expect(stripBadge).toHaveTextContent("13");
    // Check cleanses
    const cleanseBadge = screen.getByTestId("stat-badge-cleanses");
    expect(cleanseBadge).toHaveTextContent("7");
    // Check CC
    const ccBadge = screen.getByTestId("stat-badge-cc");
    expect(ccBadge).toHaveTextContent("9");
  });

  it("shows healer and support counts when present", async () => {
    const healer = makePlayer({ name: "Healer", agent_id: 1, roles: ["Heal"] });
    const support = makePlayer({ name: "Support", agent_id: 2, roles: ["Support"] });
    const dps = makePlayer({ name: "DPS", agent_id: 3, roles: ["DPS"] });

    mockFetchReadout.mockResolvedValueOnce(makeReadout([healer, support, dps]));
    mockFetchEvents.mockResolvedValueOnce(makeEvents(3));

    render(<ReadoutTabClient fightId="test-fight" />);

    await waitFor(() => {
      expect(screen.queryByText("Chargement")).toBeNull();
    });

    expect(screen.getByTestId("stat-badge-healers")).toBeInTheDocument();
    expect(screen.getByTestId("stat-badge-supports")).toBeInTheDocument();
    expect(screen.getByTestId("stat-badge-healers")).toHaveTextContent("1");
    expect(screen.getByTestId("stat-badge-supports")).toHaveTextContent("1");
  });

  it("does not show healer badge when no healers", async () => {
    const dps1 = makePlayer({ name: "DPS1", agent_id: 1, roles: ["DPS"] });
    const dps2 = makePlayer({ name: "DPS2", agent_id: 2, roles: ["DPS", "CC"] });

    mockFetchReadout.mockResolvedValueOnce(makeReadout([dps1, dps2]));
    mockFetchEvents.mockResolvedValueOnce(makeEvents(2));

    render(<ReadoutTabClient fightId="test-fight" />);

    await waitFor(() => {
      expect(screen.queryByText("Chargement")).toBeNull();
    });

    expect(screen.queryByTestId("stat-badge-healers")).not.toBeInTheDocument();
    expect(screen.queryByTestId("stat-badge-supports")).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ *
 *  TimelineMiniChart activity toggle tests
 * ------------------------------------------------------------------ */

describe("TimelineMiniChart activity toggle", () => {
  it("renders 'Toute la durée' toggle by default", async () => {
    mockFetchReadout.mockResolvedValueOnce(makeReadout([makePlayer()]));
    mockFetchEvents.mockResolvedValueOnce(makeEvents(5));

    render(<ReadoutTabClient fightId="test-fight" />);

    await waitFor(() => {
      expect(screen.queryByText("Chargement")).toBeNull();
    });

    // The toggle should show "Toute la durée" by default (inactive state)
    expect(screen.getByText("Toute la durée")).toBeInTheDocument();
  });

  it("switches to 'Activité seulement' on click", async () => {
    mockFetchReadout.mockResolvedValueOnce(makeReadout([makePlayer()]));
    mockFetchEvents.mockResolvedValueOnce(makeEvents(5));

    render(<ReadoutTabClient fightId="test-fight" />);

    await waitFor(() => {
      expect(screen.queryByText("Chargement")).toBeNull();
    });

    const toggle = screen.getByText("Toute la durée");
    fireEvent.click(toggle);

    // Should switch to activity-only mode
    expect(screen.getByText(/Activité seulement/)).toBeInTheDocument();

    // Should show activity stats (5 pics out of 200 windows = 2.5%)
    expect(screen.getByText(/pics/)).toBeInTheDocument();
  });

  it("shows the full duration stats in default mode", async () => {
    mockFetchReadout.mockResolvedValueOnce(makeReadout([makePlayer()]));
    mockFetchEvents.mockResolvedValueOnce(makeEvents(5));

    render(<ReadoutTabClient fightId="test-fight" />);

    await waitFor(() => {
      expect(screen.queryByText("Chargement")).toBeNull();
    });

    // Default mode shows bucket count + duration
    expect(screen.getByText(/200 buckets/)).toBeInTheDocument();
  });
});
