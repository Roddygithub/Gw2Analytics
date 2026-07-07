"use client";

/**
 * Inline SVG line chart for the per-account historical timeline.
 *
 * Visualises the same :class:`PlayerTimelinePoint` rows the
 * :class:`PlayerTimelineTable` (future) would render, but as
 * 3 stacked line series (damage + healing + buff-removal) so
 * the analyst can spot a per-account trend at a glance.
 *
 * Why normalise each series to its OWN max (0-100% of series max)
 * ==============================================================
 * If the 3 series shared an absolute Y axis, damage (often
 * 10k-100k magnitude) would visually crush buff-removal
 * (often 0-500 magnitude) into a flat line and the strip
 * trend would be invisible. By computing
 * ``y_damage = value / max_damage`` (and likewise for
 * healing + strip), the analyst can compare the *trends* of
 * all 3 simultaneously even when their magnitudes differ by
 * two orders of magnitude. The "showing N of M" caption on
 * the parent section surfaces the absolute totals.
 *
 * Why inline SVG (vs a charting library)
 * ======================================
 * The point count is bounded by the route's ``limit`` (max
 * 100) and the data shape is trivially rectangular. A
 * charting library (recharts / visx / chart.js) would add
 * ~50-150 KB to the bundle for features we don't need
 * (axes legends, tooltips, animation timelines, responsive
 * resize handlers). A 150-line SVG component renders the
 * same shape with zero deps -- the same tradeoff the
 * :class:`EventWindowsChart` makes.
 *
 * X-axis: ``MM/DD HH:MM`` of ``started_at`` via
 * :class:`Intl.DateTimeFormat`. The leftmost + rightmost
 * labels are always drawn; intermediate labels are sampled
 * to keep the axis uncluttered (one label per ~120px).
 *
 * Empty / single-point handling
 * =============================
 * - zero points -> empty-state panel mirroring the
 *   :class:`EventWindowsChart` styling.
 * - single point -> the chart renders a single vertical
 *   hairline at the X midpoint (the polyline collapses to a
 *   degenerate segment but the y-axis labels still show).
 * - all-zero points for a given series -> that series
 *   collapses to a flat baseline at y=0. The other series
 *   still draw; the legend still lists all 3.
 */

import { useMemo } from "react";
import type { PlayerTimelinePoint } from "@/lib/api";
import { PlayerTimelineLegend } from "@/components/PlayerTimelineLegend";

const CHART_WIDTH = 720;
const CHART_HEIGHT = 220;
const CHART_PADDING = { top: 16, right: 16, bottom: 36, left: 48 };
const POINT_RADIUS_PX = 3;
const X_LABEL_SAMPLE_PX = 120;
const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const DAMAGE_STROKE = "var(--accent)";
const HEALING_STROKE = "var(--foreground)";
const STRIP_STROKE = "#f59e0b"; // warm orange; matches the per-target strip roll-up

