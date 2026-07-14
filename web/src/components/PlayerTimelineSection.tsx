"use client";

/**
 * Client Component wrapper for the per-account historical
 * timeline.
 *
 * The parent :class:`PlayerProfilePage` is a Server Component
 * that fetches the FIRST page (default ``limit=20``) of the
 * timeline on the server, so the chart is visible at first
 * paint and the URL is permalinkable. This Client Component
 * owns the "Load more" affordance: clicking the button
 * appends the next page to the in-memory state via
 * :func:`fetchPlayerTimeline` and re-renders the chart.
 *
 * Why a Client Component for the section (not the page)
 * =====================================================
 * The page is a Server Component for the rest of the data
 * (profile + per-fight breakdown) and stays canonical
 * permalinkable. Only the pagination state is client-side
 * (the "Load more" button is a ``<button onClick={...}>``).
 * The initial data is passed in as a prop from the server
 * so the section renders on first paint with zero client
 * fetches -- the typical "RSC-first" pattern from the Next.js
 * 15+ App Router docs.
 *
 * Error + empty handling
 * ======================
 * - ``total === 0`` or empty ``points`` array -> the section
 *   renders the chart with zero points (the chart itself
 *   shows the "No timeline data available." empty-state
 *   panel).
 * - fetch error on "Load more" -> the section surfaces the
 *   error via :func:`formatApiError` and disables the button
 *   until the user reloads the page. We do NOT auto-retry
 *   (the upstream gateway might be wedged; auto-retry would
 *   just stack the load).
 * - the next page returns ``points.length === 0`` (e.g. the
 *   user already loaded the last page) -> the section
 *   hides the "Load more" button via the ``hasMore`` flag.
 */

import { useEffect, useState } from "react";
import { fetchPlayerTimeline, formatApiError, type PlayerTimeline } from "@/lib/api";
import { PlayerTimelineChart, type TimelineScale } from "@/components/PlayerTimelineChart";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import {
  PLAYER_TIMELINE_ALL_LOADED_DAYS,
  PLAYER_TIMELINE_ALL_LOADED_FIGHTS,
  PLAYER_TIMELINE_BUCKET_PER_DAY,
  PLAYER_TIMELINE_BUCKET_PER_DAY_ARIA_LABEL,
  PLAYER_TIMELINE_BUCKET_PER_FIGHT,
  PLAYER_TIMELINE_BUCKET_PER_FIGHT_ARIA_LABEL,
  PLAYER_TIMELINE_HEADING,
  PLAYER_TIMELINE_LOAD_MORE,
  PLAYER_TIMELINE_LOAD_MORE_ARIA_LABEL,
  PLAYER_TIMELINE_LOADING,
  PLAYER_TIMELINE_NO_MORE_ARIA_LABEL,
  PLAYER_TIMELINE_SECTION_ARIA_LABEL,
} from "@/lib/copy/error-messages";

const BUTTON_STYLE: React.CSSProperties = {
  padding: "8px 16px",
  border: "1px solid var(--accent)",
  borderRadius: 4,
  background: "transparent",
  color: "var(--accent)",
  fontSize: 13,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
  cursor: "pointer",
};

