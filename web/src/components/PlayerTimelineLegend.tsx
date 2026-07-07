/**
 * Colour legend for the per-account :class:`PlayerTimelineChart`.
 *
 * Three swatches sit on a single row, matching the 3 line
 * series the chart draws:
 *   - Damage    : var(--accent)   (red, the same as the per-target damage bar)
 *   - Healing   : var(--foreground) at 0.7 opacity (the healing bar tint)
 *   - Buff strip: a hard-coded warm orange (no matching CSS var
 *     yet; the per-target strip roll-up uses the same hue so the
 *     legend + the roll-up stay visually consistent across pages)
 *
 * Why a separate component (vs inline in the chart)
 * =================================================
 * The page renders the chart inside a flex column that also hosts
 * the "Load more" button + the "showing N of M" caption; the
 * legend goes on the right of the chart heading, not below the
 * SVG. Splitting it out keeps both layouts free of duplicated
 * swatch markup, and lets the page-level test stub the chart
 * without losing the legend (the v0.7.1 ``EventWindowsChart``
 * pattern: the page test mocks the chart but the legend is
 * always present).
 */

const DAMAGE_FILL = "var(--accent)";
const HEALING_FILL = "var(--foreground)";
const STRIP_FILL = "#f59e0b"; // warm orange; matches the per-target strip roll-up

const LEGEND_WRAPPER_STYLE: React.CSSProperties = {
  display: "flex",
  gap: 16,
  fontSize: 12,
  color: "var(--foreground)",
  opacity: 0.85,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const SWATCH_STYLE: React.CSSProperties = {
  display: "inline-block",
  width: 10,
  height: 10,
  marginRight: 6,
  verticalAlign: "middle",
};

export function PlayerTimelineLegend() {
  return (
    <div style={LEGEND_WRAPPER_STYLE} role="list" aria-label="Timeline legend">
      <span role="listitem">
        <span
          style={{ ...SWATCH_STYLE, background: DAMAGE_FILL }}
          aria-hidden="true"
        />
        Damage
      </span>
      <span role="listitem">
        <span
          style={{ ...SWATCH_STYLE, background: HEALING_FILL, opacity: 0.7 }}
          aria-hidden="true"
        />
        Healing
      </span>
      <span role="listitem">
        <span
          style={{ ...SWATCH_STYLE, background: STRIP_FILL }}
          aria-hidden="true"
        />
        Buff removal
      </span>
    </div>
  );
}
