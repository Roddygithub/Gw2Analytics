/**
 * Phase 7 v1 of web: drill-down page that surfaces the v0.3.0-api
 * per-target damage + healing roll-up + time-bucketed events for a
 * single fight.
 *
 * Why a dynamic Server Component
 * ==============================
 * The data source is the gateway's per-fight events endpoint
 * (Postgres-backed for the fight row, MinIO-backed for the
 * gzipped JSONL events blob). Server-side fetch avoids the
 * client-side waterfall (browser -> /fights/[id] -> gateway ->
 * Postgres + MinIO) and ensures the initial response is fully
 * populated for the URL-permalinkable fight_id (so an analyst can
 * bookmark or share a specific fight's drill-down).
 *
 * Force-dynamic
 * =============
 * ``export const dynamic = "force-dynamic"`` opts out of Next.js
 * static caching so the roll-up reflects the latest parsed fight
 * state (events_blob_uri can flip NULL -> non-NULL when a
 * re-parse lands, and the per-bucket window is query-param-driven
 * so a single URL can't represent all possible windowings).
 *
 * Why a single bound page (vs separate sub-routes)
 * ================================================
 * The per-target DPS roll-up + per-target healing roll-up +
 * per-bucket event windows are all derived from the SAME JSONL
 * events blob; a single ``fetchFightEvents`` call gets all three
 * sub-aggregations. Splitting into three sub-routes would force
 * the analyst through three waterfall round-trips for the same
 * underlying blob. The page is therefore a single Server Component
 * that hands the data to three small client-rendered sub-views.
 *
 * Empty + 404 + upstream-error handling
 * ======================================
 * - empty roll-ups (``target_dps == []`` etc.) -> the
 *   :class:`TargetRollupsGrid` renders a styled "no rows" panel;
 *   :class:`EventWindowsTable` renders a "No event windows" panel.
 *   No error path; this is the canonical "fight ran but the parser
 *   yielded zero events" case.
 * - ``ApiError(404, ...)`` from the gateway (unknown fight id OR
 *   events blob missing) -> the page renders an upstream-error
 *   card with the gateway's error body. The page does NOT raise
 *   404 itself; the canonical 404 lives at the API boundary, and
 *   the analyst surface just shows the upstream message.
 * - any other thrown error (network, 5xx) -> the same
 *   upstream-error card with the error message. The page does not
 *   try to recover; the user can refresh or navigate back to
 *   ``/fights``.
 *
 * Forward compat
 * ==============
 * Any new ``Event`` subclass added to ``gw2_core`` (e.g. a Phase 8
 * ``BuffRemovalEvent``) will surface here as a new sibling
 * roll-up section + a new column on the per-bucket event_windows
 * table. The :class:`TargetRollupsGrid` is generic so the page
 * only needs to add a new column spec; no new Client Component
 * required.
 */

import { fetchCached } from "@/lib/fetchCached";
import { API_BASE_URL } from "@/lib/env";
import {
  fetchFightEvents,
  fetchFightPlayerTimeline,
  fetchFightSquads,
  fetchFightSkills,
  fetchFightTimeline,
  formatApiError,
  type TargetDpsRow,
  type TargetHealingRow,
  type TargetBuffRemovalRow,
  type FightEventsSummaryRow,
  type FightPlayerTimeline,
  type FightTimeline,
  type SquadRollupRow,
  type SkillUsageRow,
} from "@/lib/api";
import {
  TargetRollupsGrid,
  type TargetRollupColumn,
} from "@/components/TargetRollupsGrid";
import {
  SquadRollupsGrid,
  type SquadRollupColumn,
} from "@/components/SquadRollupsGrid";
import { EventWindowsTable } from "@/components/EventWindowsTable";
import { EventWindowsChart } from "@/components/EventWindowsChart";
import { SkillUsageTable } from "@/components/SkillUsageTable";
import { PerFightTimelineSection } from "@/components/PerFightTimelineSection";
import { ReplayPlayer } from "@/components/ReplayPlayer";
import { fetchReplayTimeline } from "@/lib/replayFetcher";
import { WindowSizeSelector } from "@/components/WindowSizeSelector";
import { TargetFilter } from "@/components/TargetFilter";

export const dynamic = "force-dynamic";

