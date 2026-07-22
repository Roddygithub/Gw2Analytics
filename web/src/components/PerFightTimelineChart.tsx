/**
 * v0.8.9 of web (plan/002): inline SVG line chart for the
 * per-fight timeline.
 *
 * v0.9.0 plan/001 refactor: this component is now a THIN
 * WRAPPER around the shared :class:`TimelineChart` base --
 * strict parallel of :class:`PlayerTimelineChart`. The
 * wrapper owns the data-shape concerns (mapping
 * :class:`PerFightTimelinePoint` to the flat
 * :class:`TimelineChartPoint` shape, formatting the X-axis
 * labels in ``M:SS`` relative time, building the tooltip
 * text, picking the bucket index as the React key). The
 * shared base owns the SVG render, the per-series
 * normalisation, the linear/log scale, the X-axis label
 * sampling, the legend, and the empty-state panel.
 *
 * Why RELATIVE TIME for the X-axis (vs wall-clock)
 * ================================================
 * The per-account timeline uses ``MM/DD HH:MM`` (the
 * "historical cross-fight trend" use case -- the analyst
 * cares about WHEN across fights). The per-fight timeline
 * uses ``M:SS`` relative time (the "what happened in this
 * fight" use case -- the analyst cares about TIMING within
 * a single fight). The 2 wrappers each own their X-axis
 * format; the base is data-shape agnostic.
 *
 * Why the bucket INDEX as the React key
 * ======================================
 * :class:`PlayerTimelineChart` uses ``fight_id`` as the
 * React ``key`` because each point is a different fight.
 * Here all points share the same fight id (they're buckets
 * of the same fight), so the bucket INDEX is the natural
 * unique key. The base component receives a pre-formatted
 * ``key`` string from the wrapper -- the base doesn't need
 * to know about fight ids or bucket windows.
 *
 * Why inline SVG (vs a charting library)
 * ======================================
 * See :class:`TimelineChart` for the full rationale. Short
 * version: a 200-line SVG component renders the same shape
 * as a 50-150 KB charting library for the bounded point
 * count (max 100) and the rectangular data shape.
 *
 * Empty / single-point handling
 * =============================
 * Mirrors :class:`PlayerTimelineChart`:
 * - zero points -> empty-state panel.
 * - single point -> single vertical hairline at the X midpoint.
 * - all-zero points for a given series -> that series
 *   collapses to a flat baseline at y=0.
 */

/* eslint-disable react-refresh/only-export-components */

"use client";

import { useMemo } from "react";
import type { PerFightTimelinePoint } from "@/lib/api";
import { formatSecondsLabel } from "@/lib/format";
import { TimelineChart, type TimelineChartPoint } from "@/components/TimelineChart";

export { buildTimelineLayout as buildPerFightTimelineLayout, formatLogTick as formatPerFightLogTick } from "@/components/TimelineChart";

export type TimelineScale = "linear" | "log";

// Re-export the shared helper so existing consumers (e.g.
// ReplayPlayer) keep working without changing their imports.
export { formatSecondsLabel };

export function PerFightTimelineChart({
  points,
  scale = "linear",
}: {
  points: PerFightTimelinePoint[];
  scale?: TimelineScale;
}) {
  // Trim leading + trailing zero-activity buckets so the chart
  // focuses on the actual combat period. Long WvW fights (e.g. 272
  // min) spend most of their time repositioning with zero damage/
  // healing/strip; keeping all buckets flattens the few active ones
  // into invisibility. We find the first and last bucket with ANY
  // non-zero activity and render only that slice.
  // Returns [originalIndex, point] pairs so tooltips report the
  // correct bucket number from the original fight timeline.
  const trimmedWithIndex: [number, PerFightTimelinePoint][] = useMemo(() => {
    if (points.length === 0) return [];
    const isActive = (p: PerFightTimelinePoint) =>
      p.total_damage > 0 || p.total_healing > 0 || p.total_buff_removal > 0;
    const firstActive = points.findIndex(isActive);
    if (firstActive === -1) {
      // all zero — show everything with original indices
      return points.map((p, i) => [i, p] as [number, PerFightTimelinePoint]);
    }
    // Search from the end for the last active bucket.
    let lastActive = points.length - 1;
    while (lastActive > firstActive && !isActive(points[lastActive])) {
      lastActive--;
    }
    // Include 1 buffer bucket on each side for context.
    const start = Math.max(0, firstActive - 1);
    const end = Math.min(points.length - 1, lastActive + 1);
    const result: [number, PerFightTimelinePoint][] = [];
    for (let i = start; i <= end; i++) {
      result.push([i, points[i]]);
    }
    return result;
  }, [points]);

  // Map PerFightTimelinePoint[] to the flat
  // TimelineChartPoint[] shape the base component consumes.
  // The wrapper owns the X-axis label format (``M:SS``) +
  // the tooltip text + the React key (original bucket index
  // so the analyst sees the correct temporal reference).
  const chartPoints: TimelineChartPoint[] = useMemo(
    () =>
      trimmedWithIndex.map(([origIdx, p]) => {
        const startLabel = formatSecondsLabel(p.window_start_ms);
        const endLabel = formatSecondsLabel(p.window_end_ms);
        return {
          series: [p.total_damage, p.total_healing, p.total_buff_removal],
          key: `bucket-${origIdx}`,
          xLabel: startLabel,
          tooltip:
            `${startLabel}–${endLabel} · bucket ${origIdx + 1}/${points.length}\n` +
            `Damage: ${p.total_damage.toLocaleString("en-US")}\n` +
            `Healing: ${p.total_healing.toLocaleString("en-US")}\n` +
            `Strip: ${p.total_buff_removal.toLocaleString("en-US")}`,
        };
      }),
    [trimmedWithIndex, points.length],
  );

  return (
    <TimelineChart
      points={chartPoints}
      scale={scale}
      caption="Per-bucket trend (normalized per series)"
      ariaLabel="Per-fight timeline"
    />
  );
}
