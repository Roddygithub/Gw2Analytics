/**
 * v0.10.0 plan 032: inline SVG line chart for the
 * cross-account comparison timeline.
 *
 * Why a NEW chart component (vs reusing :class:`TimelineChart`)
 * ============================================================
 * The shared :class:`TimelineChart` base renders 3 polylines
 * (damage / healing / strip) per point per account. The
 * cross-account use case is the inverse: 1 metric (selected
 * via the section's radio) per N accounts (2-4 polylines on
 * the same chart). Reusing the base would require either
 * (a) stuffing the 4 accounts' values into the base's
 * ``series: [number, number, number]`` shape (impossible --
 * 3 fields, 4+ accounts) or (b) rendering 4 separate
 * :class:`TimelineChart` instances stacked vertically
 * (wastes viewport, no shared X axis). A purpose-built
 * :class:`CrossAccountTimelineChart` is the cleaner path.
 *
 * Why per-account color (vs per-metric color)
 * ===========================================
 * The per-account timeline uses 3 fixed colors (damage =
 * accent, healing = foreground, strip = orange) because
 * the analyst's eye associates damage with the red bar
 * across the entire app. The cross-account chart
 * inverts this: 1 metric at a time, N accounts, so the
 * analyst's eye must track WHO is who across the
 * comparison. A 4-color palette per account (red / green /
 * blue / purple) is the canonical categorical palette
 * (matches the per-squad subgroup roll-up's visual
 * convention).
 *
 * Why a shared absolute Y axis (vs per-series normalised)
 * =======================================================
 * The cross-account use case is "who hit harder" -- the
 * absolute magnitudes are the point. Per-series
 * normalisation (the per-account timeline's linear mode)
 * would make a 1M-damage account visually identical to a
 * 50k-damage account (both render as 100% on their own
 * scale). The shared absolute axis + log scale is the
 * canonical "fair comparison" tool: a 1M-damage account
 * renders high on the axis; a 50k-damage account renders
 * at the 50k decade; both are visible simultaneously.
 *
 * Why a broken line for missing dates (vs rendering zeros)
 * ========================================================
 * Two accounts rarely share the same fight set: account A
 * may have fought on day N, day N+2, day N+5 while
 * account B fought on day N+1, day N+3, day N+5. The X
 * axis is the UNION of all dates; each account's polyline
 * renders only on the dates that account fought. A "0"
 * sentinel on missing dates would render the polyline at
 * the chart's baseline (a misleading visual -- the
 * account's absence is NOT a 0 total, it's "no data").
 * The broken-line approach splits each polyline into
 * contiguous runs of non-null values; SVG renders each
 * run as a separate ``<path>`` so the gap is visually
 * unambiguous.
 *
 * Why inline SVG (vs a charting library)
 * ======================================
 * Same rationale as :class:`TimelineChart`: the data shape
 * is trivially rectangular, the point count is bounded by
 * the route's day-bucketed limit (max ~365 days for a
 * year of fighting), and a charting library would add
 * 50-150 KB to the bundle for features we don't need.
 */

"use client";

import { useMemo } from "react";
import {
  CROSS_ACCOUNT_TIMELINE_EMPTY_STATE,
  CROSS_ACCOUNT_TIMELINE_LEGEND_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_CHART_LABEL,
} from "@/lib/copy/cross-account-timeline";

export interface CrossAccountSeriesInput {
  account_name: string;
  name: string;
  points: Array<{
    started_at: string;
    total_damage: number;
    total_healing: number;
    total_buff_removal: number;
  }>;
}

export type CrossAccountMetric = "damage" | "healing" | "strip";
export type CrossAccountScale = "linear" | "log";

const CHART_WIDTH = 720;
const CHART_HEIGHT = 240;
const CHART_PADDING = { top: 16, right: 16, bottom: 36, left: 64 };
const POINT_RADIUS_PX = 3;
const X_LABEL_SAMPLE_PX = 120;
const MAX_LOG_TICKS = 8;

// 4-color palette for up to 4 accounts (the route's hard
// limit). Order: red (existing --accent), green, blue,
// purple. Matches the per-squad subgroup roll-up's visual
// convention.
const ACCOUNT_COLORS: readonly string[] = [
  "var(--accent)", // red
  "#10b981", // green
  "#3b82f6", // blue
  "#a855f7", // purple
];

const X_AXIS_FORMAT = new Intl.DateTimeFormat("en-US", {
  month: "2-digit",
  day: "2-digit",
});

const METRIC_FIELD: Record<
  CrossAccountMetric,
  "total_damage" | "total_healing" | "total_buff_removal"
