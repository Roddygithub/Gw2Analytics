"use client";

/**
 * Phase 8 v2 of web: URL-driven per-target filter for the
 * ``/fights/[id]`` drill-down page.
 *
 * Lets the analyst filter all three roll-up tables (DPS / healing /
 * buff-removal) down to a single target_agent_id without re-uploading
 * the combat log. The filter is a dropdown of unique target ids
 * sourced from the union of the three roll-up row arrays; picking
 * a target emits ``?target=N`` and the Server Component filters
 * the rows server-side so the next render is a fully-populated
 * page (no client-side cascade).
 *
 * Why a dropdown of unique target ids
 * ====================================
 * The roll-up tables key on ``target_agent_id`` (a uint64 arcdps
 * pointer-sized id) which is opaque to the analyst without a
 * player-name lookup. A dropdown of just the ids that appear in
 * the data is the smallest viable affordance: the analyst can
 * tell at a glance which targets had non-zero damage / healing /
 * buff-removal contribution, then pick one to drill into.
 *
 * Why a NAMED export (not default)
 * ================================
 * Mirrors the existing component-mock contract in
 * :file:`web/tests/setup.ts` -- the test setup stubs every
 * component used by the page as a no-op NAMED export.
 *
 * Why a single filter (vs per-kind filters)
 * =========================================
 * The three roll-ups are independent aggregations on the same
 * underlying event stream; an analyst drilling into "what did
 * agent 42 contribute?" expects to see the damage + healing +
 * strip picture for that ONE target side-by-side. A single
 * filter keeps the cross-roll-up comparison clean.
 *
 * Why ``router.push`` (not ``router.replace``)
 * ===========================================
 * Mirrors :class:`WindowSizeSelector`: ``push`` adds a new
 * history entry so the analyst can back-button through the
 * targets they tried. The page is ``force-dynamic`` +
 * ``cache: "no-store"`` so the history bloat is negligible.
 */

import { useRouter, usePathname, useSearchParams } from "next/navigation";

export interface TargetFilterProps {
  /** Unique target_agent_ids present in the combined roll-up data. */
  availableTargets: readonly number[];
  /** Currently active target filter (``null`` means "all targets"). */
  current: number | null;
  /** Fight id (used as a fallback if ``usePathname`` returns null). */
  fightId: string;
}

/**
 * Renders a ``<select>`` with an "All targets" entry followed by
 * one entry per ``availableTargets`` id. When the user picks a
 * target, the URL is rewritten to include ``?target=N`` (or the
 * param is dropped for "All targets"). The Server Component reads
 * the param back via Next.js 15+ ``searchParams`` and filters the
 * three roll-up tables.
 */
export function TargetFilter({
  availableTargets,
  current,
  fightId,
}: TargetFilterProps) {
  const router = useRouter();
  const pathname = usePathname() ?? `/fights/${fightId}`;
  // Snapshot the other search params so we preserve ``?window_s=``
  // (and any future params) when rewriting the target param.
  const existingParams = useSearchParams();

  const buildUrl = (target: number | null): string => {
    const params = new URLSearchParams(existingParams.toString());
    if (target === null) {
      params.delete("target");
    } else {
      params.set("target", String(target));
    }
    const qs = params.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  };

  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        fontSize: 14,
        color: "var(--foreground)",
        opacity: 0.85,
      }}
    >
      <span>Target:</span>
      <select
        data-testid="target-filter"
        value={current === null ? "" : String(current)}
        onChange={(e) => {
          const value = e.target.value;
          router.push(buildUrl(value === "" ? null : Number(value)));
        }}
        style={{
          padding: "4px 8px",
          background: "var(--background)",
          color: "var(--foreground)",
          border: "1px solid var(--border)",
          borderRadius: 4,
          fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
          fontSize: 14,
        }}
      >
        <option value="">All targets</option>
        {availableTargets.map((tid) => (
          <option key={tid} value={tid}>
            {tid}
          </option>
        ))}
      </select>
    </label>
  );
}
