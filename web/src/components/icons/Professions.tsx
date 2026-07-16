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
 * - ``kind='profession'`` matches ``"PROF(N)"`` for N ∈ {1..9}.
 * - ``kind='elite'`` matches ``"ELITE(N)"`` for any non-negative integer.
 * - ``kind='unknown'`` matches ``"UNKNOWN"`` (profession 0 sentinel)
 *   OR ``"BASE"`` (elite 0 sentinel — represented as elite:int=0).
 * - ``null`` is returned for any string that fails the wire contract
 *   (Phase 6 v2 SCAFFOLD-zero or a future contract widening).
 */
export type ParsedWire =
  | { kind: "profession"; int: number }
  | { kind: "elite"; int: number }
  | { kind: "unknown"; int: 0 };

const WIRE_RE = /^(PROF|ELITE)\((\d+)\)$/;

export function parseWireFormat(wire: string | null | undefined): ParsedWire | null {
  if (typeof wire !== "string") return null;
  if (wire === "UNKNOWN") return { kind: "unknown", int: 0 };
  if (wire === "BASE") return { kind: "elite", int: 0 };
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
const ELITE_ICONS_BY_INT: Record<number, string> = {
  5: "/icons/specializations/Druid_tango.png",
  18: "/icons/specializations/Berserker_tango.png",
  27: "/icons/specializations/Dragonhunter_tango.png",
  34: "/icons/specializations/Reaper_tango.png",
  40: "/icons/specializations/Chronomancer_tango.png",
  43: "/icons/specializations/Scrapper_tango.png",
  48: "/icons/specializations/Tempest_tango.png",
  52: "/icons/specializations/Herald_tango.png",
  57: "/icons/specializations/Holosmith_tango.png",
  59: "/icons/specializations/Mirage_tango.png",
  60: "/icons/specializations/Scourge_tango.png",
  62: "/icons/specializations/Firebrand_tango.png",
  64: "/icons/specializations/Spellbreaker_tango.png",
  65: "/icons/specializations/Willbender_tango.png",
  68: "/icons/specializations/Vindicator_tango.png",
  70: "/icons/specializations/Mechanist_tango.png",
  71: "/icons/specializations/Deadeye_tango.png",
  72: "/icons/specializations/Specter_tango.png",
  73: "/icons/specializations/Untamed_tango.png",
  74: "/icons/specializations/Virtuoso_tango.png",
  75: "/icons/specializations/Catalyst_tango.png",
  77: "/icons/specializations/Harbinger_tango.png",
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
  18: "Berserker",
  27: "Dragonhunter",
  34: "Reaper",
  40: "Chronomancer",
  43: "Scrapper",
  48: "Tempest",
  52: "Herald",
  57: "Holosmith",
  59: "Mirage",
  60: "Scourge",
  62: "Firebrand",
  64: "Spellbreaker",
  65: "Willbender",
  68: "Vindicator",
  70: "Mechanist",
  71: "Deadeye",
  72: "Specter",
  73: "Untamed",
  74: "Virtuoso",
  75: "Catalyst",
  77: "Harbinger",
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
