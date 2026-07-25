import { describe, expect, it } from "vitest";

import { buildPlayerReadoutRow } from "./playerReadoutRow";

describe("buildPlayerReadoutRow", () => {
  it("returns a complete PlayerReadoutOut with default values", () => {
    const row = buildPlayerReadoutRow();

    // Top-level defaults
    expect(row.agent_id).toBe(1);
    expect(row.account_name).toBe(":test.1234");
    expect(row.name).toBe("Test Character");
    expect(row.profession).toBe("PROF(1)");
    expect(row.elite_spec).toBe("BASE");
    expect(row.subgroup).toBe(1);
    expect(row.is_commander).toBe(false);
    expect(row.roles).toEqual(["DPS"]);

    // Damage — all zeros
    expect(row.damage.dps_total).toBe(0);
    expect(row.damage.dps_power).toBe(0);
    expect(row.damage.dps_condi).toBe(0);
    expect(row.damage.strips).toBe(0);

    // Heal — all zeros
    expect(row.heal.hps).toBe(0);
    expect(row.heal.cleanses).toBe(0);

    // Boons — uptime nulls, outgoing nulls
    expect(row.boons.might_uptime).toBeNull();
    expect(row.boons.fury_uptime).toBeNull();
    expect(row.boons.outgoing_might).toBeNull();
    expect(row.boons.outgoing_stability).toBeNull();
    expect(row.boons.other_boons_out).toEqual({});

    // Defense — zeros and nulls
    expect(row.defense.damage_taken).toBe(0);
    expect(row.defense.presence_pct).toBeNull();
    expect(row.defense.dist_to_commander).toBeNull();
  });

  it("allows overriding top-level fields", () => {
    const row = buildPlayerReadoutRow({ name: "Custom Name", subgroup: 5 });
    expect(row.name).toBe("Custom Name");
    expect(row.subgroup).toBe(5);
    // Unchanged defaults
    expect(row.profession).toBe("PROF(1)");
    expect(row.defense.damage_taken).toBe(0);
  });

  it("allows overriding nested damage fields by spreading the default", () => {
    const defaults = buildPlayerReadoutRow().damage;
    const row = buildPlayerReadoutRow({
      damage: { ...defaults, dps_total: 30000, dps_power: 20000, dps_condi: 10000 },
    });
    expect(row.damage.dps_total).toBe(30000);
    expect(row.damage.dps_power).toBe(20000);
    expect(row.damage.dps_condi).toBe(10000);
    // Non-overridden fields preserved from defaults
    expect(row.damage.strips).toBe(0);
    expect(row.damage.cc_applied).toBe(0);
  });

  it("allows overriding nested boon fields by spreading the default", () => {
    // ``...overrides`` replaces the entire boons object at the top level,
    // so callers must spread the default sub-object before overriding.
    const defaults = buildPlayerReadoutRow().boons;
    const row = buildPlayerReadoutRow({
      boons: { ...defaults, might_uptime: 85, fury_uptime: 70 },
    });
    expect(row.boons.might_uptime).toBe(85);
    expect(row.boons.fury_uptime).toBe(70);
    // Non-overridden fields preserved from defaults
    expect(row.boons.quickness_uptime).toBeNull();
    expect(row.boons.outgoing_might).toBeNull();
    expect(row.boons.outgoing_stability).toBeNull();
  });

  it("allows overriding nested defense fields by spreading the default", () => {
    const defaults = buildPlayerReadoutRow().defense;
    const row = buildPlayerReadoutRow({
      defense: { ...defaults, damage_taken: 50000, presence_pct: 95 },
    });
    expect(row.defense.damage_taken).toBe(50000);
    expect(row.defense.presence_pct).toBe(95);
    // Non-overridden fields preserved from defaults
    expect(row.defense.deaths).toBe(0);
    expect(row.defense.dist_to_commander).toBeNull();
  });

  it("accepts an empty overrides object", () => {
    const row = buildPlayerReadoutRow({});
    expect(row.agent_id).toBe(1);
    expect(row.name).toBe("Test Character");
  });

  it("accepts no arguments", () => {
    const row = buildPlayerReadoutRow();
    expect(row.agent_id).toBe(1);
  });

  it("overrides roles array", () => {
    const row = buildPlayerReadoutRow({ roles: ["Heal", "CC"] });
    expect(row.roles).toEqual(["Heal", "CC"]);
  });
});
