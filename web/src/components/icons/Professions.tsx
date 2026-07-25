"use client";

/**
 * F17 W.1 v2 — Tango Medium profession + elite-specification icons.
 *
 * Wire-format alignment
 * =====================
 *
 * The /api/v1/fights/{fight_id}/readout combat-readout wire shape
 * emits the player's ``profession`` / ``elite_spec`` strings via
 * ``apps/api/src/gw2analytics_api/route_helpers.format_profession`` /
 * ``format_elite_spec`` (the canonical formatters). Their output
 * shape is the lock-in that this module targets:
 *
 *   - ``"PROF(N)"``  for profession N (1..9)            — e.g. ``"PROF(1)"`` for Guardian
 *   - ``"UNKNOWN"``   for profession 0                 — no profession detected
 *   - ``"ELITE(N)"`` for elite spec N (integer per `gw2_core.EliteSpec`)
 *   - ``"BASE"``      for elite spec 0                 — no elite active
 *
 * The previous string-literal lookup (TitleCase / UPPER keys) DID
 * NOT match the wire and silently fell back to empty ``<span>`` —
 * every row rendered icon-less. This rewrite parses the wire
 * strings to extract the integer + dispatches via int-keyed tables.
 *
 * Two source-of-truth IntEnum tables back the lookup
 * (mirrored from ``libs/gw2_core/src/gw2_core/models.py``):
 * - ``Profession`` (9 members + UNKNOWN=0)
 * - ``EliteSpec``  (~27 members, two historic collisions noted below)
 *
 * Elite-spec int collisions (legacy arcdps byte re-use)
 * ====================================================
 *
 * Two elite ints collide across professions and require the
 * profession as a tiebreaker:
 *
 * - int=55: ``SOULBEAST`` (Ranger=4) vs ``DAREDEVIL`` (Thief=5)
 * - int=63: ``WEAVER``    (Elementalist=6) vs ``RENEGADE`` (Revenant=9)
 *
 * The client-side lookup takes BOTH the elite wire string AND the
 * profession wire string so the conflict resolution is unambiguous
 * (the wire emits both fields). The flat ``ELITE_ICONS_BY_INT``
 * table omits the conflict ints; the ``ELITE_ICONS_BY_INT_AND_PROFESSION``
 * map carries the conflict resolution per profession.
 *
 * Forward-compat unlocks
 * ======================
 *
 * New ``Profession`` member (e.g. a future profession #10):
 * - Wire emits ``"PROF(10)"``. ``PROFESSION_ICONS_BY_INT[10]``
 *   is undefined, so the lookup returns ``null`` + the cell
 *   renderer renders the empty ``data-testid="tango-icon-fallback"``
 *   span. A future refresh of this module adds the integer + the
 *   icon path.
 *
 * New ``EliteSpec`` member (post-Janthir Wilds):
 * - Same story — flat table returns ``null`` + the fallback span
 *   renders. Future refresh adds the int + icon.
 *
 * Why <img> (not ``next/image``)
 * ==============================
 *
 * AG Grid's cellRenderer mounts + unmounts rapidly during row
 * virtualization. ``next/image``'s intersection-observer wrappers
 * + the injected <span> DOM cause visible row-scroll stuttering +
 * memory leaks inside ``ag-grid-react``. Native <img> with
 * ``loading="lazy"`` + ``decoding="async"`` is the AG Grid-recommended
 * pattern.
 *
 * Why a Client Component ("use client")
 * ======================================
 *
 * AG Grid's cellRenderer is client-side DOM. Server-rendering the
 * same <img> would not benefit hydration.
 */

import React from "react";

/* ------------------------------------------------------------------ *
 *  Wire-format parser
 * ------------------------------------------------------------------ */

/**
 * Result of parsing a Combat-readout wire profession / elite string.
 *
 * The API ``/api/v1/fights/{id}/readout`` emits canonical profession
 * names (e.g. ``"Guardian"``) and elite-spec names (e.g. ``"Firebrand"``)
 * via ``route_helpers.format_profession`` / ``format_elite_spec``.
 *
 * - ``kind='profession'`` — a known profession name matched.
 * - ``kind='elite'`` — a known elite-spec name matched OR ``"BASE"``.
 * - ``kind='unknown'`` — ``"UNKNOWN"`` sentinel (profession 0).
 * - ``null`` — unrecognised string.
 *
 * Backward-compat: the legacy ``PROF(N)`` / ``ELITE(N)`` wire format
 * is also parsed for pre-v0.16.2-api fight data still in the database.
 */
export type ParsedWire =
  | { kind: "profession"; int: number }
  | { kind: "elite"; int: number }
  | { kind: "unknown"; int: 0 };

