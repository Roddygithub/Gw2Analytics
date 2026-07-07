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
// v0.8.2 of web: cap on the number of logarithmic Y-axis
// ticks. The 48px left padding can fit ~8 decade labels
// (1, 10, 100, 1k, 10k, 100k, 1M, 10M) before they start
// overlapping. A global max of 1B would otherwise draw 10
// ticks (0 + 9 decades) and overflow the padding. Extracted
// to a constant so the cap is tunable in one place.
const MAX_LOG_TICKS = 8;
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

/**
 * Explicit ``"en-US"`` locale (NOT ``undefined``) so the
 * server (Node.js) and the client (browser) agree on the
 * format string. ``undefined`` would pick the system locale
 * (typically ``"C"`` or ``"en-US"`` on Node.js, the user's
 * browser locale on the client) and cause a React hydration
 * mismatch when the two disagree -- e.g. ``"07/07/26, 12:00"``
 * on one side and ``"07/07/2026, 12:00 pm"`` on the other.
 * The tooltip's ``toLocaleString()`` calls below follow the
 * same convention.
 *
 * v0.8.1 of the API: the day-bucketed timeline points carry
 * ``started_at`` rounded to UTC midnight (the route's
 * ``_combine_day_midnight`` helper). The chart auto-detects
 * the day-aligned timestamps and renders ``MM/DD`` instead
 * of ``MM/DD HH:MM`` so the X-axis stays compact when the
 * analyst switches to ``?bucket=day``. No new prop: the
 * detection is a single ``.every()`` walk over the points.
 */
const X_AXIS_LABEL_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
const X_AXIS_DAY_LABEL_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "2-digit",
  day: "2-digit",
});

/**
 * Pure helper exported for the unit test (snapshot the layout
 * without rendering). Returns the per-series max + the X
 * positions for each point (1:1 with the input). The caller
 * draws the polylines + dots.
 *
 * ``scale`` picks the Y-axis strategy:
 *
 * - ``"linear"`` (default): per-series 0-100% normalisation.
 *   Each of the 3 series is scaled to its own max so a
 *   1M-damage and a 50-strip render at the same visual
 *   height. Best for TREND reading (per-series shape).
 *
 * - ``"log"``: SHARED log Y-axis across all 3 series. The
 *   global max is ``max(max_damage, max_healing, max_strip)``
 *   and each value is mapped via ``log10(v + 1) / log10(
 *   global_max + 1)``. Best for MAGNITUDE reading -- a
 *   damage=1M (at log10~6) and a strip=50 (at log10~1.7) are
 *   both visible on the same axis. The ``+ 1`` offset keeps
 *   zero values at the baseline (``log10(0 + 1) = 0``). The
 *   ``+ 1`` on the denominator keeps the global max at the
 *   top of the chart (``log10(global_max + 1) / log10(
 *   global_max + 1) = 1``). Y-axis ticks are generated at
 *   each decade (1, 10, 100, 1k, 10k, 100k, 1M, ...) up to
 *   the global max, plus a 0 baseline.
 */
export type TimelineScale = "linear" | "log";

