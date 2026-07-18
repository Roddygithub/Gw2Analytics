"use client";

/**
 * v0.10.0 plan 032: Client Component wrapper for the
 * cross-account comparison timeline.
 *
 * The parent :class:`ComparePage` is a Server Component
 * that fetches the FIRST page (default ``bucket=day``) of
 * the compare timeline on the server, so the chart is
 * visible at first paint and the URL is permalinkable.
 * This Client Component owns the metric / scale / bucket /
 * tz toggles: clicking any of them re-fetches with the
 * new value via :func:`fetchPlayerCompareTimeline` and
 * re-renders the chart.
 *
 * Why a Client Component for the section (not the page)
 * =====================================================
 * Same pattern as :class:`PlayerTimelineSection`: the
 * page is a Server Component for the initial data fetch
 * (so the URL is permalinkable + the chart renders on
 * first paint with zero client fetches). Only the
 * toggle state is client-side.
 *
 * Account chip UX
 * ===============
 * Each selected account is rendered as a "chip" with the
 * account name (last-seen char-name preferred, fall back
 * to ``account_name``) + a remove button. The chip
 * pattern matches the per-account timeline's
 * "Showing N of M fights" caption + the day-bucket
 * toggle -- a familiar affordance for an analyst who
 * has read the per-account page.
 *
 * Error + empty handling
 * ======================
 * - ``series`` empty list -> the chart's empty-state
 *   panel (uses the centralised
 *   :const:`CROSS_ACCOUNT_TIMELINE_EMPTY_STATE` string
 *   so the chart and section agree on the empty-state
 *   phrase).
 * - 422 from the gateway (e.g. bucket=toggle hit a
 *   server-side validation) -> the section surfaces the
 *   error via :func:`formatApiError` and keeps the last
 *   successful chart rendered (no flash of empty
 *   state).
 * - 5xx from the gateway -> same handler.
 *
 * v0.10.22-night-mode-2: all inline UI affordances (the
 * 13+ aria-label / button-text / chip-list / radio-group
 * literals) are imported from the new
 * `@/lib/copy/cross-account-timeline` sub-module. The
 * per-component single-concern pattern from the Phase
 * split landing carries through -- this component's
 * affordances are OWNED by this constant set, not the
 * kitchen-sink module.
 */
import React from "react";

import { useState } from "react";
import {
  fetchPlayerCompareTimeline,
  formatApiError,
  type CrossAccountTimelineSeries,
} from "@/lib/api";
import {
  CrossAccountTimelineChart,
  type CrossAccountMetric,
  type CrossAccountScale,
} from "@/components/CrossAccountTimelineChart";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import {
  CAPTION_STYLE,
  CONTROLS_ROW_STYLE,
  HEADER_ROW_STYLE,
  HEADING_STYLE,
  RADIO_GROUP_STYLE,
  SECTION_STYLE,
  SELECT_STYLE,
} from "@/shared/styles";
import {
  CROSS_ACCOUNT_TIMELINE_BUCKET_PER_DAY,
  CROSS_ACCOUNT_TIMELINE_BUCKET_PER_DAY_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_BUCKET_PER_FIGHT,
  CROSS_ACCOUNT_TIMELINE_BUCKET_PER_FIGHT_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_BUCKETING_GROUP_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_CHIPS_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_CONTROLS_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_HEADING,
  CROSS_ACCOUNT_TIMELINE_LINEAR,
  CROSS_ACCOUNT_TIMELINE_LINEAR_BUTTON_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_LOG,
  CROSS_ACCOUNT_TIMELINE_LOG_BUTTON_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_GROUP_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_LABEL,
  CROSS_ACCOUNT_TIMELINE_SCALE_GROUP_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_SECTION_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_TIMEZONE_GROUP_ARIA_LABEL,
  CROSS_ACCOUNT_TIMELINE_TZ_SELECTOR_ARIA_LABEL,
} from "@/lib/copy/cross-account-timeline";

const BUTTON_STYLE: React.CSSProperties = {
  padding: "4px 12px",
  fontSize: 12,
  border: "1px solid var(--accent)",
  borderRadius: 4,
  background: "transparent",
  color: "var(--accent)",
  cursor: "pointer",
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};
const BUTTON_ACTIVE_STYLE: React.CSSProperties = {
  ...BUTTON_STYLE,
  background: "var(--accent)",
  color: "var(--background)",
};
const BUTTON_DISABLED_STYLE: React.CSSProperties = {
  ...BUTTON_STYLE,
  opacity: 0.5,
  cursor: "not-allowed",
};