// Legacy wire format regex (pre-v0.16.2-api: "PROF(1)", "ELITE(27)").
const WIRE_RE = /^(PROF|ELITE)\((\d+)\)$/;

// Canonical profession name → int (mirrors gw2_core.Profession).
const PROFESSION_NAME_TO_INT: Record<string, number> = {
  Guardian: 1,
  Warrior: 2,
  Engineer: 3,
  Ranger: 4,
  Thief: 5,
  Elementalist: 6,
  Mesmer: 7,
  Necromancer: 8,
  Revenant: 9,
};

// Canonical elite-spec name → int (mirrors gw2_core.EliteSpec with
// API-correct IDs. v0.16.3-api: all IDs match the GW2 v2 API).
const ELITE_NAME_TO_INT: Record<string, number> = {
  Druid: 5,
  Daredevil: 7,
  Berserker: 18,
  Dragonhunter: 27,
  Reaper: 34,
  Chronomancer: 40,
  Scrapper: 43,
  Tempest: 48,
  Herald: 52,
  Soulbeast: 55,
  Weaver: 56,
  Holosmith: 57,
  Deadeye: 58,
  Mirage: 59,
  Scourge: 60,
  Spellbreaker: 61,
  Firebrand: 62,
  Renegade: 63,
  Harbinger: 64,
  Willbender: 65,
  Virtuoso: 66,
  Catalyst: 67,
  Bladesworn: 68,
  Vindicator: 69,
  Mechanist: 70,
  Specter: 71,
  Untamed: 72,
  Troubadour: 73,
  Paragon: 74,
  Amalgam: 75,
  Ritualist: 76,
  Antiquary: 77,
  Galeshot: 78,
  Conduit: 79,
  Evoker: 80,
  Luminary: 81,
};

export function parseWireFormat(wire: string | null | undefined): ParsedWire | null {
  if (typeof wire !== "string") return null;
  if (wire === "UNKNOWN") return { kind: "unknown", int: 0 };
  if (wire === "BASE") return { kind: "elite", int: 0 };

  // 1. Try canonical name-based format (current API).
  const profInt = PROFESSION_NAME_TO_INT[wire];
  if (profInt !== undefined) return { kind: "profession", int: profInt };
  const eliteInt = ELITE_NAME_TO_INT[wire];
  if (eliteInt !== undefined) return { kind: "elite", int: eliteInt };

  // 2. Fall back to legacy "PROF(N)" / "ELITE(N)" format.
  const m = WIRE_RE.exec(wire);
  if (!m) return null;
  const [, prefix, intStr] = m;
  const int = Number.parseInt(intStr, 10);
  if (!Number.isFinite(int) || int < 0) return null;
  return { kind: prefix === "PROF" ? "profession" : "elite", int };
}

/* ------------------------------------------------------------------ *
 *  Profession icon table (1D, no conflicts)
 * ------------------------------------------------------------------ */

/**
 * int → icon URL for the 9 base professions. Mirrors the
 * ``Profession`` IntEnum in ``libs/gw2_core/src/gw2_core/models.py``.
 * Includes ``UNKNOWN → null`` (int 0 is the no-profession sentinel;
 * the wire emits ``"UNKNOWN"`` for it which the lookup returns no
 * icon — the cell renders the data-testid fallback span).
 */
const PROFESSION_ICONS_BY_INT: Record<number, string> = {
  1: "/icons/professions/Guardian_tango.png",
  2: "/icons/professions/Warrior_tango.png",
  3: "/icons/professions/Engineer_tango.png",
  4: "/icons/professions/Ranger_tango.png",
  5: "/icons/professions/Thief_tango.png",
  6: "/icons/professions/Elementalist_tango.png",
  7: "/icons/professions/Mesmer_tango.png",
  8: "/icons/professions/Necromancer_tango.png",
  9: "/icons/professions/Revenant_tango.png",
};

/* ------------------------------------------------------------------ *
 *  Elite icon table (1D flat for unique ints + 2D context for conflicts)
 * ------------------------------------------------------------------ */

/**
 * int → icon URL for UNIQUE elite ints (no conflict). Mirrors
 * the ``EliteSpec`` IntEnum in ``libs/gw2_core/src/gw2_core/models.py``.
 *
 * The TWO conflicting ints (55 + 63) are DELIBERATELY omitted here
 * so the 2D ``ELITE_ICONS_BY_INT_AND_PROFESSION`` map is the
 * SINGLE source of truth for those cases.
 */
