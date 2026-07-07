/**
 * v0.8.9 of web (plan/002): Server Component wrapper for the
 * per-fight timeline section on the ``/fights/[id]`` drill-down
 * page.
 *
 * Why a Server Component (vs a Client Component)
 * ==============================================
 * The per-fight timeline is a single ``GET /api/v1/fights/{id}/timeline``
 * call (no pagination, no "Load more" -- the bucket count is
 * bounded by ``duration_s / window_s`` which is at most ~12000
 * for a 20h fight at ``window_s=5``; the route returns at most
 * ``MAX_BUCKETS = 12000`` which is a hard cap from the plan).
 * The drill-down page is already a Server Component that fetches
 * the events blob via :func:`fetchFightEvents`; threading the
 * per-fight timeline fetch through the same SSR pipeline avoids a
 * client-side waterfall. A separate Client Component would
 * require a second round-trip + a useEffect + a loading state +
 * an error state, all of which the page already handles for
 * the existing sections.
 *
 * Why a thin wrapper (vs inlining the chart in the page)
 * ======================================================
 * The page already imports 7 components (TargetRollupsGrid x3 +
 * SquadRollupsGrid + SkillUsageTable + EventWindowsChart +
 * EventWindowsTable). Adding an 8th import in the page would
 * push the page past the 300-line "fat Server Component"
 * threshold that's hard to test. The wrapper:
 *
 * 1. Renders the section heading + caption (the page's section
 *    pattern).
 * 2. Renders the :class:`PerFightTimelineChart` with the
 *    timeline points + window_s + duration_s as props.
 * 3. Renders the empty-state panel when the timeline returned
 *    zero buckets (a fight that ran for ``duration_s < window_s``
 *    produces a single zero-bucket timeline; the chart's own
 *    empty-state panel handles ``points.length === 0`` but we
 *    add a section-level caption for consistency with the
 *    other 5 sections).
 */

import { PerFightTimelineChart } from "@/components/PerFightTimelineChart";
import type { FightTimeline } from "@/lib/api";

export function PerFightTimelineSection({
  timeline,
}: {
  timeline: FightTimeline | null;
}) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <h2 style={{ fontSize: 18, fontWeight: 600 }}>Per-fight timeline</h2>
      {timeline === null ? (
        <p style={{ opacity: 0.7 }}>Per-fight timeline unavailable.</p>
      ) : (
        <>
          <p style={{ opacity: 0.7, fontSize: 13 }}>
            Showing {timeline.points.length} bucket
            {timeline.points.length === 1 ? "" : "s"} ({timeline.window_s}
            -second window, {timeline.duration_s.toFixed(2)} s duration)
          </p>
          <PerFightTimelineChart points={timeline.points} />
        </>
      )}
    </section>
  );
}