export function buildTimelineLayout(
  points: PlayerTimelinePoint[],
  scale: TimelineScale = "linear",
) {
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

  if (scale === "log") {
    // Shared log Y-axis: the global max is the highest value
    // across all 3 series, so the Y-axis is calibrated to the
    // tallest series. The other 2 series render at lower
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
    // ``TS2554: Expected 2 arguments, but got 1`` check.
    // The result is clamped to ``[0, innerH]`` for the same
    // reason as the linear branch -- a missing-arg call
    // would otherwise produce a negative ``y`` for
    // ``v > globalMax`` (e.g. a test that hard-codes
    // ``v = 2 * globalMax`` would render above the chart).
    // v0.8.2 also guards against ``NaN`` inputs: a
    // non-finite ``v`` (e.g. a future feature that divides
    // by zero upstream) would make ``Math.log10`` return
    // ``NaN``, the ``Math.max``/``Math.min`` comparisons
    // return ``false``, and the final result is ``NaN`` --
    // SVG renders ``NaN`` as a non-finite coordinate and
    // silently drops the point. The ``Number.isFinite``
    // short-circuit pins the point to the baseline.
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
  // v0.8.2 also guards against ``NaN`` inputs: a
  // non-finite ``v`` would make the division return
  // ``NaN``, the ``Math.max``/``Math.min`` comparisons
  // return ``false``, and the final result is ``NaN`` --
  // SVG renders ``NaN`` as a non-finite coordinate and
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

export function PlayerTimelineChart({
  points,
  scale = "linear",
}: {
  points: PlayerTimelinePoint[];
  scale?: TimelineScale;
}) {
  const layout = useMemo(
    () => buildTimelineLayout(points, scale),
    [points, scale],
  );

  // v0.8.1 of the API: day-bucketed points carry ``started_at`` at
  // UTC midnight, so the X-axis can render ``MM/DD`` only. The
  // detection is a single ``.every()`` walk -- cheap (O(n) on
  // the points list, bounded by the route's ``limit <= 100``).
  // Empty arrays keep the full ``MM/DD HH:MM`` format (no chart
  // to render anyway).
  const xAxisFormat = useMemo(() => {
    if (points.length === 0) {
      return X_AXIS_LABEL_FORMAT;
    }
    const allAtMidnight = points.every((p) => {
      const d = new Date(p.started_at);
      return (
        d.getUTCHours() === 0
        && d.getUTCMinutes() === 0
        && d.getUTCSeconds() === 0
      );
    });
    return allAtMidnight ? X_AXIS_DAY_LABEL_FORMAT : X_AXIS_LABEL_FORMAT;
  }, [points]);

  if (points.length === 0 || !layout) {
    return <div style={EMPTY_STYLE}>No timeline data available.</div>;
  }

  const { maxDamage, maxHealing, maxStrip, innerW, innerH, xFor, yFor, ticks } =
    layout;

  // v0.8.2 of web: in ``"log"`` mode the 3 polylines share a
  // single Y-axis, so the ``max`` argument is unused -- the
  // ``yFor`` returned by ``buildTimelineLayout`` ignores it.
  // In ``"linear"`` mode the per-series max picks the right
  // denominator. Both branches accept the same 2-arg
  // signature (the log-mode ``_max`` is unused) so the
  // return type of ``buildTimelineLayout`` is a single
  // overload.
  const isLog = layout.scale === "log";

  // Build the polyline ``d`` strings: one ``M`` + N ``L``s.
  const buildD = (values: number[], max: number): string =>
    values
      .map(
        (v, i) =>
          `${i === 0 ? "M" : "L"}${xFor(i).toFixed(2)},${yFor(v, max).toFixed(2)}`,
      )
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

          {/* Per-point dots, one set per series. ``fight_id`` is the canonical key. */}
          {points.map((p, i) => (
            <g key={p.fight_id}>
              {/* Per-group ``<title>`` surfaces the absolute
                  values on hover for ANY of the 3 sibling
                  dots (the y-axis is normalized to 0-100%
                  per series in linear mode, or shared-log in
                  log mode, so the raw magnitudes are
                  otherwise invisible). SVG ``<title>`` is
                  the canonical lightweight tooltip -- no
                  React state, no portal, no client-side
                  JS. The browser shows it as a native
                  tooltip on hover/focus. A single
                  concatenated string is used (NOT 4
                  separate template-string children) so
                  React receives a single string child --
                  multiple children trigger a hydration
                  mismatch ("expected a string, received
                  an array") and inflate the DOM with
                  reconciliation wrappers. */}
              <title>
                {`${p.fight_id} · ${xAxisFormat.format(new Date(p.started_at))}\n` +
                  `Damage: ${p.total_damage.toLocaleString("en-US")}\n` +
                  `Healing: ${p.total_healing.toLocaleString("en-US")}\n` +
                  `Strip: ${p.total_buff_removal.toLocaleString("en-US")}`}
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
                {xAxisFormat.format(new Date(p.started_at))}
              </text>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
