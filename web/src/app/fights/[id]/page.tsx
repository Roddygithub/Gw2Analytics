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
  formatApiError,
  type TargetDpsRow,
  type TargetHealingRow,
  type TargetBuffRemovalRow,
  type FightEventsSummaryRow,
  type FightPlayerTimeline,
  type FightReadoutOut,
  type FightTimeline,
  type SquadRollupRow,
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
import { PlayerSkillUsageTable } from "@/components/PlayerSkillUsageTable";
import { PlayerSkillUsageFilter } from "@/components/PlayerSkillUsageFilter";
import { LazyTabbedTimelineSection } from "@/components/LazyTabbedTimelineSection";
import { PerFightTimelineSection } from "@/components/PerFightTimelineSection";
import { ReplayPlayer } from "@/components/ReplayPlayer";
// v0.10.26-pre plan 169 commit #1: per-section error indicator.
//
// Consolidates the inline ``<p data-testid="{section}-error"
//
//   style={accent}>` shape that was duplicated across 5+ per-section
//
// error blocks on this page. Pilot-tested at
//
// :file:`web/tests/components/section-error-chip.test.tsx`.
import { SectionErrorChip } from "@/components/SectionErrorChip";
import { PlayerReadoutDamage } from "@/components/PlayerReadoutDamage";
import { PlayerReadoutHeal } from "@/components/PlayerReadoutHeal";
import { PlayerReadoutBoons } from "@/components/PlayerReadoutBoons";
import { PlayerReadoutDefense } from "@/components/PlayerReadoutDefense";
import { PlayerPositionGrid } from "@/components/PlayerPositionGrid";
import { fetchReplayTimeline } from "@/lib/replayFetcher";
import { WindowSizeSelector } from "@/components/WindowSizeSelector";
import { TargetFilter } from "@/components/TargetFilter";
import {
  FAILED_TO_LOAD_PLAYER_LIST,
  FAILED_TO_LOAD_PER_PLAYER_SKILLS,
  FAILED_TO_LOAD_FIGHT_DETAILS,
  COMBAT_READOUT_FETCH_FAILED,
  COMBAT_READOUT_LOADING,
  PER_PLAYER_PROMPT_PLACEHOLDER,
  NO_EVENT_DATA_TITLE,
  NO_EVENT_DATA_BODY,
} from "@/lib/copy/error-messages";
import { ApiError } from "@/lib/api/errors";

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
 * Build the href for the page-level tab strip. The Replay +
 * Readout tabs are URL-encoded alternate views of the SAME page
 * (no client-side router required) so the href preserves the
 * current ``window_s`` and ``target`` params (so the analyst
 * keeps their drill-down context) and toggles the ``tab=`` param.
 *
 * Why a plain ``<a>`` tag (vs ``<Link>``)
 * ======================================
 * The tab stripes are pure GET navigation between three query-param
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
  activeTab: "overview" | "replay" | "readout",
): string {
  const qs = new URLSearchParams();
  if (activeTab === "replay") qs.set("tab", "replay");
  if (activeTab === "readout") qs.set("tab", "readout");
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

/**
 * Parse the URL ``?account=`` query param into a typed account
 * name (the wire-format value the player-section dropdown
 * filters on). ``null`` means "no player selected" (the
 * default; the per-player section renders the prompt
 * placeholder). A non-string / empty value falls back to
 * ``null`` so an analyst mistyping lands on the unfiltered case
 * -- the gateway returns 404 for genuinely-unknown values and
 * the section renders the upstream error message.
 *
 * URL-state leniency
 * ==================
 * Mirrors the project's lenient URL-handling convention: invalid
 * values fall back to the null/unfiltered default rather than
 * triggering a 4xx. The strict 404 contract is the gateway's
 * responsibility (the section surfaces gateway errors verbatim
 * via :func::``formatApiError``).
 */
function parseAccount(raw: string | undefined): string | null {
  if (raw === undefined || raw === "") return null;
  return raw;
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
    account?: string;
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
  const { id } = await params;  const {
    window_s: window_s_raw,
    target: target_raw,
    tab: tab_raw,
    account: account_raw,
  } = await searchParams;
  const windowS = parseWindowS(window_s_raw);
  const targetFilter = parseTarget(target_raw);
  const accountFilter = parseAccount(account_raw);
  // v0.10.17 D1 round-2 fix: case-insensitive tab match. An
  // analyst typing ``?tab=Replay`` or ``?tab=REPLAY`` is
  // legitimate variation (hand-typed URL + URL bookmark
  // conversions); strict-equal would silently drop them to
  // ``"overview"``, which is a confusing UX (the analyst
  // sees the Overview render but their URL says Replay). The
  // match is also null-safe (``tab_raw`` may be ``undefined``
  // when the URL has no ``?tab=``).
  // Tour 6 Wave 7: extended to a 3-way ``tab=overview|replay|readout``
  // routing (the new Readout tab surfaces the Combat readout §3-6
  // 4-table roll-up per docs/v0.9.0-combat-readout-design.md §9
  // Workstream F).
  const activeTab: "overview" | "replay" | "readout" = (() => {
    const t = (tab_raw ?? "").toLowerCase();
    if (t === "replay") return "replay";
    if (t === "readout") return "readout";
    return "overview";
  })();

  let summary: FightEventsSummaryRow | null = null;
  let squads: import("@/lib/api").FightSquads | null = null;
  let skills: import("@/lib/api").FightSkills | null = null;
  let timeline: FightTimeline | null = null;
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

  // Tour 4 v0.10.13 plan 044 (Skill build analyser): per-player
  // skill attribution. Two SEPARATE fetches AFTER the existing
  // ``Promise.allSettled`` because the players filter is
  // conditional on whether ``?account=`` is set in the URL:
  //   - the agents fetch is UNCONDITIONAL (the dropdown options
  //     are always available so a 0-selection state still shows
  //     the meaningful "Pick a player" prompt);
  //   - the per-player skills fetch is CONDITIONAL on
  //     ``accountFilter !== null`` AND on the agent row
  //     resolving to ``is_player === true && account_name !==
  //     null`` (NPCs / sentinel accounts are silently excluded).
  // Both go through :func::``fetchCached`` -- the agents
  // response is keyed on the fight id alone and TTL-cached for
  // 60s; the per-player fetch is keyed on the (fight_id,
  // account_name) tuple so concurrent analyst navigations
  // between players stay cache-warm.
  // v0.10.26-pre plan 169 polish: try/catch invariant --
  // ``fightDetails === null`` is reachable ONLY when
  // ``fightDetailsError !== null`` (the catch path). The
  // chip + filter gate pair below relies on this invariant
  // to TS-narrow cleanly; do NOT decouple the two without
  // updating both branches together (the split-into-2 shape
  // depends on it). Reaching the theoretical null-null state
  // surfaces a silent-empty per-player section.
  let fightDetails: import("@/lib/api").FightOut | null = null;
  let fightDetailsError: string | null = null;
  try {
    fightDetails = await fetchCached<import("@/lib/api").FightOut>(`${base}`);
  } catch (err) {
    fightDetailsError = formatApiError(err);
  }
  let accountSkills: import("@/lib/api").PlayerSkills | null = null;
  let accountSkillsError: string | null = null;
  if (accountFilter !== null && fightDetails !== null) {
    const agent = fightDetails.agents.find(
      (a) =>
        a.is_player === true && a.account_name === accountFilter,
    );
    if (agent === undefined) {
      // The URL points at an account that isn't in this
      // fight's agents list (NPC-only fights have
      // ``account_name=null`` agents; mistyped URLs land here).
      // Same lenient contract as ``parseTarget``: surface a
      // section-level diagnostic chimp rather than a
      // page-level 404.
      accountSkillsError = `Player "${accountFilter}" not found in this fight.`;
    } else {
      try {
        accountSkills =
          await fetchCached<import("@/lib/api").PlayerSkills>(
            `${base}/players/${encodeURIComponent(accountFilter)}/skills`,
          );
      } catch (err) {
        accountSkillsError = formatApiError(err);
      }
    }
  } else if (accountFilter !== null && fightDetails === null) {
    // Agents fetch failed before we could validate the
    // account; the agents fetch error is the root cause for
    // the per-player section too. Surface it.
    accountSkillsError = fightDetailsError ?? FAILED_TO_LOAD_FIGHT_DETAILS;
  }

  // Tour 6 v0.11.0-prep: Combat-readout payload fetch for the
  // ?tab=readout path. Conditional fetch so the /readout
  // network round-trip only fires when the analyst lands on
  // the readout tab -- the Overview + Replay tabs skip it
  // entirely (the SCAFFOLD-state hardcoded rows={[]} on the
  // Wave 7 save was the right shape before the backend route
  // landed; now the round-trip is cheap (cached blob fetch +
  // O(player-count) compute) so the conditional-on-tab is
  // sufficient). Wires the live PlayerReadoutOut rows into
  // the 4 PlayerReadout{Damage,Heal,Boons,Defense} components
  // that previously rendered with rows={[]} per the Wave 7
  // SCAFFOLD contract (see CHANGELOG v0.10.23-pre). SCAFFOLD-
  // ZERO honesty: dps_power + dps_condi + barrier_total +
  // barrier_ps + time_downed_ms + dodges + blocks + interrupts
  // stay at 0 by design -- those columns await the Phase 6 v2
  // parser-stream switch (per docs/v0.10.19-combat-readout-
  // spike.md Blocker A) + the Skills DB catalog full fill-out
  // (Blocker B). The downstream cells render the in-grid zero
  // + the status banner below names which columns are SCAFFOLD-
  // zero so the analyst reads the contract inline.
  let readoutData: FightReadoutOut | null = null;
  let readoutError: string | null = null;
  if (activeTab === "readout") {
    try {
      readoutData = await fetchCached<FightReadoutOut>(`${base}/readout`);
    } catch (err) {
      readoutError = formatApiError(err);
    }
  }

  if (fetchError || !summary) {
    const isEventsUnavailable =
      results[0].status === "rejected" &&
      results[0].reason instanceof ApiError &&
      results[0].reason.error_code === "EVENTS_UNAVAILABLE";
    return (
      <main style={{ padding: "clamp(16px, 5vw, 32px)" }}>
        <header style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: 28, marginBottom: 4 }}>Fight {id}</h1>
          <p style={{ opacity: 0.7 }}>
            Per-target damage + healing + buff-removal roll-up + event windows.
          </p>
        </header>
        {isEventsUnavailable ? (
          <div
            style={{
              padding: "16px 20px",
              border: "1px solid var(--border)",
              borderRadius: 4,
              background: "var(--surface)",
            }}
          >
            <h2 style={{ fontSize: 18, marginBottom: 8 }}>{NO_EVENT_DATA_TITLE}</h2>
            <p style={{ opacity: 0.8, margin: 0 }}>{NO_EVENT_DATA_BODY}</p>
          </div>
        ) : (
          // 2026-07-16 mobile+a11y audit D1: ``role="alert"``
          //   surfaces the fetch failure to screen readers
          //   immediately (without it, SR users have no
          //   audible signal that the page failed). The
          //   visual treatment (``color: var(--accent)``)
          //   is preserved so sighted users still see the
          //   red error text.
          <p role="alert" style={{ color: "var(--accent)" }}>{fetchError}</p>
        )}
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
  // Tour 6 Wave 7 (Workstream F): Combat-readout tab. The
  // ``tab=readout`` URL fragment renders ONLY the 4 Combat-readout
  // tables (per docs/v0.9.0-combat-readout-design.md §3-6) so the
  // analyst can focus on the per-aspect roll-up without the
  // per-target + per-skill + per-fight timeline noise. SCAFFOLD-time:
  // the live ``fetchFightReadout`` payload wires in once the v0.11.0
  // forward-blocker (apps/api ``GET /api/v1/fights/{id}/readout``
  // route handler) lands; pre-routehandler renders surface the
  // SCAFFOLD-zero contract inline so the empty-state panels
  // document the gap.
  if (activeTab === "readout") {
    return (
      <main
        style={{
          padding: "clamp(16px, 5vw, 32px)",
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
              Combat readout: per-player Damage / Heal / Boons / Defense
              (Tour 6 Wave 7 Workstream F).
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
            <a
              href={buildTabHref(id, windowS, targetFilter, "readout")}
              data-testid="page-tab-readout"
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
              Readout
            </a>
          </div>
        </header>

        <p
          data-testid="readout-tab-status"
          style={{
            padding: "12px 16px",
            border: readoutError ? "1px solid var(--accent)" : "1px solid var(--border)",
            borderRadius: 4,
            color: readoutError ? "var(--accent)" : "var(--foreground)",
            opacity: 0.9,
            fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
            fontSize: 13,
          }}
        >
          {readoutError !== null ? (
            <>{COMBAT_READOUT_FETCH_FAILED} {readoutError}</>
          ) : readoutData === null ? (
            <>{COMBAT_READOUT_LOADING}</>
          ) : (
            <>
              Combat readout loaded · {readoutData.players.length} players ·
              duration {readoutData.duration_s.toFixed(1)} s. SCAFFOLD-zero
              columns <code>dps_power</code> + <code>dps_condi</code> +
              <code> heal.barrier_total</code> + <code>heal.barrier_ps</code> +
              <code> defense.time_downed_ms</code> +{" "}
              <code>defense.dodges</code> + <code>defense.blocks</code> +
              <code> defense.interrupts</code> stay at 0 until Phase 6 v2
              lands the parser-side barrier-portion + condi-split +
              statechange event subclasses (per{" "}
              <code>docs/v0.10.19-combat-readout-spike.md</code> Blocker A + B).
              Every other column shown below is wired to real per-event data
              from the upstream blob.
            </>
          )}
        </p>

        <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Damage</h2>
          <PlayerReadoutDamage rows={readoutData?.players ?? []} />
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Heal</h2>
          <PlayerReadoutHeal rows={readoutData?.players ?? []} />
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Boons</h2>
          <PlayerReadoutBoons rows={readoutData?.players ?? []} />
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <h2 style={{ fontSize: 18, fontWeight: 600 }}>Defense</h2>
          <PlayerReadoutDefense rows={readoutData?.players ?? []} />
        </section>
      </main>
    );
  }
  if (activeTab === "replay") {
    return (
      <main
        style={{
          padding: "clamp(16px, 5vw, 32px)",
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
        padding: "clamp(16px, 5vw, 32px)",
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
            <a
              href={buildTabHref(id, windowS, targetFilter, "readout")}
              data-testid="page-tab-readout"
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
              Readout
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
          <SectionErrorChip
            testid="squads-section-error"
            message={`Failed to load squads: ${sectionErrors.squads}`}
          />
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
          <SectionErrorChip
            testid="skills-section-error"
            message={`Failed to load skills: ${sectionErrors.skills}`}
          />
        )}
        <SkillUsageTable rows={skills?.skills ?? []} filename={`${id}-skills.csv`} />
      </section>

      {/* Tour 4 v0.10.13 plan 044: per-player skill attribution.
          Sits BETWEEN the existing per-skill section and the
          event-windows section. The dropdown is filtered to
          ``is_player === true && account_name !== null`` agents
          upstream (in the fetch block above) so the page only
          passes player-shaped entries to the Client Component
          filter. The body renders ONE of three states:
          - no player selected: prompt placeholder
          - fetch error: section-level diagnostic chimp
          - accountSkills resolved: the
            :component::``PlayerSkillUsageTable`` (with the
            loadout header strip + the per-skill table +
            optional CSV download). */}
      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>
          Per-player (SkillUsage attribution)
        </h2>
        {fightDetails === null && fightDetailsError !== null && (
          <SectionErrorChip
            testid="player-skill-agents-section-error"
            message={`${FAILED_TO_LOAD_PLAYER_LIST} ${fightDetailsError}`}
          />
        )}
        {fightDetails !== null && (
          <PlayerSkillUsageFilter
            currentValue={accountFilter}
            playerAgents={fightDetails.agents
              .filter(
                (a) =>
                  a.is_player === true && a.account_name !== null,
              )
              .map((a) => ({
                account_name: a.account_name as string,
                label: `${a.name} (${a.account_name})`,
              }))}
            fightId={id}
          />
        )}
        {accountFilter !== null && accountSkillsError !== null ? (
          <SectionErrorChip
            testid="player-skill-section-error"
            message={`${FAILED_TO_LOAD_PER_PLAYER_SKILLS} ${accountSkillsError}`}
          />
        ) : null}
        {accountFilter === null ? (
          <p
            data-testid="player-skill-prompt"
            style={{ opacity: 0.7, fontSize: 14, margin: 0 }}
          >
            {PER_PLAYER_PROMPT_PLACEHOLDER}
          </p>
        ) : accountSkills === null ? null : (
          <PlayerSkillUsageTable
            playerSkills={accountSkills}
            filename={`${id}-player-skills-${accountSkills.account_name.replace(/\./g, "_")}.csv`}
          />
        )}
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Event windows</h2>
        <EventWindowsChart buckets={summary.event_windows} />
        <EventWindowsTable buckets={summary.event_windows} />
      </section>

      {/* v0.11.0 Phase C: per-player positioning metrics. Rendered
          client-side because the grid fetches its own data from
          ``GET /api/v1/fights/{id}/positions`` and manages its own
          loading / error states. The section sits below the event
          windows so the existing overview flow is not interrupted. */}
      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Positions</h2>
        <PlayerPositionGrid fightId={id} />
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
        <SectionErrorChip
          testid="timeline-section-error"
          message={`Failed to load timeline: ${sectionErrors.timeline}`}
        />
      )}
        <LazyTabbedTimelineSection
          timeline={timeline}
          fightId={id}
          windowS={windowS}
        />
    </main>
  );
}
