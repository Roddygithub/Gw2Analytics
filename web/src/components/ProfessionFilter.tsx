"use client";

/**
 * Client Component for the v0.9.0 ``?profession=`` filter on
 * ``/players``.
 *
 * Why a Client Component
 * ======================
 * The filter mutates the URL (``/players?profession=MESMER``)
 * which requires the Next.js client-side router APIs
 * (``useRouter`` + ``useSearchParams``). The surrounding
 * ``/players`` page is a Server Component; the filter is the
 * only client-side island on the page.
 *
 * Why a hardcoded option list (not an API call)
 * ==============================================
 * The Profession enum is stable (libs/gw2_core/src/gw2_core/
 * models.py): 9 base professions (GUARDIAN / WARRIOR / ENGINEER
 * / RANGER / THIEF / ELEMENTALIST / MESMER / NECROMANCER /
 * REVENANT) + an UNKNOWN sentinel. A hardcoded list avoids the
 * round-trip + the render-flash of an empty <select> on first
 * load. The labels are title-cased for the analyst-facing
 * surface (e.g. ``"Mesmer"`` not ``"MESMER"``); the URL value
 * stays uppercase to match the wire enum.
 *
 * URL contract
 * ============
 * - Selecting a profession sets ``?profession=<NAME>`` and
 *   navigates to the new URL (``router.push``).
 * - Selecting "All professions" removes the param.
 * - The pre-selected value comes from the parent's
 *   ``searchParams.profession`` (the Server Component reads
 *   the URL + passes the value as a prop). This avoids a
 *   duplicate read from ``useSearchParams`` (the Server
 *   Component is the single source of truth for the URL
 *   state).
 */
import { useRouter, useSearchParams } from "next/navigation";
import { LABEL_STYLE, SELECT_STYLE } from "@/shared/styles";
import React from "react";

interface ProfessionOption {
  /** Enum name (uppercase, e.g. ``"MESMER"``); the URL value. */
  value: string;
  /** Title-cased display label (e.g. ``"Mesmer"``). */
  label: string;
}

const PROFESSION_OPTIONS: readonly ProfessionOption[] = [
  { value: "GUARDIAN", label: "Guardian" },
  { value: "WARRIOR", label: "Warrior" },
  { value: "ENGINEER", label: "Engineer" },
  { value: "RANGER", label: "Ranger" },
  { value: "THIEF", label: "Thief" },
  { value: "ELEMENTALIST", label: "Elementalist" },
  { value: "MESMER", label: "Mesmer" },
  { value: "NECROMANCER", label: "Necromancer" },
  { value: "REVENANT", label: "Revenant" },
];

const PROFESSION_SELECT_STYLE: React.CSSProperties = {
  ...SELECT_STYLE,
  padding: "6px 10px",
  fontSize: 14,
  background: "var(--bg-elev)",
  color: "inherit",
  border: "1px solid var(--border)",
};

function ProfessionFilterComponent({
  currentValue,
}: {
  /**
   * The current profession filter from the URL
   * (``searchParams.profession``). ``undefined`` when the
   * URL has no filter (the "All professions" option is
   * pre-selected in that case).
   */
  currentValue?: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newValue = e.target.value;
    // ``new URLSearchParams(searchParams.toString())`` is a
    // defensive copy so we don't mutate the read-only
    // ``searchParams`` returned by Next.js. ``toString()``
    // materialises the current state into a mutable copy.
    const params = new URLSearchParams(searchParams.toString());
    if (newValue) {
      params.set("profession", newValue);
    } else {
      params.delete("profession");
    }
    const qs = params.toString();
    router.push(`/players${qs ? `?${qs}` : ""}`);
  };

  return (
    <label style={LABEL_STYLE}>
      Filter by profession:
      <select
        data-testid="profession-filter"
        aria-label="Filter players by profession"
        value={currentValue ?? ""}
        onChange={handleChange}
        style={PROFESSION_SELECT_STYLE}
      >
        <option value="">All professions</option>
        {PROFESSION_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export const ProfessionFilter = React.memo(ProfessionFilterComponent);
