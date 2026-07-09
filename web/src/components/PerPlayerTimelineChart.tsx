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

"use client";

import { useMemo, useState } from "react";
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

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type PerPlayerMetric = "damage" | "healing" | "strip";

/**
 * Format a bucket's ``window_start_ms`` as a ``M:SS`` label.
 * Mirror of :func:`formatSecondsLabel` in
 * :class:`PerFightTimelineChart` -- the per-player chart
 * shares the same X-axis format (relative time, the
 * "what happened in this fight" use case).
 */
function formatSecondsLabel(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

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
 * same order. The caller is responsible for the
 * color-index mapping (so the chart legend is stable
 * across re-renders).
 */
export function selectTopNByMetric(
  series: PerPlayerTimelineSeries[],
  metric: PerPlayerMetric,
  n: number,
): PerPlayerTimelineSeries[] {
  const sorted = [...series].sort((a, b) => {
    const totalDiff = getMetricTotal(b, metric) - getMetricTotal(a, metric);
    if (totalDiff !== 0) return totalDiff;
    return a.account_name.localeCompare(b.account_name);
  });
  return sorted.slice(0, n);
}

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
  // helper.
  const visibleSeries = useMemo(
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
    if (visibleSeries.length === 0) return 1;
    const innerW =
      CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
    const pointCount = visibleSeries[0]?.points.length ?? 0;
    return Math.max(1, Math.ceil(X_LABEL_SAMPLE_PX / (innerW / Math.max(1, pointCount))));
  }, [visibleSeries]);

  // Y-axis scale: the global max is the highest
  // per-bucket value across all visible series in the
  // selected metric. A single point's value is the metric
  // total for that bucket. The Y axis is shared across
  // all visible series so a high-magnitude player line
  // doesn't dwarf a low-magnitude one.
  const layout = useMemo(() => {
    if (visibleSeries.length === 0) return null;
    const pointCount = visibleSeries[0].points.length;
    if (pointCount === 0) return null;
    let globalMax = 0;
    for (const s of visibleSeries) {
      for (const p of s.points) {
        const v = getMetricValue(
          p.total_damage,
          p.total_healing,
          p.total_buff_removal,
          metric,
        );
        if (v > globalMax) globalMax = v;
      }
    }
    if (globalMax <= 0) globalMax = 1;
    const innerW =
      CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
    const innerH =
      CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
    const xFor = (i: number) =>
      pointCount === 1
        ? innerW / 2
        : (innerW * i) / (pointCount - 1);
    const yFor = (v: number) => {
      if (!Number.isFinite(v)) return innerH;
      return Math.max(0, Math.min(innerH, innerH * (1 - v / globalMax)));
    };
    return { globalMax, innerW, innerH, xFor, yFor, pointCount };
  }, [visibleSeries, metric]);

  if (series.length === 0) {
    return (
      <div style={EMPTY_STYLE}>No per-player timeline data available.</div>
    );
  }

  if (!layout) {
    return (
      <div style={EMPTY_STYLE}>No per-player timeline data available.</div>
    );
  }

  const { globalMax, innerW, innerH, xFor, yFor, pointCount } = layout;

  return (
    <div style={SECTION_STYLE}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: 13,
            opacity: 0.7,
            fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
          }}
        >
          Showing {visibleSeries.length} of {series.length} player
          {series.length === 1 ? "" : "s"} ({windowS}-second window,{" "}
          {durationS.toFixed(2)} s duration)
        </span>
        <div
          style={{
            display: "inline-flex",
            gap: 12,
            alignItems: "center",
            fontSize: 13,
            fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
          }}
        >
          <span style={{ opacity: 0.7 }}>Metric:</span>
          {(["damage", "healing", "strip"] as const).map((m) => (
            <label
              key={m}
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
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
          <label
            htmlFor="per-player-top-n"
            style={{ opacity: 0.7, marginLeft: 12 }}
          >
            Top N:
          </label>
          <select
            id="per-player-top-n"
            aria-label="Top N players to display"
            value={topN}
            onChange={(e) => setTopN(Number.parseInt(e.target.value, 10))}
            style={{
              padding: "2px 6px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "var(--surface)",
              color: "var(--foreground)",
              fontSize: 13,
            }}
          >
            {TOP_N_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        width="100%"
        style={{ display: "block" }}
        role="img"
        ariaLabel="Per-player timeline"
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
          {visibleSeries.map((s, sIdx) => {
            const color = colorForIndex(sIdx);
            const total = getMetricTotal(s, metric);
            const displayName = s.name || s.account_name;
            const lineD = s.points
              .map((p, i) => {
                const v = getMetricValue(
                  p.total_damage,
                  p.total_healing,
                  p.total_buff_removal,
                  metric,
                );
                return `${i === 0 ? "M" : "L"}${xFor(i).toFixed(2)},${yFor(v).toFixed(2)}`;
              })
              .join(" ");
            const startLabel = formatSecondsLabel(
              s.points[0]?.window_start_ms ?? 0,
            );
            const endLabel = formatSecondsLabel(
              s.points[s.points.length - 1]?.window_end_ms ?? 0,
            );
            return (
              <g key={s.account_name}>
                <title>
                  {`${displayName} (${s.account_name})\n` +
                    `Total ${metric}: ${total.toLocaleString("en-US")}\n` +
                    `${startLabel}–${endLabel}`}
                </title>
                <path
                  d={lineD}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.5}
                  opacity={0.85}
                />
                {/* Per-point dots: a single dot per player per
                    bucket (the 3 metrics of TimelineChart are
                    reduced to 1 here -- the per-player chart
                    shows 1 metric at a time). */}
                {s.points.map((p, i) => {
                  const v = getMetricValue(
                    p.total_damage,
                    p.total_healing,
                    p.total_buff_removal,
                    metric,
                  );
                  return (
                    <circle
                      key={`${s.account_name}-${i}`}
                      cx={xFor(i)}
                      cy={yFor(v)}
                      r={POINT_RADIUS_PX}
                      fill={color}
                    />
                  );
                })}
              </g>
            );
          })}

          {/* X-axis labels: sampled to keep the axis legible */}
          {Array.from(
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
            .sort((a, b) => a - b)
            .map((i) => {
              const p = visibleSeries[0]?.points[i];
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
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          fontSize: 12,
          fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
        }}
      >
        {visibleSeries.map((s, sIdx) => {
          const color = colorForIndex(sIdx);
          const total = getMetricTotal(s, metric);
          return (
            <span
              key={s.account_name}
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 10,
                  background: color,
                  borderRadius: 2,
                }}
              />
              {s.name || s.account_name}
              <span style={{ opacity: 0.7 }}>
                ({total.toLocaleString("en-US")})
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}
