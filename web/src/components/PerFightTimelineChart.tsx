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
import { TimelineChart, type TimelineChartPoint } from "@/components/TimelineChart";

export { buildTimelineLayout as buildPerFightTimelineLayout, formatLogTick as formatPerFightLogTick } from "@/components/TimelineChart";

export type TimelineScale = "linear" | "log";

/**
 * Format a bucket's ``window_start_ms`` as a ``M:SS`` label.
 * ``window_start_ms=0`` -> ``"0:00"`` (the fight-start bucket).
 * ``window_start_ms=65000`` -> ``"1:05"`` (1 min 5 sec into
 * the fight). The 2-digit zero-padding on seconds keeps the
 * axis labels aligned vertically (without the pad, a
 * ``"0:5"`` label would shift the ``"0:15"`` label to the
 * right by 1 character width and break the X-axis tick
 * alignment).
 */
export function formatSecondsLabel(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${rem.toString().padStart(2, "0")}`;
}

export function PerFightTimelineChart({
  points,
  scale = "linear",
}: {
  points: PerFightTimelinePoint[];
  scale?: TimelineScale;
}) {
  // Map PerFightTimelinePoint[] to the flat
  // TimelineChartPoint[] shape the base component consumes.
  // The wrapper owns the X-axis label format (``M:SS``) +
  // the tooltip text + the React key (bucket index, since
  // all points share the same fight id).
  const chartPoints: TimelineChartPoint[] = useMemo(
    () =>
      points.map((p, i) => {
        const startLabel = formatSecondsLabel(p.window_start_ms);
        const endLabel = formatSecondsLabel(p.window_end_ms);
        return {
          series: [p.total_damage, p.total_healing, p.total_buff_removal],
          key: `bucket-${i}`,
          xLabel: startLabel,
          tooltip:
            `${startLabel}–${endLabel} · bucket ${i + 1}/${points.length}\n` +
            `Damage: ${p.total_damage.toLocaleString("en-US")}\n` +
            `Healing: ${p.total_healing.toLocaleString("en-US")}\n` +
            `Strip: ${p.total_buff_removal.toLocaleString("en-US")}`,
        };
      }),
    [points],
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