// v0.16.3-api: all IDs match the GW2 v2 API (mirrors
// libs/gw2_core/gw2_core/models.py EliteSpec IntEnum).
const ELITE_ICONS_BY_INT: Record<number, string> = {
  5: "/icons/specializations/Druid_tango.png",
  7: "/icons/specializations/Daredevil_tango.png",
  18: "/icons/specializations/Berserker_tango.png",
  27: "/icons/specializations/Dragonhunter_tango.png",
  34: "/icons/specializations/Reaper_tango.png",
  40: "/icons/specializations/Chronomancer_tango.png",
  43: "/icons/specializations/Scrapper_tango.png",
  48: "/icons/specializations/Tempest_tango.png",
  52: "/icons/specializations/Herald_tango.png",
  56: "/icons/specializations/Weaver_tango.png",
  57: "/icons/specializations/Holosmith_tango.png",
  58: "/icons/specializations/Deadeye_tango.png",
  59: "/icons/specializations/Mirage_tango.png",
  60: "/icons/specializations/Scourge_tango.png",
  61: "/icons/specializations/Spellbreaker_tango.png",
  62: "/icons/specializations/Firebrand_tango.png",
  64: "/icons/specializations/Harbinger_tango.png",
  65: "/icons/specializations/Willbender_tango.png",
  66: "/icons/specializations/Virtuoso_tango.png",
  67: "/icons/specializations/Catalyst_tango.png",
  68: "/icons/specializations/Bladesworn_tango.png",
  69: "/icons/specializations/Vindicator_tango.png",
  70: "/icons/specializations/Mechanist_tango.png",
  71: "/icons/specializations/Specter_tango.png",
  72: "/icons/specializations/Untamed_tango.png",
  73: "/icons/specializations/Troubadour_tango.png",
  74: "/icons/specializations/Paragon_tango.png",
  75: "/icons/specializations/Amalgam_tango.png",
  76: "/icons/specializations/Ritualist_tango.png",
  77: "/icons/specializations/Antiquary_tango.png",
  78: "/icons/specializations/Galeshot_tango.png",
  79: "/icons/specializations/Conduit_tango.png",
  80: "/icons/specializations/Evoker_tango.png",
  81: "/icons/specializations/Luminary_tango.png",
};

/**
 * int → (profession int → icon URL) for CONFLICTING elite ints.
 * The flat table omits these so the 2D map is the single source.
 *
 * Conflicts:
 * - int=55: SOULBEAST (Ranger=4) ↔ DAREDEVIL (Thief=5)
 * - int=63: WEAVER (Elementalist=6) ↔ RENEGADE (Revenant=9)
 */
const ELITE_ICONS_BY_INT_AND_PROFESSION: Record<number, Partial<Record<number, string>>> = {
  55: {
    4: "/icons/specializations/Soulbeast_tango.png",
    5: "/icons/specializations/Daredevil_tango.png",
  },
  63: {
    6: "/icons/specializations/Weaver_tango.png",
    9: "/icons/specializations/Renegade_tango.png",
  },
};

/* ------------------------------------------------------------------ *
 *  Reverse mapping — int → human-readable label (for `alt` + tooltip)
 * ------------------------------------------------------------------ */

const PROFESSION_LABEL_BY_INT: Record<number, string> = {
  1: "Guardian",
  2: "Warrior",
  3: "Engineer",
  4: "Ranger",
  5: "Thief",
  6: "Elementalist",
  7: "Mesmer",
  8: "Necromancer",
  9: "Revenant",
};

const ELITE_LABEL_BY_INT: Record<number, string> = {
  5: "Druid",
  7: "Daredevil",
  18: "Berserker",
  27: "Dragonhunter",
  34: "Reaper",
  40: "Chronomancer",
  43: "Scrapper",
  48: "Tempest",
  52: "Herald",
  56: "Weaver",
  57: "Holosmith",
  58: "Deadeye",
  59: "Mirage",
  60: "Scourge",
  61: "Spellbreaker",
  62: "Firebrand",
  64: "Harbinger",
  65: "Willbender",
  66: "Virtuoso",
  67: "Catalyst",
  68: "Bladesworn",
  69: "Vindicator",
  70: "Mechanist",
  71: "Specter",
  72: "Untamed",
  73: "Troubadour",
  74: "Paragon",
  75: "Amalgam",
  76: "Ritualist",
  77: "Antiquary",
  78: "Galeshot",
  79: "Conduit",
  80: "Evoker",
  81: "Luminary",
};

const ELITE_LABEL_BY_INT_AND_PROFESSION: Record<number, Partial<Record<number, string>>> = {
  55: {
    4: "Soulbeast",
    5: "Daredevil",
  },
  63: {
    6: "Weaver",
    9: "Renegade",
  },
};

/* ------------------------------------------------------------------ *
 *  Public lookups (exported for tests + future reuse)
 * ------------------------------------------------------------------ */

export function getProfessionIconPath(wire: string | null | undefined): string | null {
  const parsed = parseWireFormat(wire);
  if (!parsed || parsed.kind !== "profession") return null;
  return PROFESSION_ICONS_BY_INT[parsed.int] ?? null;
}

