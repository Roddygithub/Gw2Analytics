import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import {
  CommanderCellRenderer,
  EliteSpecCellRenderer,
} from "@/components/PlayerReadoutCells";
import {
  parseWireFormat,
  getProfessionIconPath,
  getEliteIconPath,
  getProfessionLabel,
  getEliteLabel,
} from "@/components/icons/Professions";
import type { PlayerReadoutOut } from "@/lib/api";

/**
 * F17 W.1 v2 — vitest specs for the wire-format-aware icon
 * helpers + AG Grid cellRenderer components.
 *
 * Fixture wire shapes (mirrors the API contract):
 *   - "PROF(N)"  for profession N (1..9)
 *   - "UNKNOWN"  for profession 0 sentinel
 *   - "ELITE(N)" for elite spec N (EliteSpec enum)
 *   - "BASE"     for elite spec 0 sentinel
 *
 * Critical: tests use the REAL wire strings, NOT the human-readable
 * enum names. The previous v1 used "GUARDIAN" / "Dragonhunter"
 * literals which never matched the wire.
 */

function makeRow(overrides: Partial<PlayerReadoutOut>): PlayerReadoutOut {
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
    },
    ...overrides,
  };
}

/* ------------------------------------------------------------------ *
 *  parseWireFormat
 * ------------------------------------------------------------------ */

describe("parseWireFormat (wire parser)", () => {
  it("parses 'PROF(1)' as profession int 1", () => {
    expect(parseWireFormat("PROF(1)")).toEqual({ kind: "profession", int: 1 });
  });

  it("parses 'PROF(7)' as profession int 7 (Mesmer)", () => {
    expect(parseWireFormat("PROF(7)")).toEqual({ kind: "profession", int: 7 });
  });

  it("parses 'ELITE(18)' as elite int 18 (Berserker)", () => {
    expect(parseWireFormat("ELITE(18)")).toEqual({ kind: "elite", int: 18 });
  });

  it("parses 'ELITE(27)' as elite int 27 (Dragonhunter)", () => {
    expect(parseWireFormat("ELITE(27)")).toEqual({ kind: "elite", int: 27 });
  });

  it("parses 'UNKNOWN' as kind=unknown int=0", () => {
    expect(parseWireFormat("UNKNOWN")).toEqual({ kind: "unknown", int: 0 });
  });

  it("parses 'BASE' as kind=elite int=0", () => {
    expect(parseWireFormat("BASE")).toEqual({ kind: "elite", int: 0 });
  });

  it("returns null for unparseable strings", () => {
    expect(parseWireFormat("GUARDIAN")).toBeNull();
    expect(parseWireFormat("Dragonhunter")).toBeNull();
    expect(parseWireFormat("PROF()")).toBeNull();
    expect(parseWireFormat("PROF(abc)")).toBeNull();
    expect(parseWireFormat("")).toBeNull();
  });

  it("returns null for null / undefined inputs", () => {
    expect(parseWireFormat(null)).toBeNull();
    expect(parseWireFormat(undefined)).toBeNull();
  });
});

/* ------------------------------------------------------------------ *
 *  Profession icon lookup
 * ------------------------------------------------------------------ */

describe("getProfessionIconPath", () => {
  it("maps 'PROF(1)' to Guardian icon", () => {
    expect(getProfessionIconPath("PROF(1)")).toBe(
      "/icons/professions/Guardian_tango.png",
    );
  });

  it("maps 'PROF(7)' to Mesmer icon", () => {
    expect(getProfessionIconPath("PROF(7)")).toBe(
      "/icons/professions/Mesmer_tango.png",
    );
  });

  it("returns null for 'UNKNOWN' (profession 0 sentinel)", () => {
    expect(getProfessionIconPath("UNKNOWN")).toBeNull();
  });

  it("returns null for an unknown future profession int (PROF(99))", () => {
    expect(getProfessionIconPath("PROF(99)")).toBeNull();
  });

  it("returns null for non-wire strings (TitleCase / UPPER keys)", () => {
    // Belt-and-braces: backward-compat with v1 callers.
    expect(getProfessionIconPath("GUARDIAN")).toBeNull();
    expect(getProfessionIconPath("Guardian")).toBeNull();
  });

  it("returns null for null / undefined", () => {
    expect(getProfessionIconPath(null)).toBeNull();
    expect(getProfessionIconPath(undefined)).toBeNull();
  });
});

describe("getProfessionLabel", () => {
  it("returns 'Guardian' for PROF(1)", () => {
    expect(getProfessionLabel("PROF(1)")).toBe("Guardian");
  });

  it("returns 'Mesmer' for PROF(7)", () => {
    expect(getProfessionLabel("PROF(7)")).toBe("Mesmer");
  });

  it("returns 'Unknown' for the UNKNOWN sentinel", () => {
    expect(getProfessionLabel("UNKNOWN")).toBe("Unknown");
  });
});

/* ------------------------------------------------------------------ *
 *  Elite icon lookup + collision resolution
 * ------------------------------------------------------------------ */