const CHIP_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "4px 8px",
  fontSize: 12,
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--surface)",
  color: "var(--foreground)",
  fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
};

const ERROR_STYLE: React.CSSProperties = {
  fontSize: 13,
  color: "var(--accent)",
};

const CHIPS_CONTAINER_STYLE: React.CSSProperties = {
  display: "flex",
  gap: 6,
  flexWrap: "wrap",
};

// Per-metric display-label + aria-label lookup tables. Restore the
// pre-sweep `.map()` shape (over the union of 3 metric values) so the
// metric radio block is a single rendered iteration rather than 3
// explicit <button> blocks. Each lookup entries routes through the
// centraliSed CROSS_ACCOUNT_TIMELINE_* constants -- adding/renaming a
// metric is a single-line edit in BOTH the lookup AND the sub-module.
const METRIC_RADIO_LABELS: Record<CrossAccountMetric, string> = {
  damage: CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_LABEL,
  healing: CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_LABEL,
  strip: CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_LABEL,
};
const METRIC_RADIO_ARIA_LABELS: Record<CrossAccountMetric, string> = {
  damage: CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_ARIA_LABEL,
  healing: CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_ARIA_LABEL,
  strip: CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_ARIA_LABEL,
};
const METRICS: ReadonlyArray<CrossAccountMetric> = [
  "damage",
  "healing",
  "strip",
];