export function getProfessionLabel(wire: string | null | undefined): string | null {
  const parsed = parseWireFormat(wire);
  if (!parsed) return null;
  if (parsed.kind === "profession") return PROFESSION_LABEL_BY_INT[parsed.int] ?? null;
  if (parsed.kind === "unknown") return "Unknown";
  return null;
}

/**
 * Elite-spec icon lookup. ``professionWire`` is the profession
 * wire string (used to disambiguate the int=55 + int=63 conflicts).
 *
 * Returns ``null`` when the elite int has no bundled icon (the
 * Combat-readout cell renderer then displays the empty fallback
 * span with the parsed int as the ``data-icon-fallback`` attribute
 * so a stale bundle is diagnosable in DevTools).
 */
export function getEliteIconPath(
  wire: string | null | undefined,
  professionWire: string | null | undefined,
): string | null {
  const parsed = parseWireFormat(wire);
  if (!parsed || parsed.kind !== "elite") return null;
  if (parsed.int === 0) return null; // "BASE" sentinel — no icon for no-elite
  // Conflict resolution: prefer the profession-scoped map.
  const profParsed = parseWireFormat(professionWire);
  const profInt =
    profParsed && profParsed.kind === "profession" ? profParsed.int : null;
  if (profInt !== null) {
    const override =
      ELITE_ICONS_BY_INT_AND_PROFESSION[parsed.int]?.[profInt];
    if (override) return override;
  }
  // Fall through to the flat map (works for the 21 unique ints).
  return ELITE_ICONS_BY_INT[parsed.int] ?? null;
}

export function getEliteLabel(
  wire: string | null | undefined,
  professionWire: string | null | undefined,
): string | null {
  const parsed = parseWireFormat(wire);
  if (!parsed || parsed.kind !== "elite") return null;
  if (parsed.int === 0) return null; // base sentinel
  const profParsed = parseWireFormat(professionWire);
  const profInt =
    profParsed && profParsed.kind === "profession" ? profParsed.int : null;
  if (profInt !== null) {
    const override =
      ELITE_LABEL_BY_INT_AND_PROFESSION[parsed.int]?.[profInt];
    if (override) return override;
  }
  return ELITE_LABEL_BY_INT[parsed.int] ?? null;
}

/* ------------------------------------------------------------------ *
 *  React components
 * ------------------------------------------------------------------ */

interface IconBaseProps {
  size?: number;
  className?: string;
}

/**
 * Render the Tango icon for a Combat-readout profession wire string.
 *
 * Renders an empty ``data-testid="tango-icon-fallback"`` span when
 * the wire string is unparseable, the profession is the
 * ``UNKNOWN`` sentinel, or a new profession int is unaccounted for
 * in the bundle (forward-compat).
 */
export function ProfessionIcon({
  wire,
  size = 24,
  className,
}: { wire: string | null | undefined } & IconBaseProps) {
  const src = getProfessionIconPath(wire);
  const label = getProfessionLabel(wire) ?? wire ?? "unknown profession";
  return (
    <TangoImage
      src={src}
      alt={label}
      size={size}
      className={className}
      dataFallback={wire ?? ""}
    />
  );
}

/**
 * Render the Tango icon for a Combat-readout elite-spec wire string.
 *
 * The ``professionWire`` prop disambiguates the int=55 (Soulbeast
 * vs Daredevil) + int=63 (Weaver vs Renegade) conflicts; pass the
 * row's profession wire string from the cell renderer.
 */
export function EliteSpecIcon({
  wire,
  professionWire,
  size = 24,
  className,
}: {
  wire: string | null | undefined;
  professionWire: string | null | undefined;
} & IconBaseProps) {
  const src = getEliteIconPath(wire, professionWire);
  const label = getEliteLabel(wire, professionWire) ?? wire ?? "unknown elite";
  return (
    <TangoImage
      src={src}
      alt={label}
      size={size}
      className={className}
      dataFallback={wire ?? ""}
    />
  );
}

function TangoImage({
  src,
  alt,
  size,
  className,
  dataFallback,
}: {
  src: string | null;
  alt: string;
  size: number;
  className?: string;
  dataFallback: string;
}) {
  if (!src) {
    // Empty fallback span — preserves AG Grid cell layout for rows
    // whose profession/spec wire value is unrecognized (forward-compat
    // for future EliteSpec additions, or a stale icon bundle).
    return (
      <span
        data-testid="tango-icon-fallback"
        data-icon-fallback={dataFallback}
        title={alt}
        style={{ display: "inline-block", width: size, height: size }}
      />
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      className={className}
      data-testid="tango-icon"
      data-tango-icon={alt}
      style={{ display: "inline-block", verticalAlign: "middle" }}
    />
  );
}