describe("getEliteIconPath", () => {
  it("maps ELITE(18) (Berserker) to its icon", () => {
    expect(getEliteIconPath("ELITE(18)", "PROF(2)")).toBe(
      "/icons/specializations/Berserker_tango.png",
    );
  });

  it("maps ELITE(27) (Dragonhunter) to its icon", () => {
    expect(getEliteIconPath("ELITE(27)", "PROF(1)")).toBe(
      "/icons/specializations/Dragonhunter_tango.png",
    );
  });

  it("returns null for BASE sentinel (no elite active)", () => {
    expect(getEliteIconPath("BASE", "PROF(1)")).toBeNull();
  });

  it("returns null for an unknown future elite int", () => {
    expect(getEliteIconPath("ELITE(999)", "PROF(1)")).toBeNull();
  });

  it("***conflict resolution: ELITE(55) + Ranger=4 -> Soulbeast", () => {
    expect(getEliteIconPath("ELITE(55)", "PROF(4)")).toBe(
      "/icons/specializations/Soulbeast_tango.png",
    );
  });

  it("***conflict resolution: ELITE(55) + Thief=5 -> Daredevil", () => {
    expect(getEliteIconPath("ELITE(55)", "PROF(5)")).toBe(
      "/icons/specializations/Daredevil_tango.png",
    );
  });

  it("***conflict resolution: ELITE(63) + Elementalist=6 -> Weaver", () => {
    expect(getEliteIconPath("ELITE(63)", "PROF(6)")).toBe(
      "/icons/specializations/Weaver_tango.png",
    );
  });

  it("***conflict resolution: ELITE(63) + Revenant=9 -> Renegade", () => {
    expect(getEliteIconPath("ELITE(63)", "PROF(9)")).toBe(
      "/icons/specializations/Renegade_tango.png",
    );
  });

  it("conflict resolution: ELITE(55) without profession context returns null (NO guessing)", () => {
    // Without the tiebreaker, the lookup refuses to pick —
    // surfaces the conflict as a fallback span (diagnosable).
    expect(getEliteIconPath("ELITE(55)", null)).toBeNull();
    expect(getEliteIconPath("ELITE(55)", "UNKNOWN")).toBeNull();
  });
});

describe("getEliteLabel", () => {
  it("returns 'Berserker' for ELITE(18)", () => {
    expect(getEliteLabel("ELITE(18)", "PROF(2)")).toBe("Berserker");
  });

  it("returns 'Soulbeast' for the ELITE(55)+Ranger collision", () => {
    expect(getEliteLabel("ELITE(55)", "PROF(4)")).toBe("Soulbeast");
  });

  it("returns 'Daredevil' for the ELITE(55)+Thief collision", () => {
    expect(getEliteLabel("ELITE(55)", "PROF(5)")).toBe("Daredevil");
  });
});

/* ------------------------------------------------------------------ *
 *  Cell-renderer React component (EliteSpecCellRenderer)
 * ------------------------------------------------------------------ */

