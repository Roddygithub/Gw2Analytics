/**
 * Shared profession colour palette for GW2Analytics.
 *
 * v0.14.3 Phase H: extracted from PlayerPositionHeatmap.tsx so the
 * palette can be reused by any component that needs per-profession
 * colour-coding (position heatmaps, timeline overlays, replay
 * player indicators, etc.).
 *
 * Colours are chosen for maximum contrast on dark backgrounds
 * (the app's dark-mode-first palette) and are loosely based on
 * the official GW2 profession colour themes.
 */

export const PROFESSION_COLORS: Record<string, string> = {
  Guardian: "#72C1D9",
  Warrior: "#FFD166",
  Engineer: "#D09B2C",
  Ranger: "#8CD13C",
  Thief: "#C08F95",
  Elementalist: "#F68A87",
  Mesmer: "#B679D2",
  Necromancer: "#52A76F",
  Revenant: "#D16E5A",
};

export const FALLBACK_COLOR = "#888888";

/** Resolve a profession name to its canonical colour. */
export function professionColor(profession: string): string {
  return PROFESSION_COLORS[profession] ?? FALLBACK_COLOR;
}