const BUTTON_DISABLED_STYLE: React.CSSProperties = {
  ...BUTTON_STYLE,
  opacity: 0.5,
  cursor: "not-allowed",
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

// v0.8.1 of web: the bucket toggle (Per fight / Per day). The
// inactive style matches the Load-more button so the two
// affordances read as siblings; the active style swaps the
// background to the accent colour so the analyst sees which
// bucketing is currently rendered.
const BUCKET_BUTTON_STYLE: React.CSSProperties = {
  padding: "4px 12px",
  fontSize: 12,
  border: "1px solid var(--accent)",
  borderRadius: 4,
  background: "transparent",
  color: "var(--accent)",
  cursor: "pointer",
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};
const BUCKET_BUTTON_ACTIVE_STYLE: React.CSSProperties = {
  ...BUCKET_BUTTON_STYLE,
  background: "var(--accent)",
  color: "var(--background)",
};
const BUCKET_BUTTON_DISABLED_STYLE: React.CSSProperties = {
  ...BUCKET_BUTTON_STYLE,
  opacity: 0.5,
  cursor: "not-allowed",
};

// v0.8.2 of web: the scale toggle (Linear / Log). Same
// visual style as the bucket toggle (BUCKET_BUTTON_STYLE +
// BUCKET_BUTTON_ACTIVE_STYLE) so the two affordances read
// as siblings. The Linear mode is the existing per-series
// 0-100% normalisation; the Log mode is a shared log
// Y-axis so a 1M damage and a 50 strip are both visible on
// the same axis (the original ROADMAP item).
const SCALE_TOGGLE_STORAGE_KEY = "gw2analytics:timeline-scale";

function readStoredScale(): TimelineScale {
  if (typeof window === "undefined") {
    return "linear";
  }
  try {
    const raw = window.localStorage.getItem(SCALE_TOGGLE_STORAGE_KEY);
    if (raw === "linear" || raw === "log") {
      return raw;
    }
  } catch {
    // ``localStorage`` can throw in private-browsing mode or
    // when the user has disabled it -- fall through to the
    // default. The try/catch is intentionally narrow
    // (``SecurityError`` / ``QuotaExceededError``); anything
    // else is a real bug and we let it propagate.
  }
  return "linear";
}
void readStoredScale; // re-exported for unit testability below

// v0.9.0 of web: the time-zone selector for the day-bucketed
// started_at. Client-state driver (NOT URL-driven): deviating
// from the ProfessionFilter pattern is intentional -- the
// ``bucket`` + ``scale`` toggles are pure client state already,
// so a ``router.push`` would either trigger a redundant server
// re-render OR force an async URL/state sync. The initial TZ
// is read from ``initialTimeline.tz`` (the Server Component
// fetches the first page with the routed-back ``?tz=`` URL
// param + the gateway's TZ-string echo); the subsequent
// selections are pure client state with an auto-switch-to-day
// bucket (see the ``changeTz`` handler). The ``scale`` toggle
// uses ``localStorage`` for return-visit persistence because
// it's a pure visual re-derivation; the ``tz`` field is
// data-affecting (changes the day-bucketed ``started_at``),
// so return-visit persistence would silently diverge from
// the URL on a multi-tab session. Deferring localStorage for
// ``tz`` until the page-level Server Component reads it is
// the v0.9.X roadmap item (~5 LoC change).


export function PlayerTimelineSection({
  accountName,
  initialTimeline,
}: {
  accountName: string;
  initialTimeline: PlayerTimeline;
}) {
  // The initial data comes from the Server Component (parent page).
  // We track ``timeline`` in state so "Load more" can append pages
  // without re-fetching the first page. ``bucket`` tracks the
  // active grouping (Per fight / Per day); v0.8.1 of web wires the
  // toggle so the analyst can switch groupings without leaving the
  // page. Initialised from ``initialTimeline.bucket`` so the
  // section renders on first paint with the correct unit in the
  // caption (the Server Component fetched the first page with the
  // default ``"fight"`` bucket; the toggle then drives a
  // re-fetch when the analyst switches to ``"day"``).
  const [timeline, setTimeline] = useState<PlayerTimeline>(initialTimeline);
  const [bucket, setBucket] = useState<"fight" | "day">(initialTimeline.bucket);
  // v0.8.2 of web: the scale toggle is client-only state
  // (no URL param, no server fetch) because changing scale
  // is a pure re-render of the same data points -- the
  // ``PlayerTimelineChart`` re-derives the Y-axis layout
  // from the existing points array. We initialise to
  // ``"linear"`` (the safe default) and then read the
  // stored value in a ``useEffect`` after mount so the
  // initial render always matches the server output (the
  // server has no ``window`` so it can't read
  // ``localStorage``). This avoids the SSR hydration
  // mismatch that a direct ``useState(readStoredScale)``
  // would cause -- the client would render with the stored
  // value while the server rendered with ``"linear"``,
  // triggering a React warning + a flash of wrong content.
  // The one-extra-render cost is cheaper than the
  // hydration mismatch.
  const [scale, setScale] = useState<TimelineScale>("linear");
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // v0.8.2 of web: read the stored scale AFTER mount
  // (SSR-safe) and write it on every change. The
  // mount-effect runs exactly once (empty deps) and
  // synchronously reads ``localStorage``; the write-effect
  // runs on every ``scale`` change.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- SSR-safe localStorage read on mount is a valid pattern
    setScale(readStoredScale());
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(SCALE_TOGGLE_STORAGE_KEY, scale);
    } catch {
      // Same swallow as the reader -- private-browsing
      // mode / disabled storage is non-fatal. The state
      // still updates for the current session.
    }
  }, [scale]);

  // v0.9.0 of web: TZ selector state. Initialised from
  // ``initialTimeline.tz`` (the server-rendered first page
  // already carries the routed-back ``tz`` string) + pure
  // client state thereafter -- the user picks a TZ and the
  // section re-fetches with the new value. No mount-effect
  // override (deliberately -- see the ``TIMEZONE_OPTIONS``
  // const block above for the localStorage deferral
  // rationale).
  const [tz, setTz] = useState<string>(initialTimeline.tz);

  const hasMore = timeline.points.length < timeline.total;
  const unit = bucket === "day" ? "days" : "fights";

  const loadMore = async () => {
    if (isLoading || !hasMore) {
      return;
    }
    setIsLoading(true);
    setLoadError(null);
    try {
      const next = await fetchPlayerTimeline(accountName, {
        limit: timeline.limit,
        offset: timeline.points.length,
        bucket,
        // v0.9.0 of web: forward the client-state TZ so a
        // "Load more" preserves the analyst's selected region
        // (UTC by default; the analyst's last-selected on
        // return visits).
        tz,
      });
      // Defensive de-dup: if the gateway ever returns a
      // fight_id that's already in the in-memory list (e.g.
      // a fight was added to the dataset mid-pagination), we
      // skip it. The list rendering keys on ``fight_id`` so
      // duplicates would React-warn in dev mode.
      const seen = new Set(timeline.points.map((p) => p.fight_id));
      const fresh = next.points.filter((p) => !seen.has(p.fight_id));
      setTimeline({
        ...next,
        points: [...timeline.points, ...fresh],
      });
    } catch (err) {
      setLoadError(formatApiError(err));
    } finally {
      setIsLoading(false);
    }
  };

  // v0.8.1 of web: switch the bucketing on the same page. The
  // route is offset-based so the first page of the new bucket
  // is the canonical starting point (no offset to forward --
  // the route's offset/limit apply to the bucketed points list,
  // not the underlying fight set).
  const changeBucket = async (next: "fight" | "day") => {
    if (next === bucket || isLoading) {
      return;
    }
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await fetchPlayerTimeline(accountName, {
        limit: timeline.limit,
        bucket: next,
        // v0.9.0 of web: forward the client-state TZ so a
        // bucket-toggle stays in the analyst's TZ.
        tz,
      });
      setTimeline(response);
      setBucket(next);
    } catch (err) {
      setLoadError(formatApiError(err));
    } finally {
      setIsLoading(false);
    }
  };

  // v0.9.0 of web: change the TZ for the day-bucketed
  // ``started_at``. Selecting a non-UTC TZ without changing
  // the bucket would be a no-op on the rendered chart (the
  // fight-bucket points have absolute ``started_at``), so the
  // handler auto-switches bucket to "day" -- the canonical
  // mode where TZ matters. The analyst can toggle back to
  // "Per fight" via the existing bucket buttons without
  // losing the TZ (the bucket change above forwards it).
  const changeTz = async (event: React.ChangeEvent<HTMLSelectElement>) => {
    const nextTz = event.target.value;
    if (nextTz === tz || isLoading) {
      return;
    }
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await fetchPlayerTimeline(accountName, {
        limit: timeline.limit,
        bucket: "day", // auto-switch: TZ is only meaningful in day bucket
        tz: nextTz,
      });
      setTimeline(response);
      setTz(nextTz);
      setBucket("day");
    } catch (err) {
      setLoadError(formatApiError(err));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
      aria-label={PLAYER_TIMELINE_SECTION_ARIA_LABEL}
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
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>{PLAYER_TIMELINE_HEADING}</h2>
        <div
          style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}
          role="group"
          aria-label="Timeline controls"
        >
          <span style={CAPTION_STYLE}>
            Showing {timeline.points.length} of {timeline.total} {unit}
          </span>
          {/* v0.8.2 of web: bucketing toggle (Per fight / Per day). */}
          <div
            style={{ display: "flex", alignItems: "center", gap: 4 }}
            role="group"
            aria-label="Timeline bucketing"
          >
            <button
              type="button"
              onClick={() => changeBucket("fight")}
              disabled={isLoading || bucket === "fight"}
              style={
                isLoading
                  ? BUCKET_BUTTON_DISABLED_STYLE
                  : bucket === "fight"
                    ? BUCKET_BUTTON_ACTIVE_STYLE
                    : BUCKET_BUTTON_STYLE
              }
              aria-label={PLAYER_TIMELINE_BUCKET_PER_FIGHT_ARIA_LABEL}
              aria-pressed={bucket === "fight"}
            >
              {PLAYER_TIMELINE_BUCKET_PER_FIGHT}
            </button>
            <button
              type="button"
              onClick={() => changeBucket("day")}
              disabled={isLoading || bucket === "day"}
              style={
                isLoading
                  ? BUCKET_BUTTON_DISABLED_STYLE
                  : bucket === "day"
                    ? BUCKET_BUTTON_ACTIVE_STYLE
                    : BUCKET_BUTTON_STYLE
              }
              aria-label={PLAYER_TIMELINE_BUCKET_PER_DAY_ARIA_LABEL}
              aria-pressed={bucket === "day"}
            >
              {PLAYER_TIMELINE_BUCKET_PER_DAY}
            </button>
          </div>
          {/* v0.8.2 of web: scale toggle (Linear / Log). Pure
              client-side re-render of the same data points --
              no server fetch. The toggle is always enabled
              (no loading state needed) because switching
              scale is a synchronous O(n) re-derivation. */}
          <div
            style={{ display: "flex", alignItems: "center", gap: 4 }}
            role="group"
            aria-label="Timeline Y-axis scale"
          >
            <button
              type="button"
              onClick={() => setScale("linear")}
              style={
                scale === "linear"
                  ? BUCKET_BUTTON_ACTIVE_STYLE
                  : BUCKET_BUTTON_STYLE
              }
              aria-label="Linear Y-axis scale (per-series normalised)"
              aria-pressed={scale === "linear"}
            >
              Linear
            </button>
            <button
              type="button"
              onClick={() => setScale("log")}
              style={
                scale === "log" ? BUCKET_BUTTON_ACTIVE_STYLE : BUCKET_BUTTON_STYLE
              }
              aria-label="Logarithmic Y-axis scale (shared across all 3 series)"
              aria-pressed={scale === "log"}
            >
              Log
            </button>
          </div>
          {/* v0.10.0 plan 032: the TZ selector uses the
              shared ``TIMEZONE_OPTIONS`` catalog from
              ``web/src/lib/timezones.ts`` (extracted in plan
              032 so the per-account + cross-account
              selectors ship the SAME 25 curated IANA zones).
              Auto-switches bucket to "day" on selection
              (see changeTz above). */}
          <div
            style={{ display: "flex", alignItems: "center", gap: 4 }}
            role="group"
            aria-label="Timeline timezone"
          >
            <select
              data-testid="timezone-selector"
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
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
      <PlayerTimelineChart points={timeline.points} scale={scale} />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <button
          type="button"
          onClick={loadMore}
          disabled={!hasMore || isLoading}
          style={
            !hasMore || isLoading ? BUTTON_DISABLED_STYLE : BUTTON_STYLE
          }
          aria-label={
            hasMore
              ? PLAYER_TIMELINE_LOAD_MORE_ARIA_LABEL
              : PLAYER_TIMELINE_NO_MORE_ARIA_LABEL
          }
        >          {isLoading
            ? PLAYER_TIMELINE_LOADING
            : hasMore
              ? PLAYER_TIMELINE_LOAD_MORE
              : bucket === "day"
                ? PLAYER_TIMELINE_ALL_LOADED_DAYS
                : PLAYER_TIMELINE_ALL_LOADED_FIGHTS}
        </button>
        {loadError && <span style={ERROR_STYLE}>{loadError}</span>}
      </div>
    </section>
  );
}