describe("EliteSpecCellRenderer", () => {
  it("renders the elite icon + visible human label for an active elite (Berserker)", () => {
    render(
      <EliteSpecCellRenderer
        data={makeRow({
          profession: "PROF(2)",
          elite_spec: "ELITE(18)", // Berserker on Warrior
        })}
      />,
    );
    const cell = screen.getByTestId("elite-spec-cell");
    expect(cell).toBeInTheDocument();
    // ``data-elite-spec`` carries the wire string for DevTools
    // introspection (analysts + post-mortem debugging).
    expect(cell.dataset.eliteSpec).toBe("ELITE(18)");
    const img = screen.getByTestId("tango-icon");
    expect(img).toHaveAttribute("alt", "Berserker");
    expect(img).toHaveAttribute(
      "src",
      "/icons/specializations/Berserker_tango.png",
    );
    // V2 regression-locked: the visible cell label MUST be the
    // human-readable ``Berserker``, NOT the wire token ``ELITE(18)``.
    expect(cell).toHaveTextContent("Berserker");
    expect(cell).not.toHaveTextContent("ELITE(18)");
  });

  it("renders the profession icon + visible human label when elite_spec is BASE", () => {
    render(
      <EliteSpecCellRenderer
        data={makeRow({ profession: "PROF(7)", elite_spec: "BASE" })} // Mesmer no elite
      />,
    );
    const cell = screen.getByTestId("profession-cell");
    expect(cell).toBeInTheDocument();
    const img = screen.getByTestId("tango-icon");
    expect(img).toHaveAttribute("alt", "Mesmer");
    expect(img).toHaveAttribute(
      "src",
      "/icons/professions/Mesmer_tango.png",
    );
    // V2 regression-locked: the ``BASE`` sentinel MUST NOT leak
    // into the visible label (the most confusing wire token —
    // analysts should see ``Mesmer`` regardless of elite presence).
    expect(cell).toHaveTextContent("Mesmer");
    expect(cell).not.toHaveTextContent("BASE");
  });

  it("falls back to '—' when both profession and elite are unparseable", () => {
    // BOTH profession and elite are non-wire strings so neither
    // ``parseWireFormat`` call yields a parseable result; the
    // fallback span renders (no icon) and the visible label is
    // the em-dash "—".
    // We do NOT use ``"UNKNOWN"`` because the profession wire
    // formatter emits the human-readable label "Unknown" (via
    // ``getProfessionLabel``) — not the em-dash. Only fully
    // bogus strings exercise the em-dash path.
    render(
      <EliteSpecCellRenderer
        data={makeRow({
          profession: "BOGUS_PROFESSION",
          elite_spec: "BOGUS_ELITE",
        })}
      />,
    );
    const fallback = screen.getByTestId("tango-icon-fallback");
    expect(fallback).toBeInTheDocument();
    expect(fallback.dataset.iconFallback).toBe("BOGUS_PROFESSION");
    // Visible label falls back to em-dash so the cell never
    // exposes the raw wire token to the user.
    expect(fallback.parentElement).toHaveTextContent("—");
  });

  it("renders the conflict-resolved Soulbeast icon for ELITE(55) on Ranger (PROF(4))", () => {
    render(
      <EliteSpecCellRenderer
        data={makeRow({ profession: "PROF(4)", elite_spec: "ELITE(55)" })}
      />,
    );
    const cell = screen.getByTestId("elite-spec-cell");
    const img = screen.getByTestId("tango-icon");
    expect(img).toHaveAttribute("alt", "Soulbeast");
    expect(img).toHaveAttribute(
      "src",
      "/icons/specializations/Soulbeast_tango.png",
    );
    // V2 regression-locked: visible label MUST be the human-readable "Soulbeast", not "ELITE(55)"
    expect(cell).toHaveTextContent("Soulbeast");
    expect(cell).not.toHaveTextContent("ELITE(55)");
  });

  it("renders the conflict-resolved Daredevil icon for ELITE(55) on Thief (PROF(5))", () => {
    render(
      <EliteSpecCellRenderer
        data={makeRow({ profession: "PROF(5)", elite_spec: "ELITE(55)" })}
      />,
    );
    const cell = screen.getByTestId("elite-spec-cell");
    const img = screen.getByTestId("tango-icon");
    expect(img).toHaveAttribute("alt", "Daredevil");
    expect(img).toHaveAttribute(
      "src",
      "/icons/specializations/Daredevil_tango.png",
    );
    // V2 regression-locked: visible label MUST be "Daredevil", not the wire token
    expect(cell).toHaveTextContent("Daredevil");
    expect(cell).not.toHaveTextContent("ELITE(55)");
  });

  it("renders the conflict-resolved Renegade icon for ELITE(63) on Revenant (PROF(9))", () => {
    render(
      <EliteSpecCellRenderer
        data={makeRow({ profession: "PROF(9)", elite_spec: "ELITE(63)" })}
      />,
    );
    const cell = screen.getByTestId("elite-spec-cell");
    const img = screen.getByTestId("tango-icon");
    expect(img).toHaveAttribute("alt", "Renegade");
    expect(img).toHaveAttribute(
      "src",
      "/icons/specializations/Renegade_tango.png",
    );
    // V2 regression-locked: visible label MUST be "Renegade", not the wire token
    expect(cell).toHaveTextContent("Renegade");
    expect(cell).not.toHaveTextContent("ELITE(63)");
  });

  it("falls back to the data-testid fallback span when profession is the UNKNOWN sentinel", () => {
    render(
      <EliteSpecCellRenderer
        data={makeRow({ profession: "UNKNOWN", elite_spec: "BASE" })}
      />,
    );
    const fallback = screen.getByTestId("tango-icon-fallback");
    expect(fallback).toBeInTheDocument();
    expect(fallback.dataset.iconFallback).toBe("UNKNOWN");
  });

  it("falls back to the data-testid fallback span for an unknown future elite int", () => {
    render(
      <EliteSpecCellRenderer
        data={makeRow({ profession: "PROF(2)", elite_spec: "ELITE(999)" })}
      />,
    );
    const fallback = screen.getByTestId("tango-icon-fallback");
    expect(fallback.dataset.iconFallback).toBe("ELITE(999)");
  });

  it("returns null when the data param is undefined", () => {
    const { container } = render(<EliteSpecCellRenderer data={undefined} />);
    expect(container.querySelector("[data-testid]")).toBeNull();
  });
});

/* ------------------------------------------------------------------ *
 *  Cell-renderer React component (CommanderCellRenderer)
 * ------------------------------------------------------------------ */

describe("CommanderCellRenderer", () => {
  it("renders an inline-SVG crown when is_commander is true", () => {
    render(<CommanderCellRenderer data={makeRow({ is_commander: true })} />);
    const crowned = screen.getByTestId("commander-cell-crowned");
    expect(crowned).toBeInTheDocument();
    expect(crowned.dataset.commander).toBe("true");
    expect(screen.getByTestId("commander-crown").querySelector("svg")).not.toBeNull();
  });

  it("renders an empty span (commander-cell-empty) when is_commander is false", () => {
    render(<CommanderCellRenderer data={makeRow({ is_commander: false })} />);
    const empty = screen.getByTestId("commander-cell-empty");
    expect(empty).toBeInTheDocument();
    expect(empty.querySelector("svg")).toBeNull();
  });
});
