/**
 * v0.8.9 of web (plan/002): Server Component wrapper for the
 * per-fight timeline section on the ``/fights/[id]`` drill-down
 * page.
 *
 * v0.10.3 plan 083 Feature 3A refactor: the section becomes a
 * tabbed wrapper exposing TWO views:
 *
 * - "Aggregated" (default): the per-fight timeline
 *   (:class:`PerFightTimelineChart`) -- 3 stacked line series
 *   (damage / healing / buff-removal) for the WHOLE fight.
 *   This is the "what happened in this fight" overview.
 * - "Per-player": the per-player timeline
 *   (:class:`PerPlayerTimelineChart`) -- N stacked line
 *   series (one per player) for the SELECTED metric
 *   (damage / healing / strip, toggled inside the chart).
 *   This is the "who did what" breakdown.
 *
 * Why TABS (vs two separate sections)
 * ===================================
 * The 2 views share the same underlying data (the events
 * blob, the bucket grid, the window_s) so the analyst
 * frequently wants to flip between them. Two separate
 * sections would force the page to scroll past the
 * aggregated chart to reach the per-player chart, and
 * would not correlate visually. A tabbed section keeps
 * the chart footprint compact + lets the analyst flip
 * without losing the chart's place in the page.
 *
 * Why CLIENT-side tab state (vs URL state)
 * ========================================
 * The tab is a transient filter, not a shareable view --
 * the URL stays "the per-fight timeline section" with no
 * ``?tab=`` query param. Bookmarkability is preserved at
 * the section level (the URL is always the
 * "per-fight-timeline section"), and the tab state resets
 * on page load. URL state would inflate the URL with a
 * query param that adds no semantic value (an analyst
 * bookmarking the page wants the fight, not the active
 * tab). The metric + top-N selectors inside the per-player
 * chart follow the same pattern (Client-local state, no
 * URL param).
 *
 * Empty + unavailable handling
 * ============================
 * - ``timeline === null`` AND ``playerTimeline === null``
 *   -> "Per-fight timeline unavailable" caption (both
 *   endpoints failed, e.g. a transient blob corruption
 *   that the upstream ``Promise.allSettled`` did not
 *   recover from).
 * - ``timeline !== null`` AND ``playerTimeline === null``
 *   -> aggregated view shows, per-player view is
 *   disabled with a "Per-player timeline unavailable"
 *   caption on the tab. The aggregated view is the
 *   primary surface so a transient per-player failure
 *   does not blank the section.
 * - ``timeline === null`` AND ``playerTimeline !== null``
 *   -> per-player view shows (the less-common failure
 *   mode), aggregated view is disabled. Symmetric to the
 *   above.
 * - Both empty-state captions are explicit so the analyst
 *   knows which view is missing and why.
 *
 * Why a wrapper section (vs inlining in the page)
 * ===============================================
 * The page already imports 7+ components. Adding the
 * tabbed timeline logic in the page would push it past
 * the 300-line "fat Server Component" threshold that's
 * hard to test. The wrapper:
 *
 * 1. Renders the section heading + caption.
 * 2. Manages the tab state (the "Aggregated" / "Per-player"
 *    toggle).
 * 3. Renders the appropriate chart based on the active
 *    tab + the data availability flags.
 * 4. Renders the empty-state panels when the upstream
 *    data is missing.
 */

"use client";
import React from "react";

import { useState } from "react";
import { PerFightTimelineChart } from "@/components/PerFightTimelineChart";
import { PerPlayerTimelineChart } from "@/components/PerPlayerTimelineChart";
import type { FightTimeline, FightPlayerTimeline } from "@/lib/api";
import { CAPTION_STYLE, HEADING_STYLE, SECTION_STYLE } from "@/shared/styles";

type Tab = "aggregated" | "per_player";

const TAB_STYLE_BASE: React.CSSProperties = {
  padding: "6px 12px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  fontSize: 13,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
  cursor: "pointer",
  background: "var(--surface)",
  color: "var(--foreground)",
};

const TAB_STYLE_ACTIVE: React.CSSProperties = {
  ...TAB_STYLE_BASE,
  background: "var(--accent)",
  color: "var(--accent-foreground, #fff)",
  borderColor: "var(--accent)",
};

const TAB_STYLE_DISABLED: React.CSSProperties = {
  ...TAB_STYLE_BASE,
  opacity: 0.4,
  cursor: "not-allowed",
};

const HEADER_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 12,
  flexWrap: "wrap",
};

const TAB_CONTAINER_STYLE: React.CSSProperties = {
  display: "inline-flex",
  gap: 8,
};

const CAPTION_DETAIL_STYLE: React.CSSProperties = {
  opacity: 0.7,
  fontSize: 13,
};

export function PerFightTimelineSection({
  timeline,
  playerTimeline,
}: {
  timeline: FightTimeline | null;
  playerTimeline: FightPlayerTimeline | null;
}) {
  const [activeTab, setActiveTab] = useState<Tab>("aggregated");

  const aggregatedDisabled = timeline === null;
  const perPlayerDisabled = playerTimeline === null;

  return (
    <section style={SECTION_STYLE}>
      <div style={HEADER_ROW_STYLE}>
        <h2 style={HEADING_STYLE}>Per-fight timeline</h2>
        <div style={TAB_CONTAINER_STYLE}>
          <button
            type="button"
            style={
              aggregatedDisabled
                ? TAB_STYLE_DISABLED
                : activeTab === "aggregated"
                  ? TAB_STYLE_ACTIVE
                  : TAB_STYLE_BASE
            }
            disabled={aggregatedDisabled}
            onClick={() => setActiveTab("aggregated")}
          >
            Aggregated
          </button>
          <button
            type="button"
            style={
              perPlayerDisabled
                ? TAB_STYLE_DISABLED
                : activeTab === "per_player"
                  ? TAB_STYLE_ACTIVE
                  : TAB_STYLE_BASE
            }
            disabled={perPlayerDisabled}
            onClick={() => setActiveTab("per_player")}
          >
            Per-player
          </button>
        </div>
      </div>

      {timeline === null && playerTimeline === null ? (
        <p style={CAPTION_STYLE}>Per-fight timeline unavailable.</p>
      ) : activeTab === "aggregated" ? (
        timeline === null ? (
          <p style={CAPTION_STYLE}>Aggregated timeline unavailable.</p>
        ) : (
          <>
            <p style={CAPTION_DETAIL_STYLE}>
              Showing {timeline.points.length} bucket
              {timeline.points.length === 1 ? "" : "s"} ({timeline.window_s}
              -second window, {timeline.duration_s.toFixed(2)} s duration)
            </p>
            <PerFightTimelineChart points={timeline.points} />
          </>
        )
      ) : playerTimeline === null ? (
        <p style={CAPTION_STYLE}>Per-player timeline unavailable.</p>
      ) : (
        <>
          <p style={CAPTION_DETAIL_STYLE}>
            Showing {playerTimeline.series.length} player
            {playerTimeline.series.length === 1 ? "" : "s"} (
            {playerTimeline.window_s}-second window,{" "}
            {playerTimeline.duration_s.toFixed(2)} s duration)
          </p>
          <PerPlayerTimelineChart
            series={playerTimeline.series}
            windowS={playerTimeline.window_s}
            durationS={playerTimeline.duration_s}
          />
        </>
      )}
    </section>
  );
}
