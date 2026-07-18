/**
 * v0.9.0 plan/001: shared base component for the 3-series
 * SVG line chart that powers BOTH the per-account historical
 * timeline (:class:`PlayerTimelineChart`, v0.8.0) and the
 * per-fight temporal view (:class:`PerFightTimelineChart`,
 * v0.8.9).
 *
 * Why a shared base
 * =================
 * Before v0.9.0 the 2 chart components duplicated ~120 lines of
 * near-identical TSX: the 3 polylines (damage / healing /
 * buff-removal), the per-series 0-100% normalisation, the
 * decade-style X-axis labels, the SVG-native ``<title>``
 * tooltip on the parent ``<g>`` group, the linear/log scale
 * branches, the legend swatches, and the empty-state panel.
 * The v0.8.9 plan/002 entry explicitly deferred this refactor:
 *
 *   "A v0.9.0 refactor could extract a shared
 *    ``<TimelineChart>`` base component; the two components'
 *    data shapes (per-series normalisation, SVG-native
 *    ``<title>`` tooltip, decade-style X-axis labels) are
 *    identical."
 *
 * v0.9.0 plan/001 closes that debt: the 2 wrapper components
 * become thin data-prep shells that delegate the SVG render
 * to this base.
 *
 * Generic over the point shape
 * ============================
 * The base takes a :class:`TimelineChartPoint` array (a flat
 * shape with ``series`` / ``key`` / ``xLabel`` / ``tooltip``)
 * so it can render ANY 3-series temporal data. The 2 wrappers
 * map their native point shape (PlayerTimelinePoint /
 * PerFightTimelinePoint) to the flat shape, including the
 * per-wrapper X-axis label format (``MM/DD HH:MM`` vs
 * ``M:SS``) and the per-wrapper tooltip text. The base has
 * no knowledge of fight ids or bucket windows -- the wrappers
 * own those concerns.
 *
 * Why per-series 0-100% normalisation (linear mode)
 * ==================================================
 * If the 3 series shared an absolute Y axis, damage (often
 * 10k-100k magnitude) would visually crush buff-removal
 * (often 0-500 magnitude) into a flat line and the strip
 * trend would be invisible. By computing
 * ``y_damage = value / max_damage`` (and likewise for
 * healing + strip), the analyst can compare the *trends* of
 * all 3 simultaneously even when their magnitudes differ by
 * two orders of magnitude. The "Showing N of M fights"
 * caption on the parent section surfaces the absolute
 * totals.
 *
 * Why log mode (v0.8.2 lineage)
 * =============================
 * In log mode the 3 polylines share a single Y axis (the
 * global max across all 3 series) and the values are mapped
 * via ``log10(v + 1) / log10(global_max + 1)``. The chart
 * then renders decade labels (0 + 1 + 10 + 100 + 1k + ...)
 * up to the global max, capped at 8 ticks. This is the
 * "damage = 1M dwarfs strip = 50" use case from the v0.8.2
 * ROADMAP -- the linear mode would render the strip at the
 * bottom of the chart (invisible) while the log mode shows
 * both signals on the same axis.
 *
 * Why inline SVG (no charting library)
 * ====================================
 * The point count is bounded by the route's ``limit`` (max
 * 100) and the data shape is trivially rectangular. A
 * charting library (recharts / visx / chart.js) would add
 * ~50-150 KB to the bundle for features we don't need
 * (axes legends, tooltips, animation timelines, responsive
 * resize handlers). A 200-line SVG component renders the
 * same shape with zero deps -- the same tradeoff the
 * pre-existing :class:`EventWindowsChart` makes.
 */

/* eslint-disable react-refresh/only-export-components */
import React from "react";

import { memo, useMemo } from "react";
import { PlayerTimelineLegend } from "@/components/PlayerTimelineLegend";

// ---------------------------------------------------------------------------
// Shared layout constants
// ---------------------------------------------------------------------------

const CHART_WIDTH = 720;
const CHART_HEIGHT = 220;
const CHART_PADDING = { top: 16, right: 16, bottom: 36, left: 48 };
const POINT_RADIUS_PX = 3;
const X_LABEL_SAMPLE_PX = 120;
// v0.8.2: cap on the number of logarithmic Y-axis ticks. The
// 48px left padding can fit ~8 decade labels (1, 10, 100, 1k,
// 10k, 100k, 1M, 10M) before they start overlapping. A global
// max of 1B would otherwise draw 10 ticks (0 + 9 decades) and
// overflow the padding. Extracted to a constant so the cap is
// tunable in one place.
const MAX_LOG_TICKS = 8;

