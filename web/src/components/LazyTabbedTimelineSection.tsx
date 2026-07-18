/**
 * v0.10.28 plan 162: Client Component wrapper that lazy-loads
 * the per-player timeline (``/timeline/players`` endpoint)
 * AFTER the page hydrates.
 *
 * Why lazy-load (vs server-side fetch in page.tsx)
 * =================================================
 * The ``/timeline/players`` endpoint has ~10s SSR latency
 * (heavy aggregation across all players in the fight).
 * Pre-v0.10.28 the page waited for this endpoint during
 * the SSR critical path, making the entire ``/fights/[id]``
 * page feel broken even when nothing was wrong.
 *
 * Plan 162 splits the timeline render into 2 parts:
 *
 * 1. The ``timeline`` (aggregated view, 3-line series) is
 *    STILL server-side fetched + rendered (it's fast --
 *    typically <500ms -- and is the primary "what happened
 *    in this fight" surface).
 * 2. The ``playerTimeline`` (per-player view, N line
 *    series) is NOW lazy-fetched on mount via this
 *    Client Component. The user sees the aggregated view
 *    immediately + the per-player view streams in 0-10s
 *    later without blocking the page render.
 *
 * Why a wrapper (vs inlining the fetch in PerFightTimelineSection)
 * =================================================================
 * :class:`PerFightTimelineSection` is a Client Component that
 * accepts ``timeline`` + ``playerTimeline`` as props and renders
 * a tabbed UI. The wrapper preserves that contract -- the
 * PerFightTimelineSection component is unchanged -- but adds the
 * lazy-fetch state machine at the boundary so the page can pass
 * ``fightId`` + ``windowS`` instead of pre-fetched data.
 *
 * Why a discriminated union for the state machine
 * ===============================================
 * The ``{ status: 'loading' } | { status: 'success', data } |
 * { status: 'error', error }`` pattern makes the impossible
 * states unrepresentable (a loading state with data, a success
 * state with an error, etc.) and lets TypeScript narrow the
 * ``data`` field to ``FightPlayerTimeline`` (not ``FightPlayerTimeline
 * | null``) inside the success branch. The render code is then
 * a flat if-else cascade without optional chaining noise.
 *
 * Hydration consideration
 * =======================
 * The initial state is ``{ status: 'loading' }`` which renders
 * the skeleton identically SSR + CSR (no ``typeof window``
 * checks, no conditional branches on the server). React's
 * hydration reconciliation sees the same tree on both sides;
 * no hydration warning.
 *
 * Plan 161 interaction
 * ===================
 * This component IS one of the section-isolated sections.
 * The wrapper handles its OWN error state via SectionErrorChip
 * -- the parent page does NOT need a try/catch around this
 * component (the wrapper catches the fetch error internally
 * + surfaces it as a per-section chip).
 */

"use client";

import { useEffect, useState } from "react";

import { fetchFightPlayerTimeline } from "@/lib/api/fights";
import type { FightPlayerTimeline, FightTimeline } from "@/lib/api";

import { PerFightTimelineSection } from "@/components/PerFightTimelineSection";
import { SectionErrorChip } from "@/components/SectionErrorChip";

type State =
  | { status: "loading" }
  | { status: "success"; data: FightPlayerTimeline }
  | { status: "error"; error: string };

// Skeleton styles mirror the existing CAPTION_STYLE palette so
// the loading state blends with the rest of the page. The fixed
// height prevents layout shift when the chart streams in.
const SKELETON_STYLE: React.CSSProperties = {
  height: 320,
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 4,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "var(--foreground)",
  opacity: 0.5,
  fontSize: 13,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

export function LazyTabbedTimelineSection({
  timeline,
  fightId,
  windowS,
}: {
  timeline: FightTimeline | null;
  fightId: string;
  windowS: number;
}) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    // The `active` flag prevents the cleanup-then-resolve race
    // (a fast unmount during the in-flight fetch would otherwise
    // call setState on an unmounted component, which React
    // warns about).
    let active = true;
    setState({ status: "loading" });
    fetchFightPlayerTimeline(fightId, { windowS })
      .then((data) => {
        if (active) {
          setState({ status: "success", data });
        }
      })
      .catch((err: unknown) => {
        if (active) {
          const message =
            err instanceof Error ? err.message : "Failed to load player timeline";
          setState({ status: "error", error: message });
        }
      });
    return () => {
      active = false;
    };
  }, [fightId, windowS]);

  // The PerFightTimelineSection is ALWAYS rendered (no display:none
  // wrapper). During loading we pass playerTimeline=null which lets
  // the section show its built-in "Per-player timeline unavailable"
  // caption on the per-player tab -- the user can STILL flip to the
  // Aggregated tab (which is populated via the ``timeline`` prop)
  // while the lazy fetch resolves. This is a strictly better UX
  // than hiding the section during loading + avoids the extra
  // DOM wrapper node.
  //
  // On error, the section is ALSO rendered (with
  // playerTimeline=null so the Per-player tab shows the built-in
  // unavailable caption). The error chip is shown as supplementary
  // diagnostic info ABOVE the section so the analyst still sees the
  // aggregated timeline (the primary surface) + a hint that the
  // per-player view failed to load.
  return (
    <>
      {state.status === "loading" ? (
        <div
          style={SKELETON_STYLE}
          data-testid="timeline-skeleton"
          aria-label="Loading player timeline"
        >
          Loading player timeline…
        </div>
      ) : null}
      {state.status === "error" ? (
        <SectionErrorChip
          testid="player-timeline-section-error"
          message={state.error}
        />
      ) : null}
      <PerFightTimelineSection
        timeline={timeline}
        playerTimeline={state.status === "success" ? state.data : null}
      />
    </>
  );
}
