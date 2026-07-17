/**
 * Shared formatting helpers for the web frontend.
 *
 * These utilities are intentionally tiny and presentation-only;
 * they live in ``lib/`` so multiple components can share the same
 * formatting contract without importing across component modules.
 */

/**
 * Format a millisecond offset as a ``M:SS`` label.
 *
 * ``window_start_ms=0`` -> ``"0:00"`` (the fight-start bucket).
 * ``window_start_ms=65000`` -> ``"1:05"`` (1 min 5 sec into the
 * fight). The 2-digit zero-padding on seconds keeps the axis labels
 * aligned vertically (without the pad, a ``"0:5"`` label would shift
 * the ``"0:15"`` label to the right by 1 character width and break
 * the X-axis tick alignment).
 */
export function formatSecondsLabel(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}