const DAMAGE_STROKE = "var(--accent)";
const HEALING_STROKE = "var(--foreground)";
const STRIP_STROKE = "#f59e0b"; // warm orange; matches the per-target strip roll-up

const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const SECTION_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--surface)",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const HEADER_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
};

const CAPTION_STYLE: React.CSSProperties = {
  fontSize: 13,
  opacity: 0.7,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type TimelineScale = "linear" | "log";

/**
 * The flat point shape consumed by the base component.
 *
 * The 2 wrappers (PlayerTimelineChart + PerFightTimelineChart)
 * map their native point shape to this flat shape, including
 * the per-wrapper X-axis label format (``MM/DD HH:MM`` vs
 * ``M:SS``) and the per-wrapper tooltip text. The base has
 * no knowledge of fight ids or bucket windows.
 */
export interface TimelineChartPoint {
  /**
   * The 3 series values, in [damage, healing, buff-removal]
   * order. The base component does NOT know what the values
   * mean semantically -- it only knows they're 3 polylines
   * with per-series-max normalisation (linear mode) or
   * shared-log (log mode).
   */
  series: [number, number, number];
  /**
   * The React ``key`` for the rendered point group. The
   * wrappers pick the natural identity (fight_id for the
   * per-account timeline, bucket index for the per-fight
   * timeline).
   */
  key: string;
  /**
   * The pre-formatted X-axis label for this point. The
   * wrapper owns the format (``MM/DD HH:MM`` vs ``M:SS``)
   * so the base doesn't need to know about wall-clock vs
   * relative time.
   */
  xLabel: string;
  /**
   * The pre-formatted SVG ``<title>`` tooltip text for this
   * point. Multi-line strings use literal ``\n`` newlines
   * (SVG ``<title>`` honours them). The wrapper picks the
   * text content; the base just renders it.
   */
  tooltip: string;
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for the unit tests)
// ---------------------------------------------------------------------------

/**
 * Compute the layout: per-series maxes, the X positions for
 * each point, the Y mapping, and the Y-axis tick values.
 *
 * Strict parallel of the pre-v0.9.0 ``buildTimelineLayout``
 * + ``buildPerFightTimelineLayout`` helpers (the 2 are
 * structurally identical; the post-v0.9.0 refactor
 * single-sources them here).
 *
 * ``scale`` picks the Y-axis strategy:
 * - ``"linear"`` (default): per-series 0-100% normalisation.
 * - ``"log"``: shared log Y-axis (global max across all 3
 *   series), decade tick values up to the global max.
 *
 * Returns ``null`` for an empty point list -- the base
 * component renders the empty-state panel for ``null``.
 */
// v0.9.0 plan/001: the layout helper is constrained to
// ``{ series: [number, number, number] }`` (NOT the full
// :class:`TimelineChartPoint` shape) because the layout
// calculation only consumes the 3 series values. The
// ``key`` / ``xLabel`` / ``tooltip`` fields are
// React-component concerns (the SVG ``<title>`` tooltip +
// the React ``key`` + the X-axis text label) and the
// layout helper is a pure function of the 3 series values.
// Loosening the constraint to the structural minimum lets
// the unit tests pass a minimal :class:`TimelineChartPoint`
// fixture (just the 3 series numbers + placeholder
// ``key``/``xLabel``/``tooltip``) instead of forcing them
// to build full :class:`PlayerTimelinePoint` /
// :class:`PerFightTimelinePoint` objects and pretend the
// wrapper isn't there.
export function buildTimelineLayout<
  T extends { series: [number, number, number] },
>(
  points: T[],
  scale: TimelineScale = "linear",
) {
  if (points.length === 0) {
    return null;
  }
  let maxDamage = 1;
  let maxHealing = 1;
  let maxStrip = 1;
  for (const p of points) {
    if (p.series[0] > maxDamage) maxDamage = p.series[0];
    if (p.series[1] > maxHealing) maxHealing = p.series[1];
    if (p.series[2] > maxStrip) maxStrip = p.series[2];
  }
  const innerW =
    CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const innerH =
    CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
  // 1 point -> mid-X; N points -> even spread across innerW
  const xFor = (i: number) =>
    points.length === 1
      ? innerW / 2
      : (innerW * i) / (points.length - 1);

  if (scale === "log") {
    // Shared log Y-axis: the global max is the highest value
    // across all 3 series, so the Y-axis is calibrated to
    // the tallest series. The other 2 series render at lower
    // positions on the same axis (visible but below the top).
    const globalMax = Math.max(maxDamage, maxHealing, maxStrip);
    const logMax = Math.log10(globalMax + 1);
    // v0.8.2: the second ``_max`` arg is unused in log mode
    // but the signature is widened to match the linear-mode
    // ``yFor`` so the return type of this function is a
    // single overload rather than a union. Without this,
    // TypeScript widens the return type to the LAST branch
    // (the linear-mode 2-arg signature) and the test's
    // ``yFor(0)`` call (1 arg, log mode) fails the
    // ``TS2554: Expected 2 arguments, but got 1`` check. The
    // result is clamped to ``[0, innerH]`` for the same
    // reason as the linear branch. v0.8.2 also guards
    // against ``NaN`` inputs: a non-finite ``v`` would make
    // ``Math.log10`` return ``NaN``, the ``Math.max`` /
    // ``Math.min`` comparisons return ``false``, and the
    // final result is ``NaN`` -- SVG renders ``NaN`` as a
    // non-finite coordinate and silently drops the point.
    // The ``Number.isFinite`` short-circuit pins the point
    // to the baseline.
    const yFor = (v: number, _max?: number) => {
      if (!Number.isFinite(v)) {
        return innerH;
      }
      return Math.max(
        0,
        Math.min(innerH, innerH * (1 - Math.log10(v + 1) / logMax)),
      );
    };
    // Logarithmic ticks: 0 baseline + each decade up to
    // globalMax. Decades are 1, 10, 100, 1k, 10k, 100k, 1M,
    // 10M, ... up to the ceiling of logMax. We cap the tick
    // count at ``MAX_LOG_TICKS`` (see above) to avoid
    // cluttering the axis for very wide ranges.
    const ticks: number[] = [0];
    const maxExp = Math.ceil(logMax);
    for (let exp = 0; exp <= maxExp && ticks.length < MAX_LOG_TICKS; exp++) {
      const v = Math.pow(10, exp);
      if (v <= globalMax) {
        ticks.push(v);
      }
    }
    return {
      scale,
      maxDamage,
      maxHealing,
      maxStrip,
      globalMax,
      innerW,
      innerH,
      xFor,
      yFor,
      ticks,
    };
  }

  // Linear (per-series normalised) mode: each series is
  // scaled to its own max. ``yFor`` takes the per-series max
  // as the second argument so the caller picks the right
  // denominator per polyline. The ``_max`` arg in the log
  // branch keeps the return type a single overload -- the
  // default of 1 is the all-zero sentinel (``max=1`` after
  // the ``Math.max(1, ...values)`` clamp above), so a
  // missing-arg call from the test or a future caller
  // degrades to the baseline rather than NaN. The result is
  // clamped to ``[0, innerH]`` so a caller that forgets
  // ``max`` (and so divides by the sentinel 1) cannot
  // produce a negative ``y`` that would render ABOVE the
  // chart's top edge -- the canonical SVG silent-bug trap.
  // v0.8.2 also guards against ``NaN`` inputs: a non-finite
  // ``v`` would make the division return ``NaN``, the
  // ``Math.max`` / ``Math.min`` comparisons return
  // ``false``, and the final result is ``NaN`` -- SVG
  // renders ``NaN`` as a non-finite coordinate and
  // silently drops the point. The ``Number.isFinite``
  // short-circuit pins the point to the baseline.
  const yFor = (v: number, max: number = 1) => {
    if (!Number.isFinite(v)) {
      return innerH;
    }
    return Math.max(0, Math.min(innerH, innerH * (1 - v / max)));
  };
  return {
    scale,
    maxDamage,
    maxHealing,
    maxStrip,
    innerW,
    innerH,
    xFor,
    yFor,
    ticks: [0, 1],
  };
}

/**
 * Format a Y-axis tick value for the ``"log"`` scale.
 *
 * - 0 -> ``"0"`` (baseline)
 * - 1 -> ``"1"`` (no suffix)
 * - 1_000 -> ``"1k"``
 * - 1_500 -> ``"1.5k"``
 * - 1_000_000 -> ``"1M"``
 * - 1_500_000 -> ``"1.5M"``
 * - 1_000_000_000 -> ``"1B"`` (v0.8.2 B-suffix)
 *
 * Returns the raw integer string for values < 1000. Compact
 * enough that 8 ticks fit in the 48px left padding without
 * truncation.
 */
export function formatLogTick(v: number): string {
  if (v === 0) return "0";
  if (v < 1000) return v.toString();
  if (v < 1_000_000) {
    const k = v / 1000;
    return k === Math.floor(k) ? `${k}k` : `${k.toFixed(1)}k`;
  }
  if (v < 1_000_000_000) {
    const m = v / 1_000_000;
    return m === Math.floor(m) ? `${m}M` : `${m.toFixed(1)}M`;
  }
  // v0.8.2 of web: B-suffix branch for values >= 1B. Without
  // this, a 1.5B damage renders as ``1500M`` which is
  // technically correct but harder to read at a glance.
  const b = v / 1_000_000_000;
  return b === Math.floor(b) ? `${b}B` : `${b.toFixed(1)}B`;
}

// ---------------------------------------------------------------------------
// Memoized SVG sub-component
// ---------------------------------------------------------------------------

interface PointGeometry {
  key: string;
  tooltip: string;
  x: number;
  damageY: number;
  healingY: number;
  stripY: number;
}

interface TimelineSvgProps {
  ariaLabel: string;
  innerW: number;
  innerH: number;
  isLog: boolean;
  ticks: number[];
  xFor: (i: number) => number;
  yFor: (v: number, max?: number) => number;
  damageD: string;
  healingD: string;
  stripD: string;
  pointGeometry: PointGeometry[];
  xLabelIndices: Set<number>;
  points: TimelineChartPoint[];
}

/**
 * Memoized SVG chart body.
 *
 * Isolating the SVG prevents parent re-renders from diffing
 * the chart's DOM nodes when the underlying data has not
 * changed. The SVG only re-renders when its props change.
 */
const TimelineSvg = memo(function TimelineSvg({
  ariaLabel,
  innerW,
  innerH,
  isLog,
  ticks,
  xFor,
  yFor,
  damageD,
  healingD,
  stripD,
  pointGeometry,
  xLabelIndices,
  points,
}: TimelineSvgProps) {
  return (
    <svg
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      width="100%"
      style={{ display: "block" }}
      role="img"
      aria-label={ariaLabel}
    >
      <g
        transform={`translate(${CHART_PADDING.left}, ${CHART_PADDING.top})`}
      >
        {/* Y-axis baseline + max tick (single set, since 3 series share a 0-100% scale) */}
        <line x1={0} y1={innerH} x2={innerW} y2={innerH} stroke="var(--border)" />
        <line x1={0} y1={0} x2={0} y2={innerH} stroke="var(--border)" />
        {/* v0.8.2 of web: Y-axis labels. In ``"linear"`` mode
            the axis is per-series normalised so the labels
            are ``0`` + ``100%`` (the series max). In
            ``"log"`` mode the axis is shared + logarithmic
            so the labels are decades (``0`` + ``1`` + ``10``
            + ... up to ``globalMax``). */}
        {isLog
          ? ticks.map((tick) => (
              <text
                key={`y-${tick}`}
                x={-8}
                y={yFor(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={10}
                fill="var(--foreground)"
                opacity={0.7}
              >
                {formatLogTick(tick)}
              </text>
            ))
          : (
              <>
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
              </>
            )}

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

        {/* Per-point dots, one set per series. The wrapper
            owns the React ``key`` (fight_id for the
            per-account timeline, bucket index for the
            per-fight timeline) so the base is data-shape
            agnostic. The SVG ``<title>`` tooltip is
            pre-formatted by the wrapper; the base just
            renders the string. A single concatenated
            string is used (NOT multiple template-string
            children) so React receives a single string
            child -- multiple children trigger a hydration
            mismatch and inflate the DOM with
            reconciliation wrappers. */}
        {pointGeometry.map((p) => (
          <g key={p.key}>
            <title>{p.tooltip}</title>
            <circle
              cx={p.x}
              cy={p.damageY}
              r={POINT_RADIUS_PX}
              fill={DAMAGE_STROKE}
            />
            <circle
              cx={p.x}
              cy={p.healingY}
              r={POINT_RADIUS_PX}
              fill={HEALING_STROKE}
              opacity={0.7}
            />
            <circle
              cx={p.x}
              cy={p.stripY}
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
              key={`x-${p.key}`}
              x={xFor(i)}
              y={innerH + 16}
              textAnchor="middle"
              fontSize={9}
              fill="var(--foreground)"
              opacity={0.6}
            >
              {p.xLabel}
            </text>
          );
        })}
      </g>
    </svg>
  );
});

// ---------------------------------------------------------------------------
// The base component
// ---------------------------------------------------------------------------

export function TimelineChart<T extends TimelineChartPoint>({
  points,
  scale = "linear",
  caption,
  ariaLabel = "Timeline chart",
}: {
  points: T[];
  scale?: TimelineScale;
  /** Optional caption shown above the SVG (e.g. "Per-fight trend (normalized per series)"). */
  caption?: string;
  /** The SVG ``aria-label`` for accessibility. */
  ariaLabel?: string;
}) {
  const layout = useMemo(
    () => buildTimelineLayout(points, scale),
    [points, scale],
  );

  // X-axis label sampling: first + last always drawn; others
  // at roughly one-label-per-X_LABEL_SAMPLE_PX intervals. The
  // sampling keeps the axis legible for long timelines
  // (limit=100) without forcing the analyst to render 100
  // text elements. Kept before the early return so the hook
  // call order stays unconditional; the null-layout case
  // returns an empty set.
  const xLabelIndices = useMemo(() => {
    if (!layout) {
      return new Set<number>();
    }
    const { innerW } = layout;
    const labelStep = Math.max(
      1,
      Math.ceil(X_LABEL_SAMPLE_PX / (innerW / Math.max(1, points.length))),
    );
    const indices = new Set<number>([0, points.length - 1]);
    for (let i = 0; i < points.length; i += labelStep) {
      indices.add(i);
    }
    return indices;
  }, [layout, points.length]);

  const { maxDamage, maxHealing, maxStrip, innerW, innerH, xFor, yFor, ticks } =
    layout ?? {
      maxDamage: 1,
      maxHealing: 1,
      maxStrip: 1,
      innerW: 0,
      innerH: 0,
      xFor: () => 0,
      yFor: () => 0,
      ticks: [0, 1],
    };
  const isLog = layout?.scale === "log";

  // Pre-build the 3 polyline path strings and per-point circle
  // coordinates so the SVG render loop does not recompute them
  // on every render (e.g. parent hover re-renders). Kept before
  // the early return so the hook call order stays unconditional.
  const { damageD, healingD, stripD, pointGeometry } = useMemo(() => {
    const buildD = (values: number[], max: number): string =>
      values
        .map(
          (v, i) =>
            `${i === 0 ? "M" : "L"}${xFor(i).toFixed(2)},${yFor(v, max).toFixed(2)}`,
        )
        .join(" ");

    const damageValues = points.map((p) => p.series[0]);
    const healingValues = points.map((p) => p.series[1]);
    const stripValues = points.map((p) => p.series[2]);

    const pointGeometry = points.map((p, i) => ({
      key: p.key,
      tooltip: p.tooltip,
      x: xFor(i),
      damageY: yFor(p.series[0], maxDamage),
      healingY: yFor(p.series[1], maxHealing),
      stripY: yFor(p.series[2], maxStrip),
    }));

    return {
      damageD: buildD(damageValues, maxDamage),
      healingD: buildD(healingValues, maxHealing),
      stripD: buildD(stripValues, maxStrip),
      pointGeometry,
    };
  }, [points, xFor, yFor, maxDamage, maxHealing, maxStrip]);

  if (points.length === 0 || !layout) {
    return (
      <div style={EMPTY_STYLE}>
        {points.length === 0
          ? "No timeline data available."
          : "Timeline data unavailable."}
      </div>
    );
  }

  return (
    <div style={SECTION_STYLE}>
      <div style={HEADER_STYLE}>
        {caption !== undefined && (
          <span style={CAPTION_STYLE}>{caption}</span>
        )}
        <PlayerTimelineLegend />
      </div>
      <TimelineSvg
        ariaLabel={ariaLabel}
        innerW={innerW}
        innerH={innerH}
        isLog={isLog}
        ticks={ticks}
        xFor={xFor}
        yFor={yFor}
        damageD={damageD}
        healingD={healingD}
        stripD={stripD}
        pointGeometry={pointGeometry}
        xLabelIndices={xLabelIndices}
        points={points}
      />
    </div>
  );
}
