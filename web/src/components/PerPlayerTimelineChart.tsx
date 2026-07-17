/**
 * v0.10.3 plan 083 Feature 3A: inline SVG multi-line chart
 * for the per-player timeline.
 *
 * Why a NEW chart (vs reusing :class:`TimelineChart`)
 * ====================================================
 * :class:`TimelineChart` renders 3 polylines (damage / healing
 * / buff-removal) for ONE timeline. The per-player chart
 * renders N polylines (one per player agent) for ONE metric
 * (the analyst toggles between damage / healing / strip via
 * the metric selector). The two chart shapes are structurally
 * different:
 *
 * - :class:`TimelineChart` is "3 series × 1 timeline".
 * - :class:`PerPlayerTimelineChart` is "N players × 1 metric".
 *
 * A generalisation (N series × M metrics, with M=1) would
 * inflate the base with metadata the per-account historical
 * timeline and the per-fight timeline don't need (a metric
 * selector, a per-series label). The DRY win is too small for
 * the API surface inflation.
 *
 * Why per-player ABSOLUTE Y axis (vs per-player normalised)
 * ==========================================================
 * The :class:`TimelineChart` base normalises each series to
 * its own 0-100% range so the 3 metrics (with widely
 * different magnitudes -- damage 10k-100k vs strip 0-500)
 * show trends side by side. The per-player chart is a
 * different use case: the analyst wants to compare the SAME
 * metric across players ("did Heinrik out-DPS Brendon in the
 * 0:10-0:20 window?"). A shared absolute Y axis on the
 * selected metric is the natural answer. The metric toggle
 * picks the magnitude to compare; the per-player max
 * surfaces in the legend (the per-series label).
 *
 * Why a TOP-N selector (default 10)
 * ==================================
 * A 30-player WvW fight produces 30 polylines; a single
 * shared Y axis compresses them all into a single noisy
 * strip. The default top-10 limit keeps the chart readable
 * while still showing the dominant contributors; the
 * analyst can expand to top-20 or top-30 via the selector
 * if the per-player breakdown matters more than the trend.
 *
 * Why a METRIC selector (radio buttons: damage / healing /
 * strip)
 * =============================================================
 * A single per-player chart can only compare ONE dimension
 * (the Y axis is single-valued). Toggling between damage /
 * healing / strip is the natural way to switch the question
 * ("who did the most damage?" vs "who healed the most?" vs
 * "who stripped the most?"). The selector is a 3-button
 * radio group pinned at the top of the chart; the metric
 * state is local to the Client Component (no URL state --
 * the tabbed section's URL state is the aggregated-vs-per-
 * player toggle, the metric toggle is a transient filter
 * within the per-player view).
 *
 * Color palette
 * =============
 * The 10-color palette is hardcoded (not driven by CSS
 * vars) because the chart needs visually distinct hues --
 * CSS vars would tie us to the app's surface palette which
 * has only 2-3 distinct colors. The palette is inspired by
 * D3's ``schemeCategory10`` (the canonical categorical
 * 10-color set); the first 10 entries are the D3 defaults
 * + 4 extended hues for the 20 / 30 top-N selectors.
 *
 * Empty + 1-player handling
 * =========================
 * - 0 series -> empty-state panel (same as
 *   :class:`TimelineChart`).
 * - 1 series -> single polyline + single legend row; the
 *   chart is still useful (the analyst sees the solo
 *   player's timeline + can confirm the other players
 *   are missing).
 * - All-zero points for a given series -> that series
 *   collapses to a flat baseline at y=0.
 */

/* eslint-disable react-refresh/only-export-components */

"use client";

import { memo, useMemo, useState } from "react";
import { formatSecondsLabel } from "@/lib/format";
import type { PerPlayerTimelineSeries } from "@/lib/api";

// ---------------------------------------------------------------------------
// Shared layout constants (mirror the TimelineChart base for visual parity)
// ---------------------------------------------------------------------------