export function CrossAccountCompareSection({
  initialAccounts,
  initialSeries,
  initialBucket = "day",
  initialTz = "UTC",
}: {
  initialAccounts: string[];
  initialSeries: CrossAccountTimelineSeries[];
  initialBucket?: "fight" | "day";
  initialTz?: string;
}) {
  const [accounts] = useState<string[]>(initialAccounts);
  const [series, setSeries] = useState<CrossAccountTimelineSeries[]>(initialSeries);
  const [metric, setMetric] = useState<CrossAccountMetric>("damage");
  const [scale, setScale] = useState<CrossAccountScale>("log");
  const [bucket, setBucket] = useState<"fight" | "day">(initialBucket);
  const [tz, setTz] = useState<string>(initialTz);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Total points across all series (caption surface).
  const totalPoints = series.reduce(
    (acc, s) => acc + s.points.length,
    0,
  );

  const refetch = async (next: {
    bucket?: "fight" | "day";
    tz?: string;
  }) => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await fetchPlayerCompareTimeline(accounts, next);
      setSeries(response);
    } catch (err) {
      setLoadError(formatApiError(err));
    } finally {
      setIsLoading(false);
    }
  };

  const changeBucket = (next: "fight" | "day") => {
    if (next === bucket || isLoading) return;
    setBucket(next);
    void refetch({ bucket: next, tz });
  };

  const changeTz = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const nextTz = event.target.value;
    if (nextTz === tz || isLoading) return;
    setTz(nextTz);
    // TZ is only meaningful in day bucket -- auto-switch
    // the bucket to keep the change visible (mirrors the
    // per-account timeline's ``changeTz`` contract).
    if (bucket !== "day") {
      setBucket("day");
    }
    void refetch({ bucket: "day", tz: nextTz });
  };

  // v0.10.0 ships read-only chips (see the chip block
  // above). The remove affordance is a v0.10.X followup;
  // the analyst can change the comparison set by editing
  // the URL search params (e.g. drop an account by
  // removing its ``&accounts=...`` segment).

  return (
    <section
      style={SECTION_STYLE}
      aria-label={CROSS_ACCOUNT_TIMELINE_SECTION_ARIA_LABEL}
    >
      <div style={HEADER_ROW_STYLE}>
        <h2 style={HEADING_STYLE}>
          {CROSS_ACCOUNT_TIMELINE_HEADING}
        </h2>
        <span style={CAPTION_STYLE}>
          Comparing {accounts.length} accounts &middot;{" "}
          {totalPoints} {bucket === "day" ? "day-points" : "fight-points"}
        </span>
      </div>

      {/* Account chips: each selected account as a non-removable
          label. v0.10.0 ships read-only chips (the remove
          affordance is a v0.10.X followup -- the v0.10.0
          surface lets the analyst set the comparison via
          URL search params, but does NOT provide in-page
          add/remove UI; the chips are pure status
          indicators). The full in-page add/remove UX is
          ~50 LoC and is tracked as a v0.10.X followup. */}
      <div
        style={CHIPS_CONTAINER_STYLE}
        role="list"
        aria-label={CROSS_ACCOUNT_TIMELINE_CHIPS_ARIA_LABEL}
      >
        {accounts.map((a) => {
          const seriesEntry = series.find((s) => s.account_name === a);
          const label = seriesEntry?.name || a;
          return (
            <span key={a} style={CHIP_STYLE} role="listitem">
              {label}
            </span>
          );
        })}
      </div>

      {/* Toggles: metric (radio) + scale + bucket + tz */}
      <div
        style={CONTROLS_ROW_STYLE}
        role="group"
        aria-label={CROSS_ACCOUNT_TIMELINE_CONTROLS_ARIA_LABEL}
      >
        {/* Metric radio: Damage / Healing / Buff removal */}
        <div
          style={RADIO_GROUP_STYLE}
          role="radiogroup"
          aria-label={CROSS_ACCOUNT_TIMELINE_METRIC_GROUP_ARIA_LABEL}
        >
          {METRICS.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMetric(m)}
              disabled={isLoading}
              style={
                isLoading
                  ? BUTTON_DISABLED_STYLE
                  : metric === m
                    ? BUTTON_ACTIVE_STYLE
                    : BUTTON_STYLE
              }
              aria-label={METRIC_RADIO_ARIA_LABELS[m]}
              aria-pressed={metric === m}
            >
              {METRIC_RADIO_LABELS[m]}
            </button>
          ))}
        </div>

        {/* Scale toggle: Linear / Log */}
        <div
          style={RADIO_GROUP_STYLE}
          role="group"
          aria-label={CROSS_ACCOUNT_TIMELINE_SCALE_GROUP_ARIA_LABEL}
        >
          <button
            type="button"
            onClick={() => setScale("linear")}
            style={
              scale === "linear" ? BUTTON_ACTIVE_STYLE : BUTTON_STYLE
            }
            aria-label={CROSS_ACCOUNT_TIMELINE_LINEAR_BUTTON_ARIA_LABEL}
            aria-pressed={scale === "linear"}
          >
            {CROSS_ACCOUNT_TIMELINE_LINEAR}
          </button>
          <button
            type="button"
            onClick={() => setScale("log")}
            style={scale === "log" ? BUTTON_ACTIVE_STYLE : BUTTON_STYLE}
            aria-label={CROSS_ACCOUNT_TIMELINE_LOG_BUTTON_ARIA_LABEL}
            aria-pressed={scale === "log"}
          >
            {CROSS_ACCOUNT_TIMELINE_LOG}
          </button>
        </div>

        {/* Bucket toggle: Per fight / Per day */}
        <div
          style={RADIO_GROUP_STYLE}
          role="group"
          aria-label={CROSS_ACCOUNT_TIMELINE_BUCKETING_GROUP_ARIA_LABEL}
        >
          <button
            type="button"
            onClick={() => changeBucket("fight")}
            disabled={isLoading || bucket === "fight"}
            style={
              isLoading
                ? BUTTON_DISABLED_STYLE
                : bucket === "fight"
                  ? BUTTON_ACTIVE_STYLE
                  : BUTTON_STYLE
            }
            aria-label={CROSS_ACCOUNT_TIMELINE_BUCKET_PER_FIGHT_ARIA_LABEL}
            aria-pressed={bucket === "fight"}
          >
            {CROSS_ACCOUNT_TIMELINE_BUCKET_PER_FIGHT}
          </button>
          <button
            type="button"
            onClick={() => changeBucket("day")}
            disabled={isLoading || bucket === "day"}
            style={
              isLoading
                ? BUTTON_DISABLED_STYLE
                : bucket === "day"
                  ? BUTTON_ACTIVE_STYLE
                  : BUTTON_STYLE
            }
            aria-label={CROSS_ACCOUNT_TIMELINE_BUCKET_PER_DAY_ARIA_LABEL}
            aria-pressed={bucket === "day"}
          >
            {CROSS_ACCOUNT_TIMELINE_BUCKET_PER_DAY}
          </button>
        </div>

        {/* TZ selector (only meaningful in day bucket; the
            changeTz handler auto-switches to day) */}
        <div
          style={RADIO_GROUP_STYLE}
          role="group"
          aria-label={CROSS_ACCOUNT_TIMELINE_TIMEZONE_GROUP_ARIA_LABEL}
        >
          <select
            data-testid="compare-timezone-selector"
            aria-label={CROSS_ACCOUNT_TIMELINE_TZ_SELECTOR_ARIA_LABEL}
            value={tz}
            onChange={changeTz}
            disabled={isLoading}
            style={SELECT_STYLE}
          >
            {TIMEZONE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.shortLabel ?? opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <CrossAccountTimelineChart series={series} metric={metric} scale={scale} />

      {loadError && <span style={ERROR_STYLE}>{loadError}</span>}
    </section>
  );
}
