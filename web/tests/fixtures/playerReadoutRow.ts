import type { PlayerReadoutOut } from "@/lib/api";

/**
 * Shared test fixture builder for ``PlayerReadoutOut``.
 *
 * Returns a minimal row with all numeric fields set to 0 / null so
 * individual tests can override only the fields they care about.
 * The default uses ``PROF(1)`` (Guardian) / ``BASE`` (core spec),
 * matching the wire format the API emits.
 *
 * Use the optional ``overrides`` param to customise the returned row
 * for a specific test case — the spread ``...overrides`` happens
 * **after** the defaults, so you can override any top-level field
 * (damage, heal, boons, defense, etc.).
 *
 * ```ts
 * // Default row — all zeros, Guardian core
 * buildPlayerReadoutRow()
 *
 * // Customised row — Guardian Dragonhunter with 30k DPS
 * buildPlayerReadoutRow({
 *   name: "Top DPS",
 *   elite_spec: "ELITE(27)",
 *   damage: { dps_total: 30000, dps_power: 20000, dps_condi: 10000, ... },
 * })
 * ```
 */
export function buildPlayerReadoutRow(
  overrides: Partial<PlayerReadoutOut> = {},
): PlayerReadoutOut {
  return {
    agent_id: 1,
    account_name: ":test.1234",
    name: "Test Character",
    profession: "PROF(1)", // Guardian
    elite_spec: "BASE",
    subgroup: 1,
    is_commander: false,
    roles: ["DPS"],
    damage: {
      dps_total: 0,
      dps_power: 0,
      dps_condi: 0,
      strips: 0,
      cc_applied: 0,
      down_contribution_dps: 0,
      kills: 0,
      cleave_targets: 0,
      kill_participation: 0,
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
      damage_taken: 0,
      cc_taken: 0,
      deaths: 0,
      time_downed_ms: 0,
      dodges: 0,
      blocks: 0,
      interrupts: 0,
      barrier_absorbed: 0,
      presence_pct: null,
      dist_to_commander: null,
      kill_participation: 0,
    },
    ...overrides,
  };
}