const CHART_WIDTH = 720;
const CHART_HEIGHT = 280;
const CHART_PADDING = { top: 16, right: 16, bottom: 36, left: 64 };
const POINT_RADIUS_PX = 2;
const X_LABEL_SAMPLE_PX = 120;
const TOP_N_OPTIONS: number[] = [5, 10, 20, 30];
const DEFAULT_TOP_N = 10;

// D3's ``schemeCategory10`` + 4 extended hues. The 14-entry
// palette covers the top-30 selector with visual distinction
// (top-10 is unambiguous; top-20 is distinguishable for most
// color-vision profiles; top-30 starts to overlap but the
// analyst can still pick out the top 5-10 dominant lines).
// A helper function (not direct index access) handles the
// wrap-around so the call site doesn't need a ``??`` fallback
// that would silently hide any future palette shortening.
const PALETTE: readonly string[] = [
  "#1f77b4", // D3 blue
  "#ff7f0e", // D3 orange
  "#2ca02c", // D3 green
  "#d62728", // D3 red
  "#9467bd", // D3 purple
  "#8c564b", // D3 brown
  "#e377c2", // D3 pink
  "#7f7f7f", // D3 grey
  "#bcbd22", // D3 olive
  "#17becf", // D3 cyan
  "#393b79", // extended: dark blue
  "#8c6d31", // extended: dark gold
  "#637939", // extended: dark green
  "#7b4173", // extended: dark purple
] as const;

/**
 * Pick a stable color for the ``sIdx``-th visible series.
 *
 * The wrap-around (modulo PALETTE.length) is intentional: a
 * top-30 fight reuses the 14-entry palette after index 14.
 * The first argument is non-negative (callers pass loop
 * indices); the modulo keeps it within ``[0, 14)``; the
 * ``PALETTE[mod]`` access is safe because the modulo
 * guarantees the index is in-range. The function returns
 * ``string`` (NOT ``string | undefined``) so callers
 * don't need a ``??`` fallback.
 */
function colorForIndex(sIdx: number): string {
  // ``sIdx`` is always a non-negative loop index, so the
  // single modulo keeps it within ``[0, 14)``; the
  // ``PALETTE[idx]`` access is safe by construction. The
  // ``as string`` cast keeps the public type non-optional
  // without disabling ``noUncheckedIndexedAccess``.
  return PALETTE[sIdx % PALETTE.length] as string;
}

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
  flexWrap: "wrap",
  gap: 12,
};