/**
 * Parse the URL ``?window_s=`` query param into a typed integer,
 * clamping invalid / out-of-range values to the gateway default
 * (5s). The clamping is intentional: the gateway returns 422 on
 * out-of-range, which would surface a misleading upstream-error
 * card for what is really a URL-typo case. By clamping on the
 * client, an analyst typing ``?window_s=0`` lands on the
 * canonical 5s view instead of an error page.
 */
function parseWindowS(raw: string | undefined): number {
  const DEFAULT = 5;
  if (raw === undefined || raw === "") return DEFAULT;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n) || n < 1 || n > 600) return DEFAULT;
  return n;
}

/**
 * Build the href for the page-level tab strip. The Replay tab is
 * a URL-encoded alternate view of the SAME page (no client-side
 * router required) so the href preserves the current
 * ``window_s`` and ``target`` params (so the analyst keeps
 * their drill-down context) and toggles the ``tab=`` param.
 *
 * Why a plain ``<a>`` tag (vs ``<Link>``)
 * ======================================
 * The tab stripes are pure GET navigation between two query-param
 * variants of the same pathname. ``next/link`` adds client-side
 * prefetching for ``prefetch={true}`` (the default) but for
 * tab strips on a per-fight drilldown the prefetch benefit is
 * zero (the prefetched route is identical to the current
 * route modulo two query params; the render output is already
 * cached server-side via the per-fight render's React cache).
 * A plain ``<a href=...>`` is simpler + smaller + has no
 * client-side hydration requirement.
 */
function buildTabHref(
  fightId: string,
  windowS: number,
  targetFilter: number | null,
  activeTab: "overview" | "replay",
): string {
  const qs = new URLSearchParams();
  if (activeTab === "replay") qs.set("tab", "replay");
  if (windowS !== 5) qs.set("window_s", String(windowS));
  if (targetFilter !== null) qs.set("target", String(targetFilter));
  const qsStr = qs.toString();
  return qsStr
    ? `/fights/${encodeURIComponent(fightId)}?${qsStr}`
    : `/fights/${encodeURIComponent(fightId)}`;
}

/**
 * Parse the URL ``?target=`` query param into a typed target
 * agent id, or ``null`` when the param is missing / unparseable /
 * out of range. ``null`` means "show all targets" (the
 * unfiltered case). A negative or non-integer value falls back to
 * ``null`` so an analyst typing ``?target=foo`` lands on the
 * unfiltered view instead of an error page (mirrors the
 * ``parseWindowS`` leniency contract).
 */
function parseTarget(raw: string | undefined): number | null {
  if (raw === undefined || raw === "") return null;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n) || n < 0) return null;
  return n;
}

// Column specs are built once at module-load time, not inside the
// component body, so the ``TargetRollupsGrid`` useMemo deps stay
// referentially stable across renders and the grid does not
// rebuild its column model on every revalidation. The schema is
// locked by the v0.5.0-api ``TargetDpsRowOut`` /
// ``TargetHealingRowOut`` / ``TargetBuffRemovalRowOut`` shapes; any
// future roll-up kind would add a new sibling here without changing
// this page's render shape.
const DPS_COLUMNS: TargetRollupColumn<TargetDpsRow>[] = [
  { field: "target_agent_id", headerName: "Target agent", width: 160 },
  { field: "total_damage", headerName: "Total damage", width: 160 },
  { field: "dps", headerName: "DPS", decimals: 2, width: 140 },
];
const HEALING_COLUMNS: TargetRollupColumn<TargetHealingRow>[] = [
  { field: "target_agent_id", headerName: "Target agent", width: 160 },
  { field: "total_healing", headerName: "Total healing", width: 160 },
  { field: "hps", headerName: "HPS", decimals: 2, width: 140 },
];
// Phase 8: third sibling roll-up, strict parallel of the DPS +
// Healing column specs. The schema is locked by the v0.5.0-api
// ``TargetBuffRemovalRowOut`` shape: ``target_agent_id`` +
// ``total_buff_removal`` + ``bps``.
const BUFF_REMOVAL_COLUMNS: TargetRollupColumn<TargetBuffRemovalRow>[] = [
  { field: "target_agent_id", headerName: "Target agent", width: 160 },
  { field: "total_buff_removal", headerName: "Total strip", width: 160 },
  { field: "bps", headerName: "BPS", decimals: 2, width: 140 },
];