> = {
  damage: "total_damage",
  healing: "total_healing",
  strip: "total_buff_removal",
};

const METRIC_LABEL: Record<CrossAccountMetric, string> = {
  damage: CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_LABEL,
  healing: CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_LABEL,
  strip: CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_CHART_LABEL,
};

/**
 * Format a Y-axis tick value for the log scale. Strict
 * parallel of :func:`TimelineChart.formatLogTick` -- kept as
 * a local copy because the cross-account chart is
 * intentionally decoupled from the per-account chart's
 * TimelineChart base (different data shape, different
 * rendering path).
 */
function formatLogTick(v: number): string {
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
  const b = v / 1_000_000_000;
  return b === Math.floor(b) ? `${b}B` : `${b.toFixed(1)}B`;
}

interface AlignedSeries {
  account_name: string;
  name: string;
  color: string;
  /** Value per X-axis date; ``null`` means "no data on that date" (broken line). */
  values: ReadonlyArray<number | null>;
}

function buildPolylineSegments(
  values: ReadonlyArray<number | null>,
  xFor: (i: number) => number,
  yFor: (v: number) => number,
): string[] {
  /**Split a series' values into one or more SVG path ``d``
   * strings, splitting at ``null`` boundaries so the
   * polyline has a visual gap where the account has no
   * data. A single contiguous run of non-null values
   * yields one path; two runs separated by a ``null``
   * yield two paths; etc. The first non-null value of a
   * run uses ``M`` (move-to); subsequent values use
   * ``L`` (line-to). ``yFor(null)`` is the chart's
   * baseline (not used here -- we skip the null point
   * entirely). */
  const segments: string[] = [];
  let current: string[] = [];
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v === null) {
      if (current.length > 0) {
        segments.push(current.join(" "));
        current = [];
      }
      continue;
    }
    const cmd = current.length === 0 ? "M" : "L";
    current.push(`${cmd}${xFor(i).toFixed(2)},${yFor(v).toFixed(2)}`);
  }
  if (current.length > 0) {
    segments.push(current.join(" "));
  }
  return segments;
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

