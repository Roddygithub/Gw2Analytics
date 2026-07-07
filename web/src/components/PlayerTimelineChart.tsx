/**
 * v0.8.0 of web: inline SVG line chart for the per-account
 * historical timeline.
 *
 * v0.9.0 plan/001 refactor: this component is now a THIN
 * WRAPPER around the shared :class:`TimelineChart` base. The
 * wrapper owns the data-shape concerns (mapping
 * :class:`PlayerTimelinePoint` to the flat
 * :class:`TimelineChartPoint` shape, formatting the X-axis
 * labels in ``MM/DD HH:MM`` or ``MM/DD``, building the
 * tooltip text, picking ``fight_id`` as the React key). The
 * shared base owns the SVG render, the per-series
 * normalisation, the linear/log scale, the X-axis label
 * sampling, the legend, and the empty-state panel.
 *
 * Why per-series 0-100% normalisation (linear mode)
 * ==================================================
 * See :class:`TimelineChart` for the full rationale. Short
 * version: damage (10k-100k magnitude) would visually crush
 * strip (0-500 magnitude) on a shared absolute axis, making
 * the strip trend invisible. The "Showing N of M fights"
 * caption on the parent section surfaces the absolute
 * totals.
 *
 * Why a thin wrapper (vs duplicating the SVG render)
 * ==================================================
 * Pre-v0.9.0 this component had ~250 lines of TSX, with ~120
 * lines of near-identical rendering logic to the per-fight
 * timeline (:class:`PerFightTimelineChart`). v0.9.0 plan/001
 * single-sources the rendering in :class:`TimelineChart`;
 * the 2 wrappers are ~80 lines each. The public prop
 * interface is unchanged so the page-level consumer doesn't
 * need to change.
 *
 * v0.8.1 of the API: day-bucketed points carry ``started_at``
 * at UTC midnight, so the X-axis can render ``MM/DD``
 * instead of ``MM/DD HH:MM`` when the analyst switches to
 * ``?bucket=day``. The detection is a single ``.every()``
 * walk over the points (cheap; O(n) on the points list,
 * bounded by the route's ``limit <= 100``).
 */

"use client";

import { useMemo } from "react";
import type { PlayerTimelinePoint } from "@/lib/api";
import { TimelineChart, type TimelineChartPoint } from "@/components/TimelineChart";

export { buildTimelineLayout, formatLogTick } from "@/components/TimelineChart";

/**
 * Explicit ``"en-US"`` locale (NOT ``undefined``) so the
 * server (Node.js) and the client (browser) agree on the
 * format string. ``undefined`` would pick the system locale
 * (typically ``"C"`` or ``"en-US"`` on Node.js, the user's
 * browser locale on the client) and cause a React hydration
 * mismatch when the two disagree -- e.g. ``"07/07/26, 12:00"``
 * on one side and ``"07/07/2026, 12:00 pm"`` on the other.
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

export type TimelineScale = "linear" | "log";

export function PlayerTimelineChart({
  points,
  scale = "linear",
}: {
  points: PlayerTimelinePoint[];
  scale?: TimelineScale;
}) {
  // v0.8.1 of the API: day-bucketed points carry
  // ``started_at`` at UTC midnight, so the X-axis can render
  // ``MM/DD`` only. The detection is a single ``.every()``
  // walk -- cheap (O(n) on the points list, bounded by the
  // route's ``limit <= 100``). Empty arrays keep the full
  // ``MM/DD HH:MM`` format (no chart to render anyway).
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

  // Map PlayerTimelinePoint[] to the flat TimelineChartPoint[]
  // shape the base component consumes. The wrapper owns the
  // X-axis label format + the tooltip text; the base just
  // renders the SVG.
  const chartPoints: TimelineChartPoint[] = useMemo(
    () =>
      points.map((p) => {
        const formattedDate = xAxisFormat.format(new Date(p.started_at));
        return {
          series: [p.total_damage, p.total_healing, p.total_buff_removal],
          key: p.fight_id,
          xLabel: formattedDate,
          tooltip:
            `${p.fight_id} · ${formattedDate}\n` +
            `Damage: ${p.total_damage.toLocaleString("en-US")}\n` +
            `Healing: ${p.total_healing.toLocaleString("en-US")}\n` +
            `Strip: ${p.total_buff_removal.toLocaleString("en-US")}`,
        };
      }),
    [points, xAxisFormat],
  );

  return (
    <TimelineChart
      points={chartPoints}
      scale={scale}
      caption="Per-fight trend (normalized per series)"
      ariaLabel="Per-account historical timeline"
    />
  );
}
