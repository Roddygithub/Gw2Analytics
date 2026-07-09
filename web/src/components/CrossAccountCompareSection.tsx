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
 *   panel ("No timeline data available for comparison.").
 * - 422 from the gateway (e.g. bucket=toggle hit a
 *   server-side validation) -> the section surfaces the
 *   error via :func:`formatApiError` and keeps the last
 *   successful chart rendered (no flash of empty
 *   state).
 * - 5xx from the gateway -> same handler.
 */

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

const CAPTION_STYLE: React.CSSProperties = {
  fontSize: 12,
  opacity: 0.7,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

const ERROR_STYLE: React.CSSProperties = {
  fontSize: 13,
  color: "var(--accent)",
};

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
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
      aria-label="Cross-account comparison timeline"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>
          Comparison timeline
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
        style={{ display: "flex", gap: 6, flexWrap: "wrap" }}
        role="list"
        aria-label="Accounts in comparison"
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
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
        role="group"
        aria-label="Timeline controls"
      >
        {/* Metric radio: Damage / Healing / Buff removal */}
        <div
          style={{ display: "flex", alignItems: "center", gap: 4 }}
          role="radiogroup"
          aria-label="Comparison metric"
        >
          {(["damage", "healing", "strip"] as const).map((m) => (
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
              aria-label={`${m} metric`}
              aria-pressed={metric === m}
            >
              {m === "strip" ? "Strip" : m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          ))}
        </div>

        {/* Scale toggle: Linear / Log */}
        <div
          style={{ display: "flex", alignItems: "center", gap: 4 }}
          role="group"
          aria-label="Y-axis scale"
        >
          <button
            type="button"
            onClick={() => setScale("linear")}
            style={
              scale === "linear" ? BUTTON_ACTIVE_STYLE : BUTTON_STYLE
            }
            aria-label="Linear Y-axis scale"
            aria-pressed={scale === "linear"}
          >
            Linear
          </button>
          <button
            type="button"
            onClick={() => setScale("log")}
            style={scale === "log" ? BUTTON_ACTIVE_STYLE : BUTTON_STYLE}
            aria-label="Logarithmic Y-axis scale"
            aria-pressed={scale === "log"}
          >
            Log
          </button>
        </div>

        {/* Bucket toggle: Per fight / Per day */}
        <div
          style={{ display: "flex", alignItems: "center", gap: 4 }}
          role="group"
          aria-label="Bucketing"
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
            aria-label="Per-fight bucketing"
            aria-pressed={bucket === "fight"}
          >
            Per fight
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
            aria-label="Per-day bucketing"
            aria-pressed={bucket === "day"}
          >
            Per day
          </button>
        </div>

        {/* TZ selector (only meaningful in day bucket; the
            changeTz handler auto-switches to day) */}
        <div
          style={{ display: "flex", alignItems: "center", gap: 4 }}
          role="group"
          aria-label="Timezone (day-bucketing)"
        >
          <select
            data-testid="compare-timezone-selector"
            aria-label="Day-bucket timezone (region/city)"
            value={tz}
            onChange={changeTz}
            disabled={isLoading}
            style={{
              padding: "4px 8px",
              fontSize: 12,
              border: "1px solid var(--accent)",
              borderRadius: 4,
              background: "transparent",
              color: "var(--accent)",
              fontFamily:
                "var(--font-geist-sans), Arial, Helvetica, sans-serif",
              cursor: "pointer",
            }}
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
