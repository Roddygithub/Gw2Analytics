"use client";

/**
 * Inline SVG line chart for the per-fight timeline (v0.8.9 plan/002).
 *
 * Visualises the same :class:`PerFightTimelinePoint` rows the
 * :class:`PerFightTimelineTable` (future) would render, but as
 * 3 stacked line series (damage + healing + buff-removal) so the
 * analyst can spot a per-fight trend at a glance.
 *
 * Strict parallel of :class:`PlayerTimelineChart`
 * (player-timeline-chart.tsx) -- same 3-series shape + same
 * per-series-max normalisation rationale + same inline-SVG-no-deps
 * tradeoff + same X-axis label sampling strategy. The 2 differences
 * are:
 *
 * 1. The X-axis labels are RELATIVE TIME in ``M:SS`` (e.g.
 *    ``"0:05"`` at ``window_start_ms=5000``), NOT absolute
 *    wall-clock ``MM/DD HH:MM``. The per-fight timeline is the
 *    "what happened in this fight" use case, so relative time is
 *    the natural frame. The ``window_start_ms / 1000`` produces
 *    the seconds-since-fight-start, and
 *    ``Math.floor(s / 60) + ":" + (s % 60).toString().padStart(2, "0")``
 *    produces the ``M:SS`` label.
 *
 * 2. The X-axis point identity is the bucket INDEX (NOT
 *    ``fight_id``), since each point is one bucket of the same
 *    fight. ``PlayerTimelineChart`` uses ``fight_id`` as the React
 *    ``key`` because each point is a different fight; here all
 *    points share the same fight id, so the bucket index is the
 *    natural key.
 *
 * Empty / single-point handling
 * =============================
 * Mirrors :class:`PlayerTimelineChart`:
 * - zero points -> empty-state panel.
 * - single point -> single vertical hairline at the X midpoint.
 * - all-zero points for a given series -> that series collapses
 *   to a flat baseline at y=0. The other series still draw; the
 *   legend still lists all 3.
 */

import { useMemo } from "react";
import type { PerFightTimelinePoint } from "@/lib/api";
import { PlayerTimelineLegend } from "@/components/PlayerTimelineLegend";

const CHART_WIDTH = 720;
const CHART_HEIGHT = 220;
const CHART_PADDING = { top: 16, right: 16, bottom: 36, left: 48 };
const POINT_RADIUS_PX = 3;
const X_LABEL_SAMPLE_PX = 120;
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
 * Format a bucket's ``window_start_ms`` as a ``M:SS`` label.
 * ``window_start_ms=0`` -> ``"0:00"`` (the fight-start bucket).
 * ``window_start_ms=65000`` -> ``"1:05"`` (1 min 5 sec into the
 * fight). The 2-digit zero-padding on seconds keeps the axis
 * labels aligned vertically (without the pad, a "0:5" label
 * would shift the "0:15" label to the right by 1 character
 * width and break the X-axis tick alignment).
 */
function formatSecondsLabel(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

/**
 * Pure helper exported for the unit test (snapshot the layout
 * without rendering). Returns the per-series max + the X
 * positions for each point (1:1 with the input). Strict parallel
 * of :func:`PlayerTimelineChart.buildTimelineLayout` (the only
 * delta is the dropped ``globalMax`` branch's
 * ``if (!Number.isFinite(v))`` guard is the same; the
 * ``_max`` arg in the log branch keeps the return type a single
 * overload). See the player-timeline-chart docstring for the
 * rationale behind the linear-vs-log scale split.
 */
export type TimelineScale = "linear" | "log";

export function buildPerFightTimelineLayout(
  points: PerFightTimelinePoint[],
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
  const xFor = (i: number) =>
    points.length === 1
      ? innerW / 2
      : (innerW * i) / (points.length - 1);

  if (scale === "log") {
    const globalMax = Math.max(maxDamage, maxHealing, maxStrip);
    const logMax = Math.log10(globalMax + 1);
    const yFor = (v: number, _max?: number) => {
      if (!Number.isFinite(v)) {
        return innerH;
      }
      return Math.max(
        0,
        Math.min(innerH, innerH * (1 - Math.log10(v + 1) / logMax)),
      );
    };
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
 * Format a Y-axis tick value for the ``"log"`` scale. Reuses the
 * same ``k`` / ``M`` / ``B`` suffix convention as
 * :func:`PlayerTimelineChart.formatLogTick`. Exported so the
 * component test can snapshot the formatter output without
 * rendering the chart.
 */
export function formatPerFightLogTick(v: number): string {
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

export function PerFightTimelineChart({
  points,
  scale = "linear",
}: {
  points: PerFightTimelinePoint[];
  scale?: TimelineScale;
}) {
  const layout = useMemo(
    () => buildPerFightTimelineLayout(points, scale),
    [points, scale],
  );

  if (points.length === 0 || !layout) {
    return <div style={EMPTY_STYLE}>No per-fight timeline data available.</div>;
  }

  const { maxDamage, maxHealing, maxStrip, innerW, innerH, xFor, yFor, ticks } =
    layout;
  const isLog = layout.scale === "log";

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
  // at roughly one-label-per-X_LABEL_SAMPLE_PX intervals. Strict
  // parallel of :class:`PlayerTimelineChart`'s sampling strategy;
  // the bucket index replaces the ``fight_id`` as the React key
  // since all points share the same fight id.
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
          Per-bucket trend (normalized per series)
        </span>
        <PlayerTimelineLegend />
      </div>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        width="100%"
        style={{ display: "block" }}
        role="img"
        aria-label="Per-fight timeline"
      >
        <g
          transform={`translate(${CHART_PADDING.left}, ${CHART_PADDING.top})`}
        >
          <line x1={0} y1={innerH} x2={innerW} y2={innerH} stroke="var(--border)" />
          <line x1={0} y1={0} x2={0} y2={innerH} stroke="var(--border)" />
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
                  {formatPerFightLogTick(tick)}
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

          {points.map((p, i) => (
            <g key={`bucket-${i}`}>
              <title>
                {`${formatSecondsLabel(p.window_start_ms)}–${formatSecondsLabel(p.window_end_ms)} · bucket ${i + 1}/${points.length}\n` +
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

          {[...xLabelIndices].sort((a, b) => a - b).map((i) => {
            const p = points[i];
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
    </div>
  );
}