const X_AXIS_LABEL_FORMAT = new Intl.DateTimeFormat(undefined, {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/**
 * Pure helper exported for the unit test (snapshot the layout
 * without rendering). Returns the per-series max + the X
 * positions for each point (1:1 with the input). The caller
 * draws the polylines + dots.
 */
export function buildTimelineLayout(points: PlayerTimelinePoint[]) {
  if (points.length === 0) {
    return null;
  }
  const maxDamage = Math.max(1, ...points.map((p) => p.total_damage));
  const maxHealing = Math.max(1, ...points.map((p) => p.total_healing));
  const maxStrip = Math.max(1, ...points.map((p) => p.total_buff_removal));
  const innerW =
    CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const innerH =
    CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
  // 1 point -> mid-X; N points -> even spread across innerW
  const xFor = (i: number) =>
    points.length === 1
      ? innerW / 2
      : (innerW * i) / (points.length - 1);
  const yFor = (v: number, max: number) => innerH * (1 - v / max);
  return {
    maxDamage,
    maxHealing,
    maxStrip,
    innerW,
    innerH,
    xFor,
    yFor,
  };
}

export function PlayerTimelineChart({
  points,
}: {
  points: PlayerTimelinePoint[];
}) {
  const layout = useMemo(() => buildTimelineLayout(points), [points]);

  if (points.length === 0 || !layout) {
    return <div style={EMPTY_STYLE}>No timeline data available.</div>;
  }

  const { maxDamage, maxHealing, maxStrip, innerW, innerH, xFor, yFor } =
    layout;

  // Build the polyline ``d`` strings: one ``M`` + N ``L``s.
  const buildD = (values: number[], max: number): string =>
    values
      .map((v, i) => `${i === 0 ? "M" : "L"}${xFor(i).toFixed(2)},${yFor(v, max).toFixed(2)}`)
      .join(" ");

  const damageD = buildD(
    points.map((p) => p.total_damage),
    maxDamage,
  );
  const healingD = buildD(
    points.map((p) => p.total_healing),
    maxHealing,
  );
  const stripD = buildD(
    points.map((p) => p.total_buff_removal),
    maxStrip,
  );

  // X-axis label sampling: first + last always drawn; others
  // at roughly one-label-per-X_LABEL_SAMPLE_PX intervals. The
  // sampling keeps the axis legible for long timelines
  // (limit=100) without forcing the analyst to render 100
  // text elements.
  const labelStep = Math.max(1, Math.ceil(X_LABEL_SAMPLE_PX / (innerW / Math.max(1, points.length))));
  const xLabelIndices = new Set<number>([0, points.length - 1]);
  for (let i = 0; i < points.length; i += labelStep) {
    xLabelIndices.add(i);
  }

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid var(--border)",
        borderRadius: 4,
        background: "var(--surface)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span
          style={{
            fontSize: 13,
            opacity: 0.7,
            fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
          }}
        >
          Per-fight trend (normalized per series)
        </span>
        <PlayerTimelineLegend />
      </div>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        width="100%"
        style={{ display: "block" }}
        role="img"
        aria-label="Per-account historical timeline"
      >
        <g
          transform={`translate(${CHART_PADDING.left}, ${CHART_PADDING.top})`}
        >
          {/* Y-axis baseline + max tick (single set, since 3 series share a 0-100% scale) */}
          <line x1={0} y1={innerH} x2={innerW} y2={innerH} stroke="var(--border)" />
          <line x1={0} y1={0} x2={0} y2={innerH} stroke="var(--border)" />
          <text
            x={-8}
            y={0}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize={10}
            fill="var(--foreground)"
            opacity={0.7}
          >
            100%
          </text>
          <text
            x={-8}
            y={innerH}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize={10}
            fill="var(--foreground)"
            opacity={0.7}
          >
            0
          </text>

          {/* 3 polylines: damage (accent), healing (foreground @ 0.7), strip (warm orange) */}
          <path
            d={damageD}
            fill="none"
            stroke={DAMAGE_STROKE}
            strokeWidth={1.5}
          />
          <path
            d={healingD}
            fill="none"
            stroke={HEALING_STROKE}
            strokeWidth={1.5}
            opacity={0.7}
          />
          <path
            d={stripD}
            fill="none"
            stroke={STRIP_STROKE}
            strokeWidth={1.5}
          />

          {/* Per-point dots, one set per series. ``fight_id`` is the canonical key. */}
          {points.map((p, i) => (
            <g key={p.fight_id}>
              {/* Per-group ``<title>`` surfaces the absolute
                  values on hover for ANY of the 3 sibling
                  dots (the y-axis is normalized to 0-100%
                  per series, so the raw magnitudes are
                  otherwise invisible). SVG ``<title>`` is
                  the canonical lightweight tooltip -- no
                  React state, no portal, no client-side
                  JS. The browser shows it as a native
                  tooltip on hover/focus. */}
              <title>
                {`${p.fight_id} · ${X_AXIS_LABEL_FORMAT.format(new Date(p.started_at))}\n`}
                {`Damage: ${p.total_damage.toLocaleString()}\n`}
                {`Healing: ${p.total_healing.toLocaleString()}\n`}
                {`Strip: ${p.total_buff_removal.toLocaleString()}`}
              </title>
              <circle
                cx={xFor(i)}
                cy={yFor(p.total_damage, maxDamage)}
                r={POINT_RADIUS_PX}
                fill={DAMAGE_STROKE}
              />
              <circle
                cx={xFor(i)}
                cy={yFor(p.total_healing, maxHealing)}
                r={POINT_RADIUS_PX}
                fill={HEALING_STROKE}
                opacity={0.7}
              />
              <circle
                cx={xFor(i)}
                cy={yFor(p.total_buff_removal, maxStrip)}
                r={POINT_RADIUS_PX}
                fill={STRIP_STROKE}
              />
            </g>
          ))}

          {/* X-axis labels: first + last always; intermediate sampled by labelStep */}
          {[...xLabelIndices].sort((a, b) => a - b).map((i) => {
            const p = points[i];
            return (
              <text
                key={`x-${p.fight_id}`}
                x={xFor(i)}
                y={innerH + 16}
                textAnchor="middle"
                fontSize={9}
                fill="var(--foreground)"
                opacity={0.6}
              >
                {X_AXIS_LABEL_FORMAT.format(new Date(p.started_at))}
              </text>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
