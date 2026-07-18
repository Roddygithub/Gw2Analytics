/**
 * v0.10.17 D1: BattleReplay Player for the ``/fights/[id]`` drilldown page.
 *
 * PURPOSE
 * =======
 * The :class:`ReplayPlayer` is a Client Component that powers the
 * Replay tab on the per-fight page (a NEW top-level tab added in
 * v0.10.17 alongside the existing Overview tab). The component
 * subscribes to the per-fight timeline rollup (the same
 * ``/api/v1/fights/{id}/timeline?window_s=...`` substrate the
 * page's Overview tab uses for the :class:`PerFightTimelineChart`)
 * and renders a seekable playback interface: a draggable scrubber,
 * a play/pause toggle, a 1x/2x/4x/8x speed toggle, a per-bucket
 * damage + healing + strip roll-up visualisation, and a
 * "current snapshot" panel that surfaces the absolute bucket
 * totals at the scrubber position.
 *
 * SUBSTRATE
 * =========
 * The component receives the :class:`FightTimeline` payload via
 * props (the Server Component page loads it via the existing
 * :func:`fetchCached` call + the :func:`fetchReplayTimeline`
 * wrapper). No independent fetch is fired from the Client
 * Component -- the payload flows from the page's Server Component
 * so the LRU + TTL cache stays warm across the timeline/Replay
 * tab switch.
 *
 * SCOPE BOUNDARY (vs brief deviation, documented)
 * ===============================================
 * The brief asks for a Replay UI that subscribes to the "gzipped
 * events blob" (per-event fidelity: per-skill attribution, per-
 * target attribution within a bucket, sub-bucket scrubbing). The
 * current cycle's hard constraint ("D1 does NOT touch the
 * backend") -- and the absence of a public gateway endpoint that
 * surfaces the raw events blob -- bound the substrate to the
 * per-bucket ``/timeline`` rollup. Per-event fidelity is deferred
 * to a future cycle that ships a ``/events-blob`` gateway
 * endpoint; the only client-side surface change will be to swap
 * the prop type from :class:`FightTimeline` (per-bucket) to an
 * ``EventStream`` (per-event). The control panel + the
 * visualisation logic + the playback engine are substrate-
 * agnostic and will continue to work unchanged.
 *
 * PLAYBACK ENGINE
 * ===============
 * - one ``setInterval`` per ``isPlaying === true`` session, with
 *   an interval of ``window_s * 1000 / speed`` ms
 * - the interval invokes ``setCurrentIndex`` to advance one bucket
 * - when the index reaches the last bucket the engine pauses
 *   automatically (no wrap-around; the analyst presses Reset to
 *   start over)
 * - the ``useEffect`` cleanup clears the interval on unmount or
 *   on any dep change so a slow interval never leaks into a
 *   faster one
 *
 * SCRUBBER
 * ========
 * - an ``<input type="range">`` with ``min=0 max=N-1`` bound to
 *   ``currentIndex``
 *
 * VISUAL (per-bucket horizontal bar chart)
 * ========================================
 * Each bucket is rendered as a width-``BAR_WIDTH_PX`` (14 px)
 * horizontal unit subdivided into 3 side-by-side sub-bars:
 *
 *   - damage (4 px, ``var(--accent)``)
 *   - healing (4 px, ``var(--foreground)`` @ 0.7 opacity)
 *   - strip (4 px, warm orange ``#f59e0b``)
 *
 * Each sub-bar grows from the BOTTOM of the bucket container to
 * its own ``(value / perSeriesMax) * BAR_CHART_HEIGHT_PX`` height.
 * The 3 sub-bars are independent (NOT summed), so the per-series
 * 0-100% normalisation prevents the strip series from being
 * crushed by damage 2 orders of magnitude larger -- the
 * canonical "3 standalone bars" visual intent from the brief.
 *
 * v0.10.17 D1 round-2 fix: an earlier implementation used a
 * "3 stacked segments, positioned ``bottom: 0/N/N+M``" layout
 * with each segment normalised to its own per-series max. That
 * layout silently overflowed the bucket container via
 * ``overflow: hidden`` whenever the per-series maxes occurred at
 * DIFFERENT buckets (because the 3 segment heights summed to
 * > ``BAR_CHART_HEIGHT_PX`` and the top segments were clipped
 * out of view). The fix swaps to horizontal subdivision so the
 * 3 sub-bars render at the SAME y-axis range but different
 * x-axis columns -- correct visual + no overflow risk regardless
 * of which bucket maxes each series.
 *
 * CURRENT-BUCKET SNAPSHOT
 * =======================
 * A responsive 4-cell grid panel that shows the current
 * bucket's absolute damage / healing / strip totals + the
 * ``M:SS--M:SS`` window range.
 *
 * EMPTY / NULL HANDLING
 * =====================
 * - ``timeline === null`` -> "Replay unavailable" caption.
 *   Reaches the user when the ``/timeline`` endpoint failed.
 * - ``timeline.points.length === 0`` -> "Replay unavailable:
 *   zero buckets" caption. Reaches the user when the fight is
 *   shorter than ``window_s`` so the timeline endpoint returned
 *   an empty array (a known parser-edge-case for sub-second
 *   fights).
 */

