"use client";

/**
 * F17 W.1 v2 — AG Grid cellRenderer React components for the
 * "Spécialisation" + "Cmdr" identifier columns shared by all 4
 * per-aspect tables.
 *
 * Wire-format alignment note
 * =========================
 * Per F17 W.1 v2 the icon library now consumes the Combat-readout
 * wire format (``"PROF(N)"`` / ``"ELITE(N)"`` / ``"UNKNOWN"`` /
 * ``"BASE"``) directly via the int-lookup tables in
 * ``@/components/icons/Professions``. The cell renderer
 * passes BOTH ``row.profession`` AND ``row.elite_spec`` to
 * :component:`EliteSpecIcon` so the int=55 (Soulbeast vs
 * Daredevil) + int=63 (Weaver vs Renegade) conflict resolution
 * has all the context it needs.
 *
 * The previous v1 passed raw TitleCase / UPPER strings which
 * could NEVER match the wire-format (``format_profession`` /
 * ``format_elite_spec`` emit ``f"PROF({v})"`` / ``f"ELITE({v})"``
 * strings from ``apps/api/src/gw2analytics_api/route_helpers.py``)
 * — the cell fell through to the empty fallback span for every
 * row.
 */

import React from "react";

import { CommanderCrown } from "@/components/icons/Commander";
import {
  EliteSpecIcon,
  ProfessionIcon,
  parseWireFormat,
  getEliteLabel,
  getProfessionLabel,
} from "@/components/icons/Professions";
import type { PlayerReadoutOut } from "@/lib/api";

const CELL_GAP = 6;

const cellRowStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: CELL_GAP,
  whiteSpace: "nowrap",
};

/**
 * AG Grid cellRenderer for the ``elite_spec`` column.
 *
 * The cell swaps between:
 * - Elite icon + elite label, when ``row.elite_spec`` resolves to
 *   a bundled int (via the wire-parser in
 *   :module:`@/components/icons/Professions`).
 * - Profession icon + profession label, when ``row.elite_spec``
 *   is the ``"BASE"`` sentinel (no elite) AND ``row.profession``
 *   resolves to a bundled int.
 * - Empty fallback (still shows the wire string verbatim), when
 *   both wire fields are unparseable / future-int unaccounted for.
 */
export function EliteSpecCellRenderer(params: {
  data: PlayerReadoutOut | undefined;
}) {
  const row = params.data;
  if (!row) return null;

  const specWire = row.elite_spec ?? null;
  const professionWire = row.profession ?? null;

  // Parse the elite wire once. null if the wire is missing/the
  // ``string | null | undefined`` sentinel; populated for ``BASE``,
  // ``UNKNOWN``, and ``"PROF(N)"`` / ``"ELITE(N)"`` strings.
  const specParsed =
    typeof specWire === "string" ? parseWireFormat(specWire) : null;
  // Has an active elite (not the "BASE" sentinel)?
  const hasEliteSpec =
    specParsed !== null && specParsed.kind === "elite" && specParsed.int !== 0;

  // Visible label = human-readable name (analyst-friendly, NOT
  // the wire token ``"ELITE(18)"`` / ``"BASE"`` / ``"UNKNOWN"``).
  // The wire string stays in ``data-elite-spec`` for DevTools.
  const label =
    (hasEliteSpec
      ? getEliteLabel(specWire, professionWire)
      : getProfessionLabel(professionWire)) ?? "—";

  if (hasEliteSpec) {
    return (
      <span
        style={cellRowStyle}
        data-testid="elite-spec-cell"
        data-elite-spec={specWire}
      >
        <EliteSpecIcon
          wire={specWire}
          professionWire={professionWire}
          size={20}
        />
        <span>{label}</span>
      </span>
    );
  }
  // No active elite — render the profession icon + label.
  return (
    <span
      style={cellRowStyle}
      data-testid="profession-cell"
      data-elite-spec={specWire ?? ""}
    >
      <ProfessionIcon wire={professionWire} size={20} />
      <span>{label}</span>
    </span>
  );
}

/**
 * AG Grid cellRenderer for the ``is_commander`` column.
 *
 * Renders an inline-SVG CommanderCrown glyph when
 * ``row.is_commander === true``. Non-commander rows render an
 * empty <span data-testid="commander-cell-empty" /> (preserves
 * layout shift when a filter toggles the commander flag).
 *
 * Unaffected by wire format — :attr:`is_commander` is a native
 * bool straight from the API.
 */
export function CommanderCellRenderer(params: {
  data: PlayerReadoutOut | undefined;
}) {
  const row = params.data;
  if (!row || row.is_commander !== true) {
    return <span data-testid="commander-cell-empty" />;
  }
  return (
    <span data-testid="commander-cell-crowned" data-commander="true">
      <CommanderCrown size={18} />
    </span>
  );
}

// The wire parser is imported from @/components/icons/Professions
// (the canonical export). No local duplicate — keeping both in sync
// was the DRY violation caught by the F17 W.1 v2 code-reviewer.
// The `_internal_parseWireForTests` dead-code export was removed
// alongside this consolidation (no consumer).
