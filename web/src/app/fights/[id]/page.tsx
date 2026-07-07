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

import {
  fetchFightEvents,
  formatApiError,
  type TargetDpsRow,
  type TargetHealingRow,
  type TargetBuffRemovalRow,
  type FightEventsSummaryRow,
} from "@/lib/api";
import {
  TargetRollupsGrid,
  type TargetRollupColumn,
} from "@/components/TargetRollupsGrid";
import { EventWindowsTable } from "@/components/EventWindowsTable";
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

export default async function FightEventsPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ window_s?: string; target?: string }>;
}) {
  // Next.js 15+ delivers both route params AND search params as
  // Promises; await them to obtain the fight id + window_s +
  // target. The ``encodeURIComponent`` on the id is unnecessary for
  // a SHA-256 (already URL-safe) but is the canonical guard
  // against any future id shape that happens to contain reserved
  // characters.
  const { id } = await params;
  const { window_s: window_s_raw, target: target_raw } = await searchParams;
  const windowS = parseWindowS(window_s_raw);
  const targetFilter = parseTarget(target_raw);

  let summary: FightEventsSummaryRow | null = null;
  // ``fetchError`` carries the user-facing error string (already
  // formatted via :func:`formatApiError` so the page renders the
  // exact same text a Client Component would). The body of the
  // error card just inlines the string verbatim -- no extra
  // ``Upstream error:`` prefix is needed.
  let fetchError: string | null = null;
  try {
    summary = await fetchFightEvents(id, { windowS });
  } catch (err) {
    fetchError = formatApiError(err);
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
            fightId={id}
          />
        </div>
      </header>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Per-target damage</h2>
        <TargetRollupsGrid rows={filteredDps} columns={DPS_COLUMNS} />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>
          Per-target healing
        </h2>
        <TargetRollupsGrid
          rows={filteredHealing}
          columns={HEALING_COLUMNS}
        />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>
          Per-target buff removal
        </h2>
        <TargetRollupsGrid
          rows={filteredBuffRemoval}
          columns={BUFF_REMOVAL_COLUMNS}
        />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>Event windows</h2>
        <EventWindowsTable buckets={summary.event_windows} />
      </section>
    </main>
  );
}