// v0.7.1 of web: per-subgroup roll-up column spec. Keyed on the
// ``subgroup`` string (NOT ``target_agent_id`` -- the row shape
// differs from the per-target trio). The rate columns
// (``dps`` / ``hps`` / ``bps``) all use 2-decimal fixed
// formatting so the analyst can spot a high-rate squad at a
// glance.
const SQUAD_COLUMNS: SquadRollupColumn<SquadRollupRow>[] = [
  { field: "subgroup", headerName: "Subgroup", width: 200 },
  { field: "total_damage", headerName: "Total damage", width: 140 },
  { field: "total_healing", headerName: "Total healing", width: 140 },
  { field: "total_buff_removal", headerName: "Total strip", width: 140 },
  { field: "dps", headerName: "DPS", decimals: 2, width: 120 },
  { field: "hps", headerName: "HPS", decimals: 2, width: 120 },
  { field: "bps", headerName: "BPS", decimals: 2, width: 120 },
];

export default async function FightEventsPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    window_s?: string;
    target?: string;
    tab?: string;
  }>;
}) {
  // Next.js 15+ delivers both route params AND search params as
  // Promises; await them to obtain the fight id + window_s +
  // target. The ``encodeURIComponent`` on the id is unnecessary for
  // a SHA-256 (already URL-safe) but is the canonical guard
  // against any future id shape that happens to contain reserved
  // characters.
  //
  // ``tab`` is the v0.10.17 D1 Replay-tab routing param: ``"replay"``
  // renders ONLY the :class:`ReplayPlayer` section; the default
  // (``null`` / ``""`` / any other value) renders the existing
  // Overview content (per-target roll-ups + per-bucket windows +
  // per-subgroup + per-skill + per-fight timeline). Whitelisted
  // to exactly one of two values so an analyst typing
  // ``?tab=foo`` falls back to Overview rather than triggering a
  // error path.
  const { id } = await params;  const { window_s: window_s_raw, target: target_raw, tab: tab_raw,
  } = await searchParams;
  const windowS = parseWindowS(window_s_raw);
  const targetFilter = parseTarget(target_raw);
  // v0.10.17 D1 round-2 fix: case-insensitive tab match. An
  // analyst typing ``?tab=Replay`` or ``?tab=REPLAY`` is
  // legitimate variation (hand-typed URL + URL bookmark
  // conversions); strict-equal would silently drop them to
  // ``"overview"``, which is a confusing UX (the analyst
  // sees the Overview render but their URL says Replay). The
  // match is also null-safe (``tab_raw`` may be ``undefined``
  // when the URL has no ``?tab=``).
  const activeTab: "overview" | "replay" =
    (tab_raw ?? "").toLowerCase() === "replay" ? "replay" : "overview";

  let summary: FightEventsSummaryRow | null = null;
  let squads: import("@/lib/api").FightSquads | null = null;
  let skills: import("@/lib/api").FightSkills | null = null;
  let timeline: FightTimeline | null = null;
  let playerTimeline: FightPlayerTimeline | null = null;
  // ``fetchError`` is the BLOCKING fetch failure (events endpoint:
  // the per-target roll-ups + per-bucket event_windows all derive
  // from the same blob upstream, so a missing events call means
  // nothing useful renders). The per-section error map surfaces
  // partial-failure diagnostics at the section level (squads /
  // skills / timeline / playerTimeline can fail independently
  // without blocking the page). v0.10.15 plan 035: per-section
  // diagnostic chimps added next to each roll-up grid; the
  // events-only failure mode retains the page-level banner.
  let fetchError: string | null = null;
  const sectionErrors: {
    squads?: string;
    skills?: string;
    timeline?: string;
    playerTimeline?: string;
  } = {};
  // ``fetchCached`` wraps each gateway call in an LRU (8 entries)
  // + TTL (60 s) cache with in-flight dedup so repeated
  // navigations to the same fight are served from cache.
  const base = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(id)}`;
  const qs = windowS !== 5 ? `?window_s=${windowS}` : "";
  const results = await Promise.allSettled([
    fetchCached<FightEventsSummaryRow>(`${base}/events${qs}`),
    fetchCached<import("@/lib/api").FightSquads>(`${base}/squads`),
    fetchCached<import("@/lib/api").FightSkills>(`${base}/skills`),
    // v0.10.17 D1: route the per-fight timeline fetch via the
    // :func:`fetchReplayTimeline` wrapper so the wrapper is
    // NOT a dead-code deliverable. The wrapper preserves the
    // ``fetchCached`` LRU + TTL contract (its body is a
    // pass-through to :func:`fetchCached` after URL
    // construction), so the cache key + the hit ratio are
    // identical to the inline call it replaced.
    fetchReplayTimeline(id, API_BASE_URL, { windowS }),
    fetchCached<FightPlayerTimeline>(`${base}/timeline/players${qs}`),
  ]);
  if (results[0].status === "fulfilled") {
    summary = results[0].value;
  } else {
    fetchError = formatApiError(results[0].reason);
  }
  if (results[1].status === "fulfilled") {
    squads = results[1].value;
  } else {
    sectionErrors.squads = formatApiError(results[1].reason);
  }
  if (results[2].status === "fulfilled") {
    skills = results[2].value;
  } else {
    sectionErrors.skills = formatApiError(results[2].reason);
  }
  if (results[3].status === "fulfilled") {
    timeline = results[3].value;
  } else {
    sectionErrors.timeline = formatApiError(results[3].reason);
  }
  if (results[4].status === "fulfilled") {
    playerTimeline = results[4].value;
  } else {
    sectionErrors.playerTimeline = formatApiError(results[4].reason);
  }

  if (fetchError || !summary) {
    return (
      <main style={{ padding: "32px" }}>
        <header style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 28, marginBottom: 4 }}>Fight {id}</h1>
          <p style={{ opacity: 0.7 }}>
            Per-target damage + healing + buff-removal roll-up + event windows.
          </p>
        </header>
        <p style={{ color: "var(--accent)" }}>{fetchError}</p>
      </main>
    );
  }

  // Compute the union of unique target_agent_ids across the three
  // roll-up arrays (DPS + healing + buff-removal). The
  // ``TargetFilter`` dropdown is populated from this set so the
  // analyst can pick a target that appears in at least one
  // roll-up. Sorted ascending for a stable, alphabetical-by-id
  // dropdown order. Phase 8: includes the third roll-up so a
  // target that only appears in ``target_buff_removal`` (e.g. a
  // pure-strip target) is still selectable.
  const availableTargets = Array.from(
    new Set<number>([
      ...summary.target_dps.map((r) => r.target_agent_id),
      ...summary.target_healing.map((r) => r.target_agent_id),
      ...summary.target_buff_removal.map((r) => r.target_agent_id),
    ]),
  ).sort((a, b) => a - b);

  // v0.8.3 of web: build the ``target_agent_id -> name`` lookup
  // from the roll-up rows. The gateway surfaces ``name`` on every
  // row (denormalised from ``OrmFightAgent``); iterating the union
  // of all three roll-ups guarantees a name is captured for every
  // target the dropdown exposes, even if the target only appears
  // in one of the three roll-ups. A "first non-null wins" loop
  // surfaces any cross-roll-up inconsistency (the gateway should
  // produce the same name for the same agent_id on every roll-up;
  // if a future bug breaks that contract, the FIRST name seen
  // wins and a later divergent name is silently dropped -- a
  // trade-off we accept because the simpler ``Object.fromEntries``
  // would silently overwrite with the LAST name, masking the
  // inconsistency entirely).
  //
  // PRECEDENCE CONTRACT: the roll-up order is DPS -> Healing ->
  // BuffRemoval, so a divergent name on the DPS roll-up wins over
  // the same id's name on later roll-ups. Do NOT reorder the
  // spread below without updating this contract.
  //
  // A ``null`` name (NPC without a registered char-name) is
  // preserved as ``null`` on the map so the dropdown falls back to
  // the raw id (mirrors the ``null``-on-the-wire contract from
  // the aggregator). Built once at request time -- the dropdown
  // is the only consumer and the lookup is O(1).
  const targetNameMap: Record<number, string | null> = {};
  for (const r of [
    ...summary.target_dps,
    ...summary.target_healing,
    ...summary.target_buff_removal,
  ]) {
    if (r.name !== null && !(r.target_agent_id in targetNameMap)) {
      targetNameMap[r.target_agent_id] = r.name;
    }
  }

  // Server-side filter: when ``targetFilter`` is set, narrow each
  // of the three roll-up arrays to that target. The
  // ``EventWindowsTable`` is intentionally NOT filtered -- the
  // per-bucket timeline is the "global fight picture" and a
  // per-target filter on the roll-ups already gives the analyst
  // the per-target contribution breakdown they want.
  const filteredDps =
    targetFilter === null
      ? summary.target_dps
      : summary.target_dps.filter((r) => r.target_agent_id === targetFilter);
  const filteredHealing =
    targetFilter === null
      ? summary.target_healing
      : summary.target_healing.filter((r) => r.target_agent_id === targetFilter);
  const filteredBuffRemoval =
    targetFilter === null
      ? summary.target_buff_removal
      : summary.target_buff_removal.filter(
          (r) => r.target_agent_id === targetFilter,
        );

  // v0.10.17 D1: the Replay tab is a URL-routed alternate view
  // of the SAME page. When ``tab=replay`` is set, we render
  // ONLY the :class:`ReplayPlayer` (the per-target roll-ups
  // + per-bucket windows + per-subgroup + per-skill + per-fight
  // timeline sections are all suppressed because they share
  // data with the ReplayPlayer and would crowd the viewport).
  // The fetch pipeline above still runs for BOTH tabs so the
  // LRU ``/timeline`` cache stays warm for a tab toggle (and
  // the per-section error map above still feeds the diagnostic
  // chimp on the Replay tab's empty-state path).
  if (activeTab === "replay") {
    return (
      <main
        style={{
          padding: "32px",
          display: "flex",
          flexDirection: "column",
          gap: "24px",
        }}
      >
        <header
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <h1 style={{ fontSize: 28, marginBottom: 4 }}>
              Fight {summary.fight_id}
            </h1>
            <p style={{ opacity: 0.7 }}>
              Duration: {summary.duration_s.toFixed(2)} s
              {targetFilter !== null ? ` — filtered to target ${targetFilter}` : ""}
            </p>
          </div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
            }}
            data-testid="page-tab-strip"
          >
            <a
              href={buildTabHref(id, windowS, targetFilter, "overview")}
              data-testid="page-tab-overview"
              style={{
                padding: "6px 12px",
                border: "1px solid var(--border)",
                borderRadius: 4,
                fontSize: 13,
                textDecoration: "none",
                color: "var(--foreground)",
                background: "var(--surface)",
                fontFamily:
                  "var(--font-geist-sans), Arial, Helvetica, sans-serif",
              }}
            >
              Overview
            </a>
            <a
              href={buildTabHref(id, windowS, targetFilter, "replay")}
              data-testid="page-tab-replay"
              data-active="true"
              aria-current="page"
              style={{
                padding: "6px 12px",
                border: "1px solid var(--accent)",
                borderRadius: 4,
                fontSize: 13,
                textDecoration: "none",
                color: "var(--accent-foreground, #fff)",
                background: "var(--accent)",
                fontFamily:
                  "var(--font-geist-sans), Arial, Helvetica, sans-serif",
              }}
            >
              Replay
            </a>
          </div>
        </header>
        {timeline === null ? (
          <p
            data-testid="replay-tab-error"
            style={{ color: "var(--accent)" }}
          >
            Failed to load timeline for the Replay tab:{" "}
            {sectionErrors.timeline ?? "unknown error"}
          </p>
        ) : (
          <ReplayPlayer fightId={id} timeline={timeline} />
        )}
      </main>
    );
  }

  return (
    <main
      style={{
        padding: "32px",
        display: "flex",
        flexDirection: "column",
        gap: "24px",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1 style={{ fontSize: 28, marginBottom: 4 }}>
            Fight {summary.fight_id}
          </h1>
          <p style={{ opacity: 0.7 }}>
            Duration: {summary.duration_s.toFixed(2)} s
            {targetFilter !== null ? ` — filtered to target ${targetFilter}` : ""}
          </p>
        </div>
        <div style={{ display: "inline-flex", gap: 16, flexWrap: "wrap" }}>
          <WindowSizeSelector current={windowS} fightId={id} />
          <TargetFilter
            current={targetFilter}
            availableTargets={availableTargets}
            targetNameMap={targetNameMap}
            fightId={id}
          />
          {/* v0.10.17 D1: page-level tab strip -- "Replay" is
              ALWAYS reachable from the Overview tab (the
              ``/api/v1/fights/{id}/timeline`` endpoint that
              powers the page's existing
              :class:`PerFightTimelineSection` is the same
              substrate the Replay tab uses, so there is no
              additional fetch cost on the tab toggle). The
              Replay tab is only disabled when ``timeline ===
              null`` AND a transient backfill has yet to land
              -- the in-tab empty-state surfaces the upstream
              error in that case. */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
            }}
            data-testid="page-tab-strip"
          >
            <a
              href={buildTabHref(id, windowS, targetFilter, "overview")}
              data-testid="page-tab-overview"
              data-active="true"
              aria-current="page"
              style={{
                padding: "6px 12px",
                border: "1px solid var(--accent)",
                borderRadius: 4,
                fontSize: 13,
                textDecoration: "none",
                color: "var(--accent-foreground, #fff)",
                background: "var(--accent)",
                fontFamily:
                  "var(--font-geist-sans), Arial, Helvetica, sans-serif",
              }}
            >
              Overview
            </a>
            <a
              href={buildTabHref(id, windowS, targetFilter, "replay")}
              data-testid="page-tab-replay"
              style={{
                padding: "6px 12px",
                border: "1px solid var(--border)",
                borderRadius: 4,
                fontSize: 13,
                textDecoration: "none",
                color: "var(--foreground)",
                background: "var(--surface)",
                fontFamily:
                  "var(--font-geist-sans), Arial, Helvetica, sans-serif",
              }}
            >
              Replay
            </a>
          </div>
        </div>
      </header>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Per-target damage</h2>
        <TargetRollupsGrid rows={filteredDps} columns={DPS_COLUMNS} filename={`${id}-damage.csv`} />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>
          Per-target healing
        </h2>
        <TargetRollupsGrid
          rows={filteredHealing}
          columns={HEALING_COLUMNS}
          filename={`${id}-healing.csv`}
        />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>
          Per-target buff removal
        </h2>
        <TargetRollupsGrid
          rows={filteredBuffRemoval}
          columns={BUFF_REMOVAL_COLUMNS}
          filename={`${id}-buff-removal.csv`}
        />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>
          Per-subgroup (squad)
        </h2>
        {sectionErrors.squads && (
          <p
            data-testid="squads-error"
            style={{ color: "var(--accent)", fontSize: 14, margin: 0 }}
          >
            Failed to load squads: {sectionErrors.squads}
          </p>
        )}
        <SquadRollupsGrid
          rows={squads?.squads ?? []}
          columns={SQUAD_COLUMNS}
          filename={`${id}-squads.csv`}
        />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Per-skill</h2>
        {sectionErrors.skills && (
          <p
            data-testid="skills-error"
            style={{ color: "var(--accent)", fontSize: 14, margin: 0 }}
          >
            Failed to load skills: {sectionErrors.skills}
          </p>
        )}
        <SkillUsageTable rows={skills?.skills ?? []} filename={`${id}-skills.csv`} />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Event windows</h2>
        <EventWindowsChart buckets={summary.event_windows} />
        <EventWindowsTable buckets={summary.event_windows} />
      </section>

      {/* v0.8.9 of web (plan/002): the per-fight timeline lives
          at the bottom of the page, BELOW the per-bucket event
          windows section. The per-bucket event windows are the
          "raw" view (absolute damage + healing per bucket from
          the existing ``EventWindowAggregator``); the per-fight
          timeline is the "normalised" view (3 stacked line
          series for trend reading). Showing both side-by-side
          lets the analyst correlate the absolute bucket
          magnitudes with the per-series trend lines. */}
      {sectionErrors.timeline && (
        <p
          data-testid="timeline-error"
          style={{ color: "var(--accent)", fontSize: 14, margin: 0 }}
        >
          Failed to load timeline: {sectionErrors.timeline}
        </p>
      )}
      {sectionErrors.playerTimeline && (
        <p
          data-testid="player-timeline-error"
          style={{ color: "var(--accent)", fontSize: 14, margin: 0 }}
        >
          Failed to load per-player timeline: {sectionErrors.playerTimeline}
        </p>
      )}
      <PerFightTimelineSection timeline={timeline} playerTimeline={playerTimeline} />
    </main>
  );
}
