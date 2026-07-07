"use client";

/**
 * Inline SVG bar chart for the per-fight event windows.
 *
 * Visualises the same :class:`EventBucket` rows the
 * :class:`EventWindowsTable` renders, but as a
 * side-by-side bar chart (damage bar + healing bar per bucket)
 * so the analyst can spot burst windows at a glance.
 *
 * Why inline SVG (vs a charting library)
 * ======================================
 * The bucket count is bounded by ``duration_s / window_s`` (e.g.
 * a 60s fight at ``window_s=5`` is 12 buckets; a 5-minute fight
 * at ``window_s=1`` is 300 buckets) and the data shape is
 * trivially rectangular. A charting library (recharts /
 * visx / chart.js) would add ~50-150 KB to the bundle for
 * features we don't need (axes legends, tooltips, animation
 * timelines, responsive resize handlers). A 100-line SVG
 * component renders the same shape with zero deps.
 *
 * Why side-by-side bars (vs stacked)
 * ==================================
 * The two event kinds (damage + healing) come from independent
 * source-attribution paths; stacking them would imply "healing
 * comes out of damage" which the data does NOT support. A
 * side-by-side layout keeps the two magnitudes visually
 * independent and matches the per-target / per-bucket trio's
 * "independent roll-ups on the same duration_s" contract.
 *
 * Empty / single-bucket handling
 * ==============================
 * - zero buckets -> empty-state panel mirroring the
 *   :class:`EventWindowsTable` styling.
 * - single bucket -> the chart renders one bucket group
 *   (two bars). The x-axis labels show ``start_ms`` / ``end_ms``.
 * - all-zero buckets -> the chart renders the y-axis tick
 *   labels but the bars have zero height (visible as a flat
 *   baseline). The legend still shows damage + healing.
 */

import { useMemo } from "react";
import type { EventBucket } from "@/lib/api";

const CHART_WIDTH = 720;
const CHART_HEIGHT = 200;
const CHART_PADDING = { top: 16, right: 16, bottom: 32, left: 48 };
const BAR_GAP_PX = 4;
const BAR_PADDING_PX = 2;
const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const DAMAGE_FILL = "var(--accent)";
const HEALING_FILL = "var(--foreground)";

export function EventWindowsChart({ buckets }: { buckets: EventBucket[] }) {
  const layout = useMemo(() => {
    if (buckets.length === 0) {
      return null;
    }
    const maxValue = Math.max(
      1,
      ...buckets.flatMap((b) => [b.damage_total, b.healing_total]),
    );
    const innerW = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
    const innerH = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
    const groupWidth = innerW / buckets.length;
    const barWidth = Math.max(
      2,
      (groupWidth - BAR_GAP_PX) / 2 - BAR_PADDING_PX,
    );
    return { maxValue, innerW, innerH, groupWidth, barWidth };
  }, [buckets]);

  if (buckets.length === 0 || !layout) {
    return <div style={EMPTY_STYLE}>No event windows.</div>;
  }

  const { maxValue, innerW, innerH, groupWidth, barWidth } = layout;
  const yScale = (v: number) => innerH * (1 - v / maxValue);

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid var(--border)",
        borderRadius: 4,
        background: "var(--surface)",
      }}
    >
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        width="100%"
        style={{ display: "block" }}
        role="img"
        aria-label="Per-bucket event damage and healing"
      >
        <g transform={`translate(${CHART_PADDING.left}, ${CHART_PADDING.top})`}>
          {/* y-axis baseline + max tick */}
          <line
            x1={0}
            y1={innerH}
            x2={innerW}
            y2={innerH}
            stroke="var(--border)"
          />
          <line
            x1={0}
            y1={0}
            x2={0}
            y2={innerH}
            stroke="var(--border)"
          />
          <text
            x={-8}
            y={yScale(maxValue)}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize={10}
            fill="var(--foreground)"
            opacity={0.7}
          >
            {maxValue}
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

          {buckets.map((b, i) => {
            const x0 = i * groupWidth;
            const damageH = innerH - yScale(b.damage_total);
            const healingH = innerH - yScale(b.healing_total);
            return (
              <g key={`${b.start_ms}-${b.end_ms}`}>
                <rect
                  x={x0 + BAR_PADDING_PX}
                  y={yScale(b.damage_total)}
                  width={barWidth}
                  height={damageH}
                  fill={DAMAGE_FILL}
                />
                <rect
                  x={x0 + barWidth + BAR_GAP_PX}
                  y={yScale(b.healing_total)}
                  width={barWidth}
                  height={healingH}
                  fill={HEALING_FILL}
                  opacity={0.7}
                />
                {i % Math.max(1, Math.ceil(buckets.length / 8)) === 0 && (
                  <text
                    x={x0 + groupWidth / 2}
                    y={innerH + 14}
                    textAnchor="middle"
                    fontSize={9}
                    fill="var(--foreground)"
                    opacity={0.6}
                  >
                    {b.start_ms}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <div
        style={{
          display: "flex",
          gap: 16,
          fontSize: 12,
          marginTop: 8,
          color: "var(--foreground)",
          opacity: 0.7,
        }}
      >
        <span>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              background: DAMAGE_FILL,
              marginRight: 6,
              verticalAlign: "middle",
            }}
          />
          Damage
        </span>
        <span>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              background: HEALING_FILL,
              opacity: 0.7,
              marginRight: 6,
              verticalAlign: "middle",
            }}
          />
          Healing
        </span>
      </div>
    </div>
  );
}
