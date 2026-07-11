"use client";

/**
 * Phase 7 v2 of web: URL-driven ``window_s`` selector for the
 * ``/fights/[id]`` drill-down page.
 *
 * The gateway's ``GET /api/v1/fights/{fight_id}/events?window_s=N``
 * accepts ``window_s in [1, 600]``; the page hardcoded the default
 * 5s in Phase 7 v1. This selector lets the analyst change the
 * bucket size on the fly without re-uploading the combat log.
 *
 * Why a dropdown of preset values
 * ===============================
 * The gateway's Pydantic ``Query(ge=1, le=600)`` validator rejects
 * out-of-range ``window_s`` with a 422; surfacing a free-form
 * number input would require the page to either pre-validate the
 * value client-side (added complexity for marginal benefit) or to
 * render the 422 error from the upstream. Preset values cover the
 * common analyst use cases:
 *   - 1s   -- per-second (very fine-grained; per-fight ~30 buckets
 *     on a 30s fight)
 *   - 5s   -- gateway default + standard GW2 toolchain bucketing
 *   - 30s  -- per-encounter
 *   - 60s  -- per-minute
 *   - 300s -- per-5-min (very coarse)
 *
 * Why a NAMED export (not default)
 * ================================
 * Mirrors the existing component-mock contract in
 * :file:`web/tests/setup.ts` -- the test setup stubs every
 * component used by the page as a no-op NAMED export. Default
 * exports would force a different mock shape.
 *
 * Why ``usePathname`` (not a hardcoded ``/fights`` prefix)
 * ========================================================
 * The selector doesn't know which page it lives on; it just needs
 * to preserve the current path and rewrite the query. The
 * Server Component that owns the page passes ``fightId`` so the
 * full URL can be reconstructed if ``usePathname`` ever returns
 * ``null`` (which it can during the first server-render tick
 * before the client router has hydrated; in practice the
 * dropdown is only interactive after hydration anyway).
 *
 * Why ``router.push`` (not ``router.replace``)
 * ===========================================
 * ``router.push`` adds a new entry to the browser history so the
 * analyst can back-button through the bucket sizes they tried.
 * The roll-up URL is cheap to re-render (the page is
 * ``force-dynamic`` + ``cache: "no-store"``), so the history
 * bloat is negligible.
 */

import { useRouter, usePathname, useSearchParams } from "next/navigation";

/**
 * The canonical preset list. Module-scope constant so the
 * component's render doesn't re-allocate the array on every
 * change event.
 */
export const WINDOW_S_PRESETS: readonly number[] = [1, 5, 30, 60, 300] as const;

export interface WindowSizeSelectorProps {
  /** Current window_s value (must be one of ``WINDOW_S_PRESETS``). */
  current: number;
  /** Fight id (used as a fallback if ``usePathname`` returns null). */
  fightId: string;
}

export function WindowSizeSelector({ current, fightId }: WindowSizeSelectorProps) {
  const router = useRouter();
  const pathname = usePathname() ?? `/fights/${fightId}`;
  const searchParams = useSearchParams();

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
      <span>Window (s):</span>
      <select
        data-testid="window-s-selector"
        value={current}
        onChange={(e) => {
          const value = e.target.value;
          const next = new URLSearchParams(searchParams.toString());
          if (value === String(WINDOW_S_PRESETS[1])) {
            next.delete("window_s");
          } else {
            next.set("window_s", value);
          }
          const queryString = next.toString();
          const url = queryString ? `${pathname}?${queryString}` : pathname;
          router.push(url);
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
        {WINDOW_S_PRESETS.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
}