"use client";
import React from "react";

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type { FightTimeline, PerFightTimelinePoint } from "@/lib/api/fights";
import { formatSecondsLabel } from "@/lib/format";

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------

/**
 * Available playback speeds. 1x / 2x / 4x / 8x covers 25 ms to
 * 60 s bucketed intervals at 5 s window_s; 8x at 5 s window_s
 * advances one bucket every 625 ms (16 fps minimum so the
 * scrubber movement reads smoothly without flicker).
 */
const SPEEDS = [1, 2, 4, 8] as const;
type Speed = (typeof SPEEDS)[number];

/**
 * Per-bucket horizontal unit width (14 px). Subdivided into 3
 * 4 px-wide sub-bars (damage / healing / strip) separated by
 * 1 px gaps so the eye reads them as 3 distinct values rather
 * than a single gradient.
 */
const BAR_WIDTH_PX = 14;
const BAR_SUB_WIDTH_PX = 4;
const BAR_SUB_GAP_PX = 1;
const BAR_GAP_PX = 2;
// Height of the per-bucket bar chart in pixels. Each sub-bar
// grows from the bucket's bottom to a normalised height
// between 0 and ``BAR_CHART_HEIGHT_PX``.
const BAR_CHART_HEIGHT_PX = 120;
const BAR_CHART_PADDING_PX = 8;

// ---------------------------------------------------------------------------
// Style constants
// ---------------------------------------------------------------------------

const REPLAY_SECTION_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  padding: "16px",
  border: "1px solid var(--border)",
  borderRadius: 6,
  background: "var(--surface)",
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const CONTROLS_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  flexWrap: "wrap",
};

const CONTROL_BUTTON_BASE: React.CSSProperties = {
  padding: "6px 12px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  fontSize: 13,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
  cursor: "pointer",
  background: "var(--background)",
  color: "var(--foreground)",
};

const CONTROL_BUTTON_ACTIVE: React.CSSProperties = {
  ...CONTROL_BUTTON_BASE,
  background: "var(--accent)",
  color: "var(--accent-foreground, #fff)",
  border: "1px solid var(--accent)",
};

const SNAPSHOT_PANEL_STYLE: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 12,
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--background)",
};

const SNAPSHOT_CELL_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};

const SNAPSHOT_LABEL_STYLE: React.CSSProperties = {
  fontSize: 11,
  opacity: 0.7,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};

const SNAPSHOT_VALUE_STYLE: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 600,
};

const HEADER_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 12,
  flexWrap: "wrap",
};

const HEADER_TITLE_STYLE: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 600,
  margin: 0,
};