const HEADER_LABEL_STYLE: React.CSSProperties = {
  fontSize: 13,
  opacity: 0.7,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const CONTROLS_STYLE: React.CSSProperties = {
  display: "inline-flex",
  gap: 12,
  alignItems: "center",
  fontSize: 13,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const RADIO_LABEL_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const SELECT_STYLE: React.CSSProperties = {
  padding: "2px 6px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--surface)",
  color: "var(--foreground)",
  fontSize: 13,
};

const LEGEND_STYLE: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
  fontSize: 12,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const LEGEND_ITEM_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const LEGEND_SWATCH_BASE_STYLE: React.CSSProperties = {
  display: "inline-block",
  width: 10,
  height: 10,
  borderRadius: 2,
};

const TOP_N_LABEL_STYLE: React.CSSProperties = {
  opacity: 0.7,
  marginLeft: 12,
};

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type PerPlayerMetric = "damage" | "healing" | "strip";



/**
 * Get the per-metric total for a single point.
 *
 * The metric field is mapped to the 3 totals on
 * :class:`PerPlayerTimelinePoint`:
 * - ``"damage"`` -> ``total_damage``
 * - ``"healing"`` -> ``total_healing``
 * - ``"strip"`` -> ``total_buff_removal``
 *
 * A non-finite value is clamped to 0 so the chart's Y axis
 * doesn't render NaN as a non-finite coordinate (SVG
 * silently drops NaN points; the clamp + 0-fallback makes
 * the failure mode explicit at the chart level).
 */
function getMetricValue(
  totalDamage: number,
  totalHealing: number,
  totalStrip: number,
  metric: PerPlayerMetric,
): number {
  const v =
    metric === "damage"
      ? totalDamage
      : metric === "healing"
        ? totalHealing
        : totalStrip;
  return Number.isFinite(v) ? v : 0;
}

/**
 * Compute the per-series total for the selected metric.
 * Used for the deterministic top-N sort (highest total
 * first; ties broken by ascending account_name).
 */
function getMetricTotal(
  series: PerPlayerTimelineSeries,
  metric: PerPlayerMetric,
): number {
  return series.points.reduce(
    (acc, p) =>
      acc +
      getMetricValue(p.total_damage, p.total_healing, p.total_buff_removal, metric),
    0,
  );
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for unit tests)
// ---------------------------------------------------------------------------

export interface SelectedSeries {
  series: PerPlayerTimelineSeries;
  total: number;
}

/**
 * Select the top-N series by total of the selected metric.
 *
 * Strict parallel of the aggregated timeline's
 * deterministic-ordering contract: highest total first;
 * ties broken by ascending ``account_name``. The top-N
 * limit is applied AFTER the sort so the top-N are the
 * top-N, not the first N encountered in the input order.
 *
 * Returns the (possibly-empty) selected subset in the
 * same order, with the metric total pre-computed so the
 * caller doesn't re-calculate it during render. The caller
 * is responsible for the color-index mapping (so the chart
 * legend is stable across re-renders).
 */
export function selectTopNByMetric(
  series: PerPlayerTimelineSeries[],
  metric: PerPlayerMetric,
  n: number,
): SelectedSeries[] {
  const mapped: SelectedSeries[] = series.map((s) => ({
    series: s,
    total: getMetricTotal(s, metric),
  }));
  mapped.sort((a, b) => {
    const totalDiff = b.total - a.total;
    if (totalDiff !== 0) return totalDiff;
    return (a.series.account_name ?? "").localeCompare(
      b.series.account_name ?? "",
    );
  });
  return mapped.slice(0, n);
}

// ---------------------------------------------------------------------------
// Memoized sub-components
// ---------------------------------------------------------------------------

interface SeriesRenderData {
  series: PerPlayerTimelineSeries;
  total: number;
  color: string;
  lineD: string;
  cyCoords: number[];
  displayName: string;
  title: string;
}

interface ChartSvgProps {
  globalMax: number;
  innerW: number;
  innerH: number;
  xFor: (i: number) => number;
  seriesData: SeriesRenderData[];
  xLabels: number[];
}

/**
 * Memoized SVG chart body.
 *
 * Isolating the SVG prevents parent re-renders (e.g. hover
 * states, time cursors, or unrelated dashboard updates) from
 * diffing thousands of DOM nodes. The SVG only re-renders
 * when its props change.
 */
const ChartSvg = memo(function ChartSvg({
  globalMax,
  innerW,
  innerH,
  xFor,
  seriesData,
  xLabels,
}: ChartSvgProps) {
  return (
    <svg
      viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
      width="100%"
      style={{ display: "block" }}
      role="img"
      aria-label="Per-player timeline"
    >
      <g
        transform={`translate(${CHART_PADDING.left}, ${CHART_PADDING.top})`}
      >
        {/* Y-axis baseline + max tick (shared single axis) */}
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
          {globalMax.toLocaleString("en-US")}
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

        {/* N polylines: one per visible player, distinct color */}
        {seriesData.map((d) => (
          <g key={d.series.account_name}>
            <title>{d.title}</title>
            <path
              d={d.lineD}
              fill="none"
              stroke={d.color}
              strokeWidth={1.5}
              opacity={0.85}
            />
            {/* Per-point dots: a single dot per player per
                bucket (the 3 metrics of TimelineChart are
                reduced to 1 here -- the per-player chart
                shows 1 metric at a time). */}
            {d.cyCoords.map((cy, i) => (
              <circle
                key={`${d.series.account_name}-${i}`}
                cx={xFor(i)}
                cy={cy}
                r={POINT_RADIUS_PX}
                fill={d.color}
              />
            ))}
          </g>
        ))}

        {/* X-axis labels: sampled to keep the axis legible */}
        {xLabels.map((i) => {
          const p = seriesData[0]?.series.points[i];
          if (!p) return null;
          return (
            <text
              key={`x-${i}`}
              x={xFor(i)}
              y={innerH + 16}
              textAnchor="middle"
              fontSize={9}
              fill="var(--foreground)"
              opacity={0.6}
            >
              {formatSecondsLabel(p.window_start_ms)}
            </text>
          );
        })}
      </g>
    </svg>
  );
});

interface ControlBarProps {
  metric: PerPlayerMetric;
  setMetric: (m: PerPlayerMetric) => void;
  topN: number;
  setTopN: (n: number) => void;
  visibleCount: number;
  totalCount: number;
  windowS: number;
  durationS: number;
}

/**
 * Memoized control bar.
 *
 * Isolating the metric/top-N controls prevents transient
 * state updates (hover, focus) in the controls from
 * triggering a re-render of the expensive SVG chart.
 */
const ControlBar = memo(function ControlBar({
  metric,
  setMetric,
  topN,
  setTopN,
  visibleCount,
  totalCount,
  windowS,
  durationS,
}: ControlBarProps) {
  return (
    <div style={HEADER_STYLE}>
      <span style={HEADER_LABEL_STYLE}>
        Showing {visibleCount} of {totalCount} player
        {totalCount === 1 ? "" : "s"} ({windowS}-second window,{" "}
        {durationS.toFixed(2)} s duration)
      </span>
      <div style={CONTROLS_STYLE}>
        <span style={{ opacity: 0.7 }}>Metric:</span>
        {(["damage", "healing", "strip"] as const).map((m) => (
          <label key={m} style={RADIO_LABEL_STYLE}>
            <input
              type="radio"
              name="per-player-metric"
              value={m}
              checked={metric === m}
              onChange={() => setMetric(m)}
            />
            {m.charAt(0).toUpperCase() + m.slice(1)}
          </label>
        ))}
        <label htmlFor="per-player-top-n" style={TOP_N_LABEL_STYLE}>
          Top N:
        </label>
        <select
          id="per-player-top-n"
          aria-label="Top N players to display"
          value={topN}
          onChange={(e) => setTopN(Number.parseInt(e.target.value, 10))}
          style={SELECT_STYLE}
        >
          {TOP_N_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// The component
// ---------------------------------------------------------------------------

export function PerPlayerTimelineChart({
  series,
  windowS,
  durationS,
}: {
  series: PerPlayerTimelineSeries[];
  windowS: number;
  durationS: number;
}) {
  const [metric, setMetric] = useState<PerPlayerMetric>("damage");
  const [topN, setTopN] = useState<number>(DEFAULT_TOP_N);

  // Memoised top-N selection so the chart's color-index
  // mapping is stable across re-renders with the same
  // (series, metric, topN) tuple. The deterministic
  // ordering (sort by total, then by account_name) is the
  // same contract as the aggregated timeline's top-N
  // helper. Totals are pre-computed here so the render
  // phase doesn't re-calculate them.
  const visibleData = useMemo(
    () => selectTopNByMetric(series, metric, topN),
    [series, metric, topN],
  );

  // X-axis label sampling: first + last always drawn;
  // others at roughly one-label-per-X_LABEL_SAMPLE_PX
  // intervals. Mirrors the :class:`TimelineChart` base's
  // sampling. The bucket count is bounded by
  // ``duration_s / window_s`` (typically 60-300 buckets
  // for a 5-min WvW fight at window_s=5).
  const labelStep = useMemo(() => {
    if (visibleData.length === 0) return 1;
    const innerW =
      CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
    const pointCount = visibleData[0]?.series.points.length ?? 0;
    return Math.max(1, Math.ceil(X_LABEL_SAMPLE_PX / (innerW / Math.max(1, pointCount))));
  }, [visibleData]);

  // Y-axis scale + pre-computed per-series render data.
  // The global max is the highest per-bucket value across
  // all visible series in the selected metric. We also
  // pre-build the SVG path ``d`` strings and dot Y
  // coordinates so the render phase is pure JSX.
  const layout = useMemo(() => {
    if (visibleData.length === 0) return null;
    const pointCount = visibleData[0].series.points.length;
    if (pointCount === 0) return null;

    const innerW =
      CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
    const innerH =
      CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
    const xFor = (i: number) =>
      pointCount === 1
        ? innerW / 2
        : (innerW * i) / (pointCount - 1);

    // Single-pass value extraction + global max computation.
    // We materialise the raw values once, then build the
    // scaled geometry with the final globalMax in a second
    // pass. This avoids the previous double-build of lineD
    // and cyCoords.
    const rawValues: number[][] = visibleData.map(({ series: s }) =>
      s.points.map((p) =>
        getMetricValue(
          p.total_damage,
          p.total_healing,
          p.total_buff_removal,
          metric,
        ),
      ),
    );
    let globalMax = 0;
    for (const values of rawValues) {
      for (const v of values) {
        if (v > globalMax) globalMax = v;
      }
    }
    if (globalMax <= 0) globalMax = 1;

    const yFor = (v: number) => {
      if (!Number.isFinite(v)) return innerH;
      return Math.max(0, Math.min(innerH, innerH * (1 - v / globalMax)));
    };

    const seriesData: SeriesRenderData[] = visibleData.map(
      ({ series: s, total }, sIdx) => {
        const values = rawValues[sIdx];
        const displayName = s.name || s.account_name;
        const startLabel = formatSecondsLabel(
          s.points[0]?.window_start_ms ?? 0,
        );
        const endLabel = formatSecondsLabel(
          s.points[s.points.length - 1]?.window_end_ms ?? 0,
        );
        return {
          series: s,
          total,
          color: colorForIndex(sIdx),
          lineD: values
            .map(
              (v, i) =>
                `${i === 0 ? "M" : "L"}${xFor(i).toFixed(2)},${yFor(v).toFixed(2)}`,
            )
            .join(" "),
          cyCoords: values.map(yFor),
          displayName,
          title: `${displayName} (${s.account_name})\nTotal ${metric}: ${total.toLocaleString("en-US")}\n${startLabel}–${endLabel}`,
        };
      },
    );

    const xLabels = Array.from(
      new Set<number>([
        0,
        pointCount - 1,
        ...Array.from(
          { length: Math.ceil(pointCount / labelStep) },
          (_, k) => k * labelStep,
        ),
      ]),
    )
      .filter((i) => i >= 0 && i < pointCount)
      .sort((a, b) => a - b);

    return {
      globalMax,
      innerW,
      innerH,
      xFor,
      pointCount,
      seriesData,
      xLabels,
    };
  }, [visibleData, metric, labelStep]);

  if (series.length === 0 || !layout) {
    return <div style={EMPTY_STYLE}>No per-player timeline data available.</div>;
  }

  const { globalMax, innerW, innerH, xFor, seriesData, xLabels } = layout;

  return (
    <div style={SECTION_STYLE}>
      <ControlBar
        metric={metric}
        setMetric={setMetric}
        topN={topN}
        setTopN={setTopN}
        visibleCount={visibleData.length}
        totalCount={series.length}
        windowS={windowS}
        durationS={durationS}
      />
      <ChartSvg
        globalMax={globalMax}
        innerW={innerW}
        innerH={innerH}
        xFor={xFor}
        seriesData={seriesData}
        xLabels={xLabels}
      />
      <div style={LEGEND_STYLE}>
        {seriesData.map((d) => (
          <span
            key={d.series.account_name}
            style={LEGEND_ITEM_STYLE}
          >
            <span
              style={{
                ...LEGEND_SWATCH_BASE_STYLE,
                background: d.color,
              }}
            />
            {d.displayName}
            <span style={{ opacity: 0.7 }}>
              ({d.total.toLocaleString("en-US")})
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