export function CrossAccountTimelineChart({
  series,
  metric,
  scale = "log",
}: {
  series: CrossAccountSeriesInput[];
  metric: CrossAccountMetric;
  scale?: CrossAccountScale;
}) {
  // Union of all ``started_at`` timestamps across all
  // series, sorted ascending. This is the SHARED X axis
  // -- every account's polyline aligns to this set.
  // A single timestamp union is the natural "union of
  // fight days" semantics: each date is rendered once
  // regardless of how many accounts fought on it.
  const allDates = useMemo(() => {
    const set = new Set<string>();
    for (const s of series) {
      for (const p of s.points) {
        set.add(p.started_at);
      }
    }
    return Array.from(set).sort();
  }, [series]);

  // Align each series to the union of dates. Missing
  // dates map to ``null`` (broken-line sentinel).
  const aligned: AlignedSeries[] = useMemo(() => {
    const field = METRIC_FIELD[metric];
    return series.map((s, i) => {
      const valueByDate = new Map<string, number>();
      for (const p of s.points) {
        valueByDate.set(p.started_at, p[field]);
      }
      return {
        account_name: s.account_name,
        name: s.name,
        color: ACCOUNT_COLORS[i % ACCOUNT_COLORS.length] ?? "var(--accent)",
        values: allDates.map((d) => valueByDate.get(d) ?? null),
      };
    });
  }, [series, allDates, metric]);

  // Global max across all aligned values for the selected
  // metric (the Y-axis calibration). ``Math.max(1, ...)``
  // pins the all-zero sentinel to 1 so the log mode's
  // ``Math.log10(globalMax + 1)`` doesn't divide by 0.
  const globalMax = useMemo(() => {
    let max = 0;
    for (const a of aligned) {
      for (const v of a.values) {
        if (v !== null && v > max) max = v;
      }
    }
    return Math.max(1, max);
  }, [aligned]);

  if (allDates.length === 0) {
  return (
    <div style={EMPTY_STYLE}>
      {CROSS_ACCOUNT_TIMELINE_EMPTY_STATE}
    </div>
  );
  }

  const innerW = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const innerH = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;

  const xFor = (i: number): number =>
    allDates.length === 1
      ? innerW / 2
      : (innerW * i) / (allDates.length - 1);

  const isLog = scale === "log";
  const logMax = isLog ? Math.log10(globalMax + 1) : 1;
  const yFor = (v: number): number => {
    if (!Number.isFinite(v)) return innerH;
    if (isLog) {
      return Math.max(
        0,
        Math.min(innerH, innerH * (1 - Math.log10(v + 1) / logMax)),
      );
    }
    return Math.max(0, Math.min(innerH, innerH * (1 - v / globalMax)));
  };

  // Log Y-axis ticks: 0 baseline + each decade up to
  // globalMax, capped at MAX_LOG_TICKS so the 64px left
  // padding can fit them.
  const logTicks: number[] = isLog
    ? (() => {
        const ticks: number[] = [0];
        const maxExp = Math.ceil(logMax);
        for (let exp = 0; exp <= maxExp && ticks.length < MAX_LOG_TICKS; exp++) {
          const v = Math.pow(10, exp);
          if (v <= globalMax) ticks.push(v);
        }
        return ticks;
      })()
    : [0, globalMax];

  // X-axis label sampling: first + last always drawn;
  // intermediates at roughly one-label-per-X_LABEL_SAMPLE_PX
  // intervals.
  const labelStep = Math.max(
    1,
    Math.ceil(X_LABEL_SAMPLE_PX / (innerW / Math.max(1, allDates.length))),
  );
  const xLabelIndices = new Set<number>([0, allDates.length - 1]);
  for (let i = 0; i < allDates.length; i += labelStep) {
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
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <span
          style={{
            fontSize: 13,
            opacity: 0.7,
            fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
          }}
        >
          {METRIC_LABEL[metric]} trend &middot; shared {scale} scale &middot;
          max {formatLogTick(globalMax)}
        </span>
        <div
          style={{
            display: "flex",
            gap: 12,
            fontSize: 12,
            color: "var(--foreground)",
            opacity: 0.85,
            fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
            flexWrap: "wrap",
          }}
          role="list"
          aria-label={CROSS_ACCOUNT_TIMELINE_LEGEND_ARIA_LABEL}
        >
          {aligned.map((a) => (
            <span key={a.account_name} role="listitem">
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 10,
                  marginRight: 6,
                  verticalAlign: "middle",
                  background: a.color,
                }}
                aria-hidden="true"
              />
              {a.name || a.account_name}
            </span>
          ))}
        </div>
      </div>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        width="100%"
        style={{ display: "block" }}
        role="img"
        aria-label={`Cross-account ${metric} comparison`}
      >
        <g
          transform={`translate(${CHART_PADDING.left}, ${CHART_PADDING.top})`}
        >
          {/* Y-axis baseline + left edge */}
          <line x1={0} y1={innerH} x2={innerW} y2={innerH} stroke="var(--border)" />
          <line x1={0} y1={0} x2={0} y2={innerH} stroke="var(--border)" />

          {/* Y-axis labels */}
          {isLog
            ? logTicks.map((tick) => (
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
                    {formatLogTick(globalMax)}
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

          {/* N polylines (broken-line segments) */}
          {aligned.map((a) => {
            const segments = buildPolylineSegments(a.values, xFor, yFor);
            return segments.map((d, i) => (
              <path
                key={`${a.account_name ?? a.name ?? `acc:${i}`}-${i}`}
                d={d}
                fill="none"
                stroke={a.color}
                strokeWidth={1.5}
              />
            ));
          })}

          {/* Per-point dots (only for non-null values) + SVG
              tooltips with the account name + the metric value. */}
          {aligned.map((a) =>
            a.values.map((v, i) => {
              if (v === null) return null;
              return (
                <circle
                  key={`${a.account_name ?? a.name ?? `acc:${i}`}-dot-${i}`}
                  cx={xFor(i)}
                  cy={yFor(v)}
                  r={POINT_RADIUS_PX}
                  fill={a.color}
                >
                  <title>
                    {`${a.name || a.account_name} \u00b7 ${X_AXIS_FORMAT.format(
                      new Date(allDates[i] ?? ""),
                    )}\n${METRIC_LABEL[metric]}: ${v.toLocaleString("en-US")}`}
                  </title>
                </circle>
              );
            }),
          )}

          {/* X-axis labels (sampled) */}
          {[...xLabelIndices].sort((a, b) => a - b).map((i) => (
            <text
              key={`x-${i}`}
              x={xFor(i)}
              y={innerH + 16}
              textAnchor="middle"
              fontSize={9}
              fill="var(--foreground)"
              opacity={0.6}
            >
              {X_AXIS_FORMAT.format(new Date(allDates[i] ?? ""))}
            </text>
          ))}
        </g>
      </svg>
    </div>
  );
}