const HEADER_SUBTITLE_STYLE: React.CSSProperties = {
  opacity: 0.7,
  fontSize: 13,
  margin: "4px 0 0 0",
};

const SCRUBBER_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const SCRUBBER_INPUT_STYLE: React.CSSProperties = {
  width: "100%",
  accentColor: "var(--accent)",
};

const SCRUBBER_LABELS_STYLE: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontSize: 12,
  opacity: 0.7,
};

const BAR_CHART_CONTAINER_STYLE: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--background)",
  padding: BAR_CHART_PADDING_PX,
  overflowX: "auto",
};

const LEGEND_STYLE: React.CSSProperties = {
  display: "flex",
  gap: 16,
  fontSize: 12,
  opacity: 0.7,
  flexWrap: "wrap",
};

const INLINE_FLEX_ITEM_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const LEGEND_SWATCH_STYLE: React.CSSProperties = {
  display: "inline-block",
  width: 10,
  height: 10,
  borderRadius: 2,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Compute the per-window tick-stride: the bucket index step
 * at which to drop X-axis labels so the axis reads every Nth
 * bucket rather than every bucket. Capped at 1 so a short
 * replay does NOT skip any labels.
 */
function computeReadoutStep(N: number): number {
  const BAR_TOTAL_PX = BAR_WIDTH_PX + BAR_GAP_PX;
  const chartWidthPx = N * BAR_TOTAL_PX;
  const desiredLabelSpacingPx = 120;
  return Math.max(1, Math.floor(chartWidthPx / desiredLabelSpacingPx));
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface ReplayPlayerProps {
  /**
   * The fight id (used for the section heading + the readout
   * + the analytics-friendly "Replay fight {id}" aria-label).
   * The Server Component page passes this through from the
   * route param.
   */
  fightId: string;
  /**
   * The per-fight timeline rollup fetched by the Server
   * Component page via :func:`fetchCached` (via the
   * :func:`fetchReplayTimeline` wrapper). ``null`` indicates
   * the upstream ``/timeline`` fetch failed.
   */
  timeline: FightTimeline | null;
}

/**
 * Inner component props: ``timeline`` is constrained to
 * non-null here because the outer :class:`ReplayPlayer` has
 * already short-circuited on the null / empty cases.
 *
 * Why a separate type (vs ``Required<ReplayPlayerProps>``)
 * =========================================================
 * ``Required<X>`` narrows OPTIONAL properties to REQUIRED --
 * it does NOT strip ``null``. A type alias that says
 * ``timeline: NonNullable<ReplayPlayerProps["timeline"]>`` is
 * the canonical TypeScript pattern for narrowing nullable
 * fields, so the playback engine's ``timeline.points`` /
 * ``timeline.window_s`` dereferences are statically safe.
 *
 * Without this narrowing the tsc strict-mode check
 * (``ts18047: X is possibly null``) would fail at every
 * ``timeline.X`` access in the inner component body.
 */
type ReplayPlayerInnerProps = {
  fightId: string;
  timeline: FightTimeline;
};

interface BucketBarProps {
  point: PerFightTimelinePoint;
  heights: { damage: number; healing: number; strip: number };
  isCurrent: boolean;
  index: number;
  N: number;
  readoutStep: number;
}

/**
 * Memoised single bucket bar.
 *
 * Extracted so that scrubbing ``currentIndex`` only re-renders
 * the two buckets whose ``isCurrent`` prop actually changes;
 * every other bucket reuses its cached React element.
 */
const BucketBar = memo(function BucketBar({
  point,
  heights,
  isCurrent,
  index,
  N,
  readoutStep,
}: BucketBarProps) {
  const left = index * (BAR_WIDTH_PX + BAR_GAP_PX);
  const title =
    `${formatSecondsLabel(point.window_start_ms)}–${formatSecondsLabel(point.window_end_ms)} · bucket ${index + 1}/${N}\n` +
    `Dmg: ${point.total_damage.toLocaleString("en-US")} · Heal: ${point.total_healing.toLocaleString("en-US")} · Strip: ${point.total_buff_removal.toLocaleString("en-US")}`;

  return (
    <div
      data-testid={isCurrent ? "replay-bar-current" : "replay-bar"}
      title={title}
      style={{
        position: "absolute",
        left,
        top: 0,
        width: BAR_WIDTH_PX,
        height: BAR_CHART_HEIGHT_PX,
        border: isCurrent
          ? "2px solid var(--accent)"
          : "1px solid var(--border)",
        borderRadius: 2,
        background: "var(--surface)",
      }}
    >
      {/* Damage sub-bar (col 0). */}
      <div
        data-testid="replay-bar-damage"
        style={{
          position: "absolute",
          left: 0,
          bottom: 0,
          width: BAR_SUB_WIDTH_PX,
          height: heights.damage,
          background: "var(--accent)",
        }}
      />
      {/* Healing sub-bar (col 1). */}
      <div
        data-testid="replay-bar-healing"
        style={{
          position: "absolute",
          left: BAR_SUB_WIDTH_PX + BAR_SUB_GAP_PX,
          bottom: 0,
          width: BAR_SUB_WIDTH_PX,
          height: heights.healing,
          background: "var(--foreground)",
          opacity: 0.7,
        }}
      />
      {/* Strip sub-bar (col 2). */}
      <div
        data-testid="replay-bar-strip"
        style={{
          position: "absolute",
          left: 2 * (BAR_SUB_WIDTH_PX + BAR_SUB_GAP_PX),
          bottom: 0,
          width: BAR_SUB_WIDTH_PX,
          height: heights.strip,
          background: "#f59e0b",
        }}
      />
      {isCurrent && (
        <span
          style={{
            position: "absolute",
            left: -2,
            top: -22,
            fontSize: 10,
            fontWeight: 600,
            background: "var(--accent)",
            color: "var(--accent-foreground, #fff)",
            padding: "2px 4px",
            borderRadius: 2,
            whiteSpace: "nowrap",
            zIndex: 1,
          }}
        >
          B{index + 1}
        </span>
      )}
      {(index === 0 || index === N - 1 || index % readoutStep === 0) && (
        <span
          style={{
            position: "absolute",
            left: -6,
            bottom: -16,
            fontSize: 9,
            color: "var(--foreground)",
            opacity: 0.6,
            whiteSpace: "nowrap",
          }}
        >
          {formatSecondsLabel(point.window_start_ms)}
        </span>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ReplayPlayer({ fightId, timeline }: ReplayPlayerProps) {
  // ---- Empty-state guard -------------------------------------------------
  if (timeline === null) {
    return (
      <section
        data-testid="replay-unavailable"
        style={REPLAY_SECTION_STYLE}
        aria-label={`Replay unavailable for fight ${fightId}`}
      >
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>
          Replay unavailable
        </h2>
        <p style={{ opacity: 0.7, fontSize: 14, margin: 0 }}>
          The per-fight timeline endpoint failed for fight {fightId}. The
          Overview tab&apos;s timeline section already surfaces the upstream
          error; the Replay tab echoes the same status to keep the two
          surfaces coherent.
        </p>
      </section>
    );
  }
  if (timeline.points.length === 0) {
    return (
      <section
        data-testid="replay-empty"
        style={REPLAY_SECTION_STYLE}
        aria-label={`Replay empty for fight ${fightId}`}
      >
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>
          Replay unavailable: zero buckets
        </h2>
        <p style={{ opacity: 0.7, fontSize: 14, margin: 0 }}>
          The fight was shorter than the {timeline.window_s}-s bucket window.
          This is a known parser-edge-case for sub-second fights; the Overview
          tab&apos;s event-windows table surfaces the same data on a finer
          grid.
        </p>
      </section>
    );
  }
  return <ReplayPlayerInner fightId={fightId} timeline={timeline} />;
}

/**
 * Memoized snapshot panel.
 *
 * Isolating the snapshot prevents control-state updates
 * (play/pause, speed) from re-rendering the stats grid when
 * the current bucket has not changed.
 */
const SnapshotPanel = memo(function SnapshotPanel({
  point,
}: {
  point: PerFightTimelinePoint;
}) {
  return (
    <div data-testid="replay-current-snapshot" style={SNAPSHOT_PANEL_STYLE}>
      <div style={SNAPSHOT_CELL_STYLE}>
        <span style={SNAPSHOT_LABEL_STYLE}>Damage</span>
        <span style={SNAPSHOT_VALUE_STYLE}>
          {point.total_damage.toLocaleString("en-US")}
        </span>
      </div>
      <div style={SNAPSHOT_CELL_STYLE}>
        <span style={SNAPSHOT_LABEL_STYLE}>Healing</span>
        <span style={SNAPSHOT_VALUE_STYLE}>
          {point.total_healing.toLocaleString("en-US")}
        </span>
      </div>
      <div style={SNAPSHOT_CELL_STYLE}>
        <span style={SNAPSHOT_LABEL_STYLE}>Strip</span>
        <span style={SNAPSHOT_VALUE_STYLE}>
          {point.total_buff_removal.toLocaleString("en-US")}
        </span>
      </div>
      <div style={SNAPSHOT_CELL_STYLE}>
        <span style={SNAPSHOT_LABEL_STYLE}>Window</span>
        <span style={SNAPSHOT_VALUE_STYLE}>
          {formatSecondsLabel(point.window_start_ms)}–
          {formatSecondsLabel(point.window_end_ms)}
        </span>
      </div>
    </div>
  );
});

/**
 * Memoized speed button.
 *
 * Extracted so the inline ``onClick`` closure is not
 * re-created for every speed button on every playback tick.
 */
const SpeedButton = memo(function SpeedButton({
  speed,
  isActive,
  onSelect,
}: {
  speed: Speed;
  isActive: boolean;
  onSelect: (s: Speed) => void;
}) {
  return (
    <button
      key={speed}
      type="button"
      onClick={() => onSelect(speed)}
      aria-label={`Set speed to ${speed}x`}
      aria-pressed={isActive}
      data-testid={`replay-speed-${speed}x`}
      style={isActive ? CONTROL_BUTTON_ACTIVE : CONTROL_BUTTON_BASE}
    >
      {speed}x
    </button>
  );
});

/**
 * Static legend. Hoisted to module scope so it is never
 * re-evaluated during playback ticks.
 */
const ReplayLegend = memo(function ReplayLegend() {
  return (
    <div style={LEGEND_STYLE} data-testid="replay-legend">        <span style={INLINE_FLEX_ITEM_STYLE}>
          <span style={{ ...LEGEND_SWATCH_STYLE, background: "var(--accent)" }} />
          Damage
        </span>
        <span style={INLINE_FLEX_ITEM_STYLE}>
          <span
            style={{
              ...LEGEND_SWATCH_STYLE,
              background: "var(--foreground)",
              opacity: 0.7,
            }}
          />
          Healing
        </span>
        <span style={INLINE_FLEX_ITEM_STYLE}>
          <span style={{ ...LEGEND_SWATCH_STYLE, background: "#f59e0b" }} />
          Strip
        </span>
    </div>
  );
});

/**
 * Internal component: the real playback engine. Split out
 * so the empty-state branches above can short-circuit BEFORE
 * the playback hooks execute (a hook called conditionally is
 * a React rules-of-hooks violation; a hook called on a null
 * timeline would also throw on the first dereference).
 */
function ReplayPlayerInner({ fightId, timeline }: ReplayPlayerInnerProps) {
  const points = timeline.points;
  const N = points.length;
  const windowS = timeline.window_s;
  const durationS = timeline.duration_s;

  // ---- Playback state ----------------------------------------------------
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(1);

  // ---- Playback engine ---------------------------------------------------
  useEffect(() => {
    if (!isPlaying || N === 0) return;
    const intervalMs = (windowS * 1000) / speed;
    const id = window.setInterval(() => {
      setCurrentIndex((i) => {
        if (i >= N - 1) {
          // Defer isPlaying-toggle via setTimeout(0) so the
          // setInterval callback's React batch does not call
          // setIsPlaying during the same event as
          // setCurrentIndex. The microtask defer keeps the
          // state-update batch minimal.
          window.setTimeout(() => setIsPlaying(false), 0);
          return N - 1;
        }
        return i + 1;
      });
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [isPlaying, speed, windowS, N]);

  // ---- Derived values ----------------------------------------------------
  const currentPoint: PerFightTimelinePoint | null = points[currentIndex] ?? null;
  const isAtEnd = currentIndex >= N - 1;
  // Per-series global maxes for the bar-chart normalisation.
  // The clamp to 1 mirrors :func:`buildTimelineLayout` so an
  // all-zero series collapses to a flat baseline rather than
  // a divide-by-zero error.
  const { maxDamage, maxHealing, maxStrip } = useMemo(() => {
    let maxDamage = 1;
    let maxHealing = 1;
    let maxStrip = 1;
    for (const p of points) {
      if (p.total_damage > maxDamage) maxDamage = p.total_damage;
      if (p.total_healing > maxHealing) maxHealing = p.total_healing;
      if (p.total_buff_removal > maxStrip) maxStrip = p.total_buff_removal;
    }
    return { maxDamage, maxHealing, maxStrip };
  }, [points]);
  // Bar-chart total width; overflows horizontally on long
  // fights (the bar-chart <div> becomes a horizontal scrolling
  // region via the overflow-x style below).
  const barChartWidth = N * BAR_WIDTH_PX + (N - 1) * BAR_GAP_PX;
  const readoutStep = useMemo(() => computeReadoutStep(N), [N]);

  // Pre-compute per-bucket bar heights so the chart re-renders
  // only when the timeline data or global maxes change, not on
  // every scrubber movement.
  const bucketBars = useMemo(
    () =>
      points.map((p) => ({
        damage:
          (p.total_damage / maxDamage) * BAR_CHART_HEIGHT_PX,
        healing:
          (p.total_healing / maxHealing) * BAR_CHART_HEIGHT_PX,
        strip:
          (p.total_buff_removal / maxStrip) * BAR_CHART_HEIGHT_PX,
      })),
    [points, maxDamage, maxHealing, maxStrip],
  );

  // ---- Handlers ----------------------------------------------------------
  const onScrub = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const v = Number.parseInt(e.target.value, 10);
      if (Number.isFinite(v)) {
        setCurrentIndex(Math.max(0, Math.min(N - 1, v)));
      }
    },
    [N],
  );

  /**
   * Play/pause handler. When the analyst is at the last
   * bucket, pressing Play RESETS to the beginning and starts
   * playing from there -- the auto-pause left the user at the
   * end so a fresh Play must restart. We do NOT auto-resume
   * on the same button press because the auto-pause is a
   * clear "you hit the end" signal and the analyst expects
   * to press Play a second time to restart.
   */
  const onPlayPause = useCallback(() => {
    if (N === 0) return;
    if (isAtEnd) {
      setCurrentIndex(0);
      setIsPlaying(true);
    } else {
      setIsPlaying((p) => !p);
    }
  }, [isAtEnd, N]);

  const onReset = useCallback(() => {
    setCurrentIndex(0);
    setIsPlaying(false);
  }, []);

  const onSelectSpeed = useCallback((s: Speed) => {
    setSpeed(s);
  }, []);

  return (
    <section
      data-testid="replay-player"
      style={REPLAY_SECTION_STYLE}
      aria-label={`Replay fight ${fightId}`}
    >
      <header style={HEADER_STYLE}>
        <div>
          <h2 style={HEADER_TITLE_STYLE}>
            Replay — fight {fightId}
          </h2>
          <p style={HEADER_SUBTITLE_STYLE}>
            {N} bucket{N === 1 ? "" : "s"} · {windowS}-s window ·
            {" "}
            {durationS.toFixed(2)}
            s duration
          </p>
        </div>
      </header>

      {/* Controls row: Play / pause / Reset / speed-toggle */}
      <div style={CONTROLS_ROW_STYLE} data-testid="replay-controls">
        <button
          type="button"
          onClick={onReset}
          aria-label="Reset replay"
          style={CONTROL_BUTTON_BASE}
        >
          ⏮ Reset
        </button>
        <button
          type="button"
          onClick={onPlayPause}
          aria-label={isPlaying ? "Pause replay" : "Play replay"}
          aria-pressed={isPlaying}
          data-testid="replay-play-pause"
          style={CONTROL_BUTTON_ACTIVE}
        >
          {isPlaying ? "❚❚ Pause" : "▶ Play"}
        </button>
        <span style={INLINE_FLEX_ITEM_STYLE}>
          <span style={{ fontSize: 12, opacity: 0.7 }}>Speed:</span>
          {SPEEDS.map((s) => (
            <SpeedButton
              key={s}
              speed={s}
              isActive={speed === s}
              onSelect={onSelectSpeed}
            />
          ))}
        </span>
      </div>

      {/* Scrubber: range input bound to currentIndex */}
      <div style={SCRUBBER_ROW_STYLE} data-testid="replay-scrubber-row">
        <input
          type="range"
          min={0}
          max={N - 1}
          step={1}
          value={currentIndex}
          onChange={onScrub}
          aria-label={`Replay scrubber, position ${currentIndex + 1} of ${N}`}
          aria-valuemin={0}
          aria-valuemax={N - 1}
          aria-valuenow={currentIndex}
          aria-valuetext={currentPoint ? formatSecondsLabel(currentPoint.window_start_ms) : ""}
          data-testid="replay-scrubber"
          style={SCRUBBER_INPUT_STYLE}
        />
        <div style={SCRUBBER_LABELS_STYLE}>
          <span>
            Bucket {currentIndex + 1} / {N}
          </span>
          <span>
            t ={" "}
            {currentPoint
              ? formatSecondsLabel(currentPoint.window_start_ms)
              : "—"}
          </span>
        </div>
      </div>

      {/* Snapshot panel: current bucket's absolute totals. */}
      {currentPoint && <SnapshotPanel point={currentPoint} />}

      {/* Per-bucket bar chart: 14 px-wide bucket subdivided into
          3 side-by-side 4 px-wide sub-bars (damage / healing /
          strip), each normalised to its own per-series global
          max. The 3 sub-bars grow independently from the bottom
          of the bucket so they NEVER sum to more than the bucket
          height (the prior "3 stacked segments" implementation
          DID sum to > bucket height when the per-series maxes
          occurred at different buckets, causing the
          ``overflow: hidden`` parent to silently clip the top
          segments -- fixed by this horizontal subdivision).
          The current bucket gets a brighter border + a "B{i+1}"
          badge floating above the bucket's top-left. Horizontal
          overflow for long fights (>60 buckets fills >720 px). */}
      <div
        data-testid="replay-bar-chart"
        style={BAR_CHART_CONTAINER_STYLE}
        aria-label="Per-bucket damage + healing + strip bar chart"
      >
        <div
          style={{
            position: "relative",
            width: barChartWidth,
            height: BAR_CHART_HEIGHT_PX,
          }}
        >
          {points.map((p, i) => (
            <BucketBar
              key={i}
              point={p}
              heights={bucketBars[i]}
              isCurrent={i === currentIndex}
              index={i}
              N={N}
              readoutStep={readoutStep}
            />
          ))}
        </div>
      </div>

      {/* Legend */}
      <ReplayLegend />
    </section>
  );
}
