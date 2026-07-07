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

import { useState } from "react";
import { fetchPlayerTimeline, formatApiError, type PlayerTimeline } from "@/lib/api";
import { PlayerTimelineChart } from "@/components/PlayerTimelineChart";

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

export function PlayerTimelineSection({
  accountName,
  initialTimeline,
}: {
  accountName: string;
  initialTimeline: PlayerTimeline;
}) {
  // The initial data comes from the Server Component (parent page).
  // We track ``timeline`` in state so "Load more" can append pages
  // without re-fetching the first page.
  const [timeline, setTimeline] = useState<PlayerTimeline>(initialTimeline);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const hasMore = timeline.points.length < timeline.total;

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

  return (
    <section
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
      aria-label="Per-account historical timeline"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Historical timeline</h2>
        <span style={CAPTION_STYLE}>
          Showing {timeline.points.length} of {timeline.total} fights
        </span>
      </div>
      <PlayerTimelineChart points={timeline.points} />
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
            hasMore ? "Load more timeline points" : "No more timeline points"
          }
        >
          {isLoading
            ? "Loading\u2026"
            : hasMore
              ? "Load more"
              : "All fights loaded"}
        </button>
        {loadError && <span style={ERROR_STYLE}>{loadError}</span>}
      </div>
    </section>
  );
}
