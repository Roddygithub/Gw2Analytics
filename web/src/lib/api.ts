/**
 * Server-side fetcher for the GW2Analytics FastAPI gateway.
 *
 * This helper is consumed by both Server Components (which import
 * it at request time) and Client Components (after fetch+hydration).
 * The ``API_BASE_URL`` env var is set in ``web/.env.local`` (gitignored)
 * following the Next.js convention; the production deployment wires
 * it to the gateway origin.
 *
 * Why env-driven (vs hardcoded localhost): keeps the front-end build
 * portable across local dev / preview builds / production deploys
 * without rebuilding the bundle per environment.
 */

import { API_BASE_URL } from "./env";

/**
 * Get the fights list from the gateway.
 *
 * Mirrors ``GET /api/v1/fights`` in :mod:`apps.api.routes.fights` with
 * the default ``limit=50``. Returns an array even when the upstream
 * rejects so the consumer can render an explicit empty state.
 */
export async function fetchFights(): Promise<FightRow[]> {
  const resp = await fetch(`${API_BASE_URL}/api/v1/fights`, {
    // Server Components re-execute per request; the cache is opt-in.
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as FightRow[];
}

/**
 * Get the per-target damage + per-target healing + time-bucketed
 * events roll-up for one fight.
 *
 * Mirrors ``GET /api/v1/fights/{fight_id}/events`` in
 * :mod:`apps.api.routes.fights`. ``windowS`` defaults to 5 (the
 * gateway default; matches the standard GW2 toolchain bucketing
 * convention). Throws :class:`ApiError` on any non-2xx so the
 * Server Component can render the canonical upstream-error card
 * (404: fight unknown OR events blob missing; 422: windowS out of
 * range; 502: blob corrupt).
 *
 * Phase 7 v1 of web: the v0.3.0-api response now exposes both
 * ``target_dps`` and ``target_healing`` roll-ups side-by-side, plus
 * the per-bucket ``event_windows`` (which carries both
 * ``damage_total`` and ``healing_total`` via the discriminated
 * ``Event`` union). This helper surfaces all three on the HTTP
 * boundary.
 */
export async function fetchFightEvents(
  fightId: string,
  opts: { windowS?: number } = {},
): Promise<FightEventsSummaryRow> {
  const params = new URLSearchParams();
  if (opts.windowS !== undefined) {
    params.set("window_s", String(opts.windowS));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/events${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, {
    // Server Components re-execute per request; the cache is opt-in.
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightEventsSummaryRow;
}

/**
 * Resolve a GW2 API key against the gateway.
 *
 * Mirrors ``GET /api/v1/account`` in :mod:`apps.api.routes.account`,
 * passing the supplied key as a ``Bearer`` token. Returns the
 * canonical ``(world_id, world_name, world_population)`` triple.
 */
export async function resolveAccount(
  apiKey: string,
): Promise<AccountEnrichedRow> {
  const resp = await fetch(`${API_BASE_URL}/api/v1/account`, {
    method: "GET",
    headers: { Authorization: `Bearer ${apiKey.trim()}` },
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as AccountEnrichedRow;
}

/**
 * POST a combat log to the gateway's multipart ingestion endpoint.
 *
 * Mirrors ``POST /api/v1/uploads`` in
 * :mod:`apps.api.routes.uploads`. The gateway hashes the bytes,
 * stores the raw blob in MinIO, queue-spawns a background parser
 * task, and returns the canonical ``UploadCreatedRow`` envelope
 * (id + sha256 + status=pending). The parsed fight eventually
 * materialises on ``GET /api/v1/fights`` once the parser commits.
 *
 * ``Content-Type`` is intentionally NOT set: the browser computes
 * ``multipart/form-data; boundary=...`` from the FormData body and
 * we lose that boundary if we override the header.
 */
export async function uploadLog(file: File): Promise<UploadCreatedRow> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch(`${API_BASE_URL}/api/v1/uploads`, {
    method: "POST",
    body: fd,
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as UploadCreatedRow;
}

/**
 * Fetch the current parse status for an upload.
 *
 * Mirrors ``GET /api/v1/uploads/{upload_id}`` in
 * :mod:`apps.api.routes.uploads`. The gateway returns the canonical
 * ``UploadOut`` envelope (id + sha256 + status + parser_version +
 * fight_id + ...) -- the wizard polls this every ~2s after POST until
 * ``status`` flips to ``"completed"`` (reveals drill-down link to
 * ``/fights/{fight_id}``) or ``"failed"`` (reveals ``error_message``).
 *
 * Throws :class:`ApiError` on any non-2xx so the wizard can render
 * the canonical upstream-error card (404: upload deleted server-side,
 * 502: gateway down). The wizard's 30s polling budget surfaces a
 * timeout instead of looping forever on a wedged parse.
 *
 * v0.9.0 of the API: this endpoint was already present at v0.5.0;
 * the wizard is the first front-end consumer that depends on its
 * status polling semantics.
 */

export async function fetchUploadStatus(uploadId: string): Promise<UploadStatusRow> {
  const url = `${API_BASE_URL}/api/v1/uploads/${encodeURIComponent(uploadId)}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as UploadStatusRow;
}

/**
 * Format any thrown value into the canonical error string we show
 * the user in Client Components. Shared between ``/account`` +
 * ``/upload`` so the upstream diagnostics stay consistent.
 *
 *   ApiError(502, "upstream gateway")
 *     -> "Upstream error: 502: 502: upstream gateway"
 *   new Error("Network unreachable")
 *     -> "Network unreachable"
 *   "anything else"
 *     -> "anything else" (string-coerced)
 */
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    return `Upstream error: ${err.status}: ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return String(err);
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(`${status}: ${message}`);
  }
}

export interface FightRow {
  id: string;
  build_version: string;
  encounter_id: number;
  agent_count: number;
  started_at: string;
  game_type: number;
}

export interface AccountEnrichedRow {
  world_id: number;
  world_name: string;
  world_population: string;
}

/**
 * Lightweight envelope from ``POST /api/v1/uploads``.
 *
 * The gateway returns this synchronously (HTTP 201) before the
 * background parser runs; ``status`` will be ``"pending"`` on a
 * fresh upload and either ``"completed"`` or ``"failed"`` on a
 * re-upload of an already-seen sha256. The parsed fight surfaces
 * on ``/fights`` once ``status`` flips to ``"completed"``.
 */
export interface UploadCreatedRow {
  /** Authoritative upload id (UUID v4, string-serialised). */
  id: string;
  /** SHA-256 of the raw bytes — the upload idempotency key. */
  sha256: string;
  /**
   * Backend uses "pending" / "completed" / "failed". The trailing
   * ``(string & {})`` keeps forward-compat for new buckets the v2
   * API might introduce while still giving IDEs autocomplete for
   * the three known values today.
   */
  status: "pending" | "completed" | "failed" | (string & {});
}

/**
 * Full upload envelope from ``GET /api/v1/uploads/{upload_id}``.
 *
 * Returned by the gateway's :func:`apps.api.routes.uploads.get_upload`
 * route; the wizard polls this every ~2s after ``POST /uploads``
 * resolves to detect when the background parse finishes
 * (``status="completed"`` + ``fight_id`` populated) or fails
 * (``status="failed"`` + ``error_message`` populated).
 *
 * v0.9.0 of the web: this surface was previously exposed only via
 * internal ``/api/v1/webhooks`` admin tooling; the wizard is the
 * first user-facing consumer that polls it.
 */
export interface UploadStatusRow {
  /** Same UUID v4 string as :attr:`UploadCreatedRow.id`. */
  id: string;
  /** Same hex string as :attr:`UploadCreatedRow.sha256`. */
  sha256: string;
  /** Original filename as posted in the multipart ``file`` field. */
  original_filename: string;
  /** Raw blob size in bytes (matches Content-Length on the POST). */
  size_bytes: number;
  /** ISO-8601 wall-clock time the row was committed. */
  uploaded_at: string;
  /**
   * Backend uses "pending" / "completed" / "failed". The trailing
   * ``(string & {})`` keeps forward-compat same as :attr:`UploadCreatedRow.status`.
   */
  status: "pending" | "completed" | "failed" | (string & {});
  /** Populated only when ``status="failed"``; ``null`` otherwise. */
  error_message: string | null;
  /**
   * Parser version that processed (or is processing) the blob;
   * ``null`` while ``status="pending"``.
   */
  parser_version: string | null;
  /**
   * Authoritative ``fight.id`` of the parsed encounter; ``null``
   * while ``status="pending"`` or while ``status="failed"`` (a
   * failed parse never yields a row). The wizard's drill-down link
   * uses this id on success.
   */
  fight_id: string | null;
}

/**
 * One per-target damage roll-up row, mirror of
 * :class:`apps.api.schemas.TargetDpsRowOut` (apps/api 0.3.0+).
 *
 * The aggregator-side ``attack_count`` field is dropped from the
 * API surface (analyst-only signal; the UI shows ``total_damage`` +
 * ``dps`` only). The ``dps`` rate is computed by the gateway from
 * ``total_damage / duration_s``; ``duration_s`` itself is on
 * :class:`FightEventsSummaryRow`.
 *
 * v0.8.3 of the API: the optional ``name`` field carries the
 * player-name denormalisation (the arcdps char-name as recorded
 * on ``OrmFightAgent``). ``null`` when the agent id has no
 * registered name (an NPC) or when the gateway omitted the map;
 * the frontend falls back to the raw ``target_agent_id`` in that
 * case. Strict parallel of :attr:`TargetHealingRow.name` and
 * :attr:`TargetBuffRemovalRow.name`.
 */
export interface TargetDpsRow {
  target_agent_id: number;
  total_damage: number;
  dps: number;
  name: string | null;
}

/**
 * One per-target healing roll-up row, mirror of
 * :class:`apps.api.schemas.TargetHealingRowOut` (apps/api 0.3.0+).
 *
 * Strict parallel of :class:`TargetDpsRow`: drops ``heal_count``
 * from the API surface for analyst-only parity; the ``hps`` rate
 * is ``total_healing / duration_s``.
 */
export interface TargetHealingRow {
  target_agent_id: number;
  total_healing: number;
  hps: number;
  name: string | null;
}

/**
 * One per-target buff-removal roll-up row, mirror of
 * :class:`apps.api.schemas.TargetBuffRemovalRowOut` (apps/api 0.5.0+).
 *
 * Phase 8 ships this third roll-up, strict parallel of
 * :class:`TargetDpsRow` + :class:`TargetHealingRow`. Drops
 * ``strip_count`` from the API surface for analyst-only parity; the
 * ``bps`` rate is ``total_buff_removal / duration_s``. A single
 * cbtevent that dual-emits a ``HealingEvent`` AND a
 * ``BuffRemovalEvent`` (corrupting / confusion skills) lands in BOTH
 * ``target_healing`` AND ``target_buff_removal`` -- independent
 * roll-ups on the same ``duration_s``.
 */
export interface TargetBuffRemovalRow {
  target_agent_id: number;
  total_buff_removal: number;
  bps: number;
  name: string | null;
}

/**
 * One time-bucketed roll-up window spanning ``[start_ms, end_ms)``,
 * mirror of :class:`apps.api.schemas.EventBucketOut`.
 *
 * The Phase 7 v2 :class:`Event` discriminated union lets
 * ``EventWindowAggregator`` account both damage AND healing in one
 * bucket, so the bucket's ``damage_total`` + ``healing_total`` +
 * ``event_count`` always sum correctly (event_count includes
 * damage + healing + future kinds).
 */
export interface EventBucket {
  start_ms: number;
  end_ms: number;
  damage_total: number;
  healing_total: number;
  event_count: number;
}

/**
 * Combined aggregation payload from
 * ``GET /api/v1/fights/{fight_id}/events``, mirror of
 * :class:`apps.api.schemas.FightEventsSummaryOut` (apps/api 0.3.0+).
 *
 * Phase 7 v1 of web (apps/api 0.3.0 / v0.3.0-api wire-up): the
 * per-target healing roll-up (``target_healing``) is now a sibling
 * of the damage roll-up (``target_dps``), and the discriminated
 * union round-trip via :class:`TypeAdapter[Event].validate_json`
 * lets the gateway stream both kinds in one JSONL blob. The
 * ``duration_s`` field is computed from
 * ``max(event.time_ms) / 1000.0`` because the V1.3 EVTC header
 * does not carry a wall-clock duration scalar.
 */
export interface FightEventsSummaryRow {
  fight_id: string;
  duration_s: number;
  target_dps: TargetDpsRow[];
  target_healing: TargetHealingRow[];
  target_buff_removal: TargetBuffRemovalRow[];
  event_windows: EventBucket[];
}

/**
 * One per-account cross-fight roll-up row from
 * ``GET /api/v1/players``, mirror of
 * :class:`apps.api.schemas.PlayerListRowOut` (apps/api 0.7.0+).
 *
 * The aggregator-side ``profession`` / ``elite_spec`` are
 * rendered as the wire-format string labels
 * (``"UNKNOWN"`` / ``"PROF(<id>)"`` /
 * ``"BASE"`` / ``"ELITE(<id>)"``) so the analyst-facing grid
 * shows human-readable class labels without a second lookup
 * table. ``fights_attended`` is the count of unique fight ids
 * the account appears in; the full ``attended_fight_ids`` list
 * is on :class:`PlayerProfile` (not on the list view -- it
 * would bloat the paginated response for large datasets).
 */
export interface PlayerListRow {
  account_name: string;
  name: string;
  profession: string;
  elite_spec: string;
  fights_attended: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

/**
 * One row of the per-fight breakdown on
 * :class:`PlayerProfile`, mirror of
 * :class:`apps.api.schemas.PerFightBreakdownRowOut`. The
 * ``started_at`` field is the wall-clock time the parser saw
 * the first event of the fight (Postgres ``TIMESTAMPTZ``,
 * serialised as an ISO-8601 string by the gateway).
 */
export interface PerFightBreakdownRow {
  fight_id: string;
  started_at: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

/**
 * Full cross-fight profile for one account, mirror of
 * :class:`apps.api.schemas.PlayerProfileOut` (apps/api 0.7.0+).
 * The ``per_fight_breakdown`` array is sorted by ``started_at``
 * DESC (recency-first) at the route layer; the
 * ``attended_fight_ids`` array is the same set in
 * ascending-id order (the aggregator's deterministic-ordering
 * contract).
 */
export interface PlayerProfile {
  account_name: string;
  name: string;
  profession: string;
  elite_spec: string;
  fights_attended: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
  attended_fight_ids: string[];
  per_fight_breakdown: PerFightBreakdownRow[];
}

/**
 * One per-subgroup (squad) roll-up row, mirror of
 * :class:`apps.api.schemas.SquadRollupRowOut` (apps/api 0.7.0+).
 * The ``subgroup`` field is a string (an empty string is a
 * valid value that surfaces in the empty-string bucket; the
 * route does NOT coerce the empty subgroup to a sentinel).
 * ``dps`` / ``hps`` / ``bps`` are the per-second rates
 * computed by the route from the per-subgroup totals /
 * ``duration_s``.
 */
export interface SquadRollupRow {
  subgroup: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
  dps: number;
  hps: number;
  bps: number;
}

/**
 * Per-fight squad roll-up payload from
 * ``GET /api/v1/fights/{fight_id}/squads``, mirror of
 * :class:`apps.api.schemas.FightSquadsOut`. ``duration_s`` is
 * the same scalar as the per-target / per-bucket trio on
 * :class:`FightEventsSummaryRow` so the analyst can compare
 * the roll-ups without a second lookup.
 */
export interface FightSquads {
  fight_id: string;
  duration_s: number;
  squads: SquadRollupRow[];
}

/**
 * One per-skill roll-up row, mirror of
 * :class:`apps.api.schemas.SkillUsageRowOut` (apps/api 0.7.0+).
 *
 * ``hit_count`` is the SUM of the per-event hit counts across
 * all 3 event kinds (damage + healing + strip = 1 each per
 * event); a single cbtevent that dual-emits lands as 2 hits.
 * The per-skill roll-up keeps ``hit_count`` on the API surface
 * (the per-target trio deliberately drops it as analyst-only
 * metadata) because analysts use it to spot "low-damage
 * high-frequency" skill patterns.
 */
export interface SkillUsageRow {
  skill_id: number;
  skill_name: string;
  hit_count: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

/**
 * Per-fight skill roll-up payload from
 * ``GET /api/v1/fights/{fight_id}/skills``, mirror of
 * :class:`apps.api.schemas.FightSkillsOut`. The skills array
 * is ordered by ``-total_damage`` (the aggregator's
 * deterministic-ordering contract).
 */
export interface FightSkills {
  fight_id: string;
  skills: SkillUsageRow[];
}

/**
 * Get the paginated cross-fight player roll-up from the
 * gateway.
 *
 * Mirrors ``GET /api/v1/players`` in
 * :mod:`apps.api.routes.players` with the default
 * ``limit=50`` and ``offset=0``. The route applies the
 * offset/limit to the FINAL sorted player list, not the
 * underlying fight set, so the response is stable across page
 * boundaries (a player who was page-1 row 5 last request is
 * page-1 row 5 this request).
 *
 * v0.9.0 of the API: the optional ``profession`` arg maps to
 * the ``?profession=ProfessionName`` query param (e.g.
 * ``?profession=MESMER``). The value is the enum name
 * (uppercase, e.g. ``"MESMER"``) -- the gateway's
 * :class:`Profession` Pydantic enum accepts both the enum
 * name and the integer value, but the web surface uses the
 * name for URL-readability. The filter is applied AFTER the
 * cross-fight roll-up + BEFORE the offset/limit, so
 * pagination is consistent on the filtered set.
 */
export async function fetchPlayers(
  opts: { limit?: number; offset?: number; profession?: string } = {},
): Promise<PlayerListRow[]> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.profession !== undefined) params.set("profession", opts.profession);
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/players${qs ? `?${qs}` : ""}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as PlayerListRow[];
}

/**
 * Get the full cross-fight profile + per-fight breakdown for
 * one account.
 *
 * Mirrors ``GET /api/v1/players/{account_name:path}`` in
 * :mod:`apps.api.routes.players`. The ``:path`` converter lets
 * the route accept account names containing ``/`` characters;
 * FastAPI decodes the URL-encoded form before handing the
 * string to the handler. Throws :class:`ApiError(404)` when
 * no agent in any fight carries the requested ``account_name``
 * (the canonical "player not found" contract).
 *
 * ``accountName`` MUST be URL-encoded by the caller (use
 * ``encodeURIComponent``); the Next.js 15+ async ``params``
 * contract delivers the decoded string automatically.
 */
export async function fetchPlayer(
  accountName: string,
): Promise<PlayerProfile> {
  const url = `${API_BASE_URL}/api/v1/players/${encodeURIComponent(accountName)}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as PlayerProfile;
}

/**
 * One per-fight timeline point from
 * ``GET /api/v1/players/{account_name}/timeline``, mirror of
 * :class:`apps.api.schemas.PlayerTimelinePointOut` (apps/api 0.8.0+).
 *
 * Strict parallel of :class:`PerFightBreakdownRow` -- one
 * point per attended fight, sorted by ``started_at`` DESC
 * (recency-first) at the route layer with ``fight_id`` ASC
 * as the deterministic-ordering tiebreaker.
 */
export interface PlayerTimelinePoint {
  fight_id: string;
  started_at: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

/**
 * Per-account historical timeline payload from
 * ``GET /api/v1/players/{account_name}/timeline``, mirror of
 * :class:`apps.api.schemas.PlayerTimelineOut` (apps/api 0.8.0+).
 *
 * ``total`` is the un-paginated count of attended fights so
 * the client can render a "showing N of M" caption and gate
 * the "Load more" button without a second request. ``limit``
 * and ``offset`` echo the request params so a Server
 * Component can verify the round-trip (e.g. when the route
 * clamps an out-of-range value).
 */
export interface CrossAccountTimelinePoint {
  fight_id: string;
  started_at: string;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

/**
 * One per-account series within a cross-account timeline response,
 * mirror of
 * :class:`gw2_analytics.cross_account_timeline.CrossAccountTimelineSeries`
 * (apps/api 0.10.0+).
 *
 * The ``points`` array mirrors :attr:`PlayerTimelinePoint` (one
 * point per attended fight, sorted by ``started_at`` DESC at the
 * route layer with ``fight_id`` ASC as the deterministic-ordering
 * tiebreaker). The ``name`` field is the last-seen char-name
 * (cosmetic identity); the analyst-facing chart labels each
 * polyline with ``name ?? account_name`` so a renamed player is
 * still visually identifiable.
 */
export interface CrossAccountTimelineSeries {
  account_name: string;
  name: string;
  points: CrossAccountTimelinePoint[];
}

/**
 * Get the per-fight historical timeline for N accounts
 * simultaneously.
 *
 * Mirrors ``GET /api/v1/players/compare/timeline`` in
 * :mod:`apps.api.routes.player_compare` with the ``accounts``
 * query param as a repeatable list (``?accounts=A&accounts=B``
 * URL-encoded; the route enforces ``[2, 4]`` accounts). The
 * response is a list of per-account series -- one series per
 * requested account -- each with the same ``points`` shape as
 * the per-account timeline (so the chart can overlay the
 * accounts on a shared X axis). An account with no attended
 * fights is reported as a series with ``points: []`` (NOT a
 * 404 -- the analyst UX benefits from a same-shape response
 * for all requested accounts).
 *
 * Throws :class:`ApiError(422)` on fewer than 2 / more than 4
 * unique accounts, on an unknown ``?tz=`` IANA name, or on an
 * unknown ``?bucket=`` value. The page-level Server Component
 * surfaces these as the upstream-error card.
 */
export async function fetchPlayerCompareTimeline(
  accounts: string[],
  opts: { bucket?: "fight" | "day"; tz?: string } = {},
): Promise<CrossAccountTimelineSeries[]> {
  const params = new URLSearchParams();
  for (const acct of accounts) {
    params.append("accounts", acct);
  }
  if (opts.bucket !== undefined) params.set("bucket", opts.bucket);
  if (opts.tz !== undefined) params.set("tz", opts.tz);
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/players/compare/timeline?${qs}`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  const rows: unknown = await resp.json();
  if (!Array.isArray(rows)) {
    throw new ApiError(500, "upstream returned non-array");
  }
  return rows as CrossAccountTimelineSeries[];
}

export interface PlayerTimeline {
  account_name: string;
  total: number;
  limit: number;
  offset: number;
  /**
   * v0.8.1 of the API: the bucketing kind echoed from the
   * request. ``"fight"`` (default): one point per attended
   * fight, ``started_at`` is the parser-derived wall-clock
   * time. ``"day"``: one point per UTC calendar day, with
   * the 3 totals summed across the day's fights and
   * ``started_at`` rounded to UTC midnight so the chart's
   * X-axis can auto-detect the day alignment.
   */
  bucket: "fight" | "day";
  /**
   * v0.8.9 of the API: the TZ string echoed from the
   * ``?tz=`` query param (default ``"UTC"``). Determines
   * the calendar-day boundary for ``bucket="day"`` mode;
   * the day-bucketed point's ``started_at`` is the
   * day-midnight in the requested TZ (serialised as UTC
   * for wire compat -- the JSON still shows
   * ``"2024-01-15T00:00:00Z"``). ``bucket="fight"`` is
   * unaffected by the ``tz`` value. An invalid ``?tz=``
   * returns 422 (canonical FastAPI contract for
   * query-param validation failures, same shape as the
   * ``limit`` / ``offset`` 422 path).
   */
  tz: string;
  points: PlayerTimelinePoint[];
}

/**
 * Get the per-fight historical timeline for one account.
 *
 * Mirrors ``GET /api/v1/players/{account_name:path}/timeline``
 * in :mod:`apps.api.routes.players` with the default
 * ``limit=20`` and ``offset=0``. The route applies
 * ``offset``/``limit`` to the FINAL sorted points list (the
 * same way the list + detail routes do), so the response is
 * stable across page boundaries: the analyst sees the same
 * first-N points whether they requested them via
 * "Load more" or via a fresh ``?offset=20`` query string.
 *
 * Throws :class:`ApiError(404)` when no agent in any fight
 * carries the requested ``account_name`` (the canonical
 * "player not found" contract); the page-level Server
 * Component surfaces this as the upstream-error card.
 *
 * ``accountName`` MUST be URL-encoded by the caller (use
 * ``encodeURIComponent``); the Next.js 15+ async ``params``
 * contract delivers the decoded string automatically.
 */
export async function fetchPlayerTimeline(
  accountName: string,
  opts: {
    limit?: number;
    offset?: number;
    bucket?: "fight" | "day";
    /**
     * v0.8.9 of the API: ``?tz=Continent/City`` query param
     * for the day-bucketed ``started_at``. Default ``"UTC"``
     * (backward compat with pre-v0.8.9 consumers). An
     * invalid TZ string surfaces as 422 from the gateway;
     * the fetcher does NOT validate the string client-side
     * -- the gateway is the source of truth for the TZ
     * catalog (``zoneinfo.ZoneInfo`` on the server). The
     * ``bucket="fight"`` mode is unaffected.
     */
    tz?: string;
  } = {},
): Promise<PlayerTimeline> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.bucket !== undefined) params.set("bucket", opts.bucket);
  if (opts.tz !== undefined) params.set("tz", opts.tz);
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/players/${encodeURIComponent(accountName)}/timeline${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as PlayerTimeline;
}

/**
 * Get the per-subgroup roll-up for one fight.
 *
 * Mirrors ``GET /api/v1/fights/{fight_id}/squads`` in
 * :mod:`apps.api.routes.fights`. The route decompresses the
 * same events blob the per-target trio uses, splits by
 * ``isinstance`` at the call site, loads the per-fight agents
 * to build the ``agent_id -> subgroup`` map, and invokes
 * :class:`gw2_analytics.squad_rollup.SquadRollupAggregator` on
 * the same ``duration_s``.
 */
export async function fetchFightSquads(
  fightId: string,
): Promise<FightSquads> {
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/squads`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightSquads;
}

/**
 * Get the per-skill roll-up for one fight.
 *
 * Mirrors ``GET /api/v1/fights/{fight_id}/skills`` in
 * :mod:`apps.api.routes.fights`. The route loads the
 * per-fight ``OrmFightSkill`` rows to build the
 * ``skill_id -> skill_name`` map and invokes
 * :class:`gw2_analytics.skill_usage.SkillUsageAggregator` on
 * the split event streams. No ``duration_s`` is returned
 * (the skill-usage aggregator does not compute per-second
 * rates; see the module docstring for the rationale).
 */
export async function fetchFightSkills(
  fightId: string,
): Promise<FightSkills> {
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/skills`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightSkills;
}

/**
 * One per-fight timeline point from
 * ``GET /api/v1/fights/{fight_id}/timeline``, mirror of
 * :class:`apps.api.schemas.PerFightTimelinePointOut`
 * (apps/api 0.8.9+).
 *
 * The ``window_start_ms`` + ``window_end_ms`` straddle the
 * half-open ``[start, end)`` bucket range (the per-bucket
 * aggregation is contiguous). The 3 totals are the SUM of
 * the bucket's events. The chart's X-axis labels the buckets
 * by their ``window_start_ms / 1000`` in ``M:SS`` format
 * (relative time, not absolute date+time -- the per-fight
 * timeline is the "what happened in this fight" use case).
 */
export interface PerFightTimelinePoint {
  window_start_ms: number;
  window_end_ms: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

/**
 * Per-fight timeline payload from
 * ``GET /api/v1/fights/{fight_id}/timeline``, mirror of
 * :class:`apps.api.schemas.PerFightTimelineOut`
 * (apps/api 0.8.9+).
 *
 * The ``points`` array is sorted ascending by
 * ``window_start_ms`` (the aggregator's deterministic-
 * ordering contract). ``window_s`` + ``duration_s`` echo
 * the request params + the parser's max(time_ms) / 1000.0
 * so the chart can render a "Showing N buckets (M-second
 * window, X-second duration)" caption without a second
 * lookup.
 */
export interface FightTimeline {
  fight_id: string;
  window_s: number;
  duration_s: number;
  points: PerFightTimelinePoint[];
}

/**
 * Get the per-fight timeline (damage + healing + buff-removal
 * over time) for one fight.
 *
 * Mirrors ``GET /api/v1/fights/{fight_id}/timeline`` in
 * :mod:`apps.api.routes.fights`. ``windowS`` defaults to 5
 * (the gateway default; matches the per-fight events
 * endpoint's bucketing convention). Throws :class:`ApiError`
 * on any non-2xx so the Server Component can render the
 * canonical upstream-error card (404: fight unknown OR
 * events blob missing; 422: windowS out of range; 502: blob
 * corrupt).
 *
 * The per-fight timeline is a separate endpoint from
 * :func:`fetchFightEvents` (not folded into the events
 * payload) for the same reason the squads + skills endpoints
 * are separate: a single bound response would force the
 * page to refetch the full event blob even when only the
 * per-fight timeline is requested.
 */
export async function fetchFightTimeline(
  fightId: string,
  opts: { windowS?: number } = {},
): Promise<FightTimeline> {
  const params = new URLSearchParams();
  if (opts.windowS !== undefined) {
    params.set("window_s", String(opts.windowS));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/timeline${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightTimeline;
}

/**
 * One per-player timeline point from
 * ``GET /api/v1/fights/{fight_id}/timeline/players``, mirror
 * of :class:`apps.api.schemas.PerPlayerTimelinePointOut`
 * (apps/api 0.10.3+).
 *
 * Strict parallel of :class:`PerFightTimelinePoint` but
 * scoped to a single player (the series' owner). The schema
 * is structurally nested (``list[PerPlayerTimelineSeries[points:
 * list[PerPlayerTimelinePoint]]]``) vs the flat
 * ``list[PerFightTimelinePoint]`` of the aggregated
 * timeline. The frontend's per-player chart requires the
 * 2-level nested shape so the same X-axis bucket grid can
 * be rendered with one line per player -- a flat list would
 * force the chart to re-group by player on every render.
 */
export interface PerPlayerTimelinePoint {
  window_start_ms: number;
  window_end_ms: number;
  total_damage: number;
  total_healing: number;
  total_buff_removal: number;
}

/**
 * One player's per-fight timeline series from
 * ``GET /api/v1/fights/{fight_id}/timeline/players``, mirror
 * of :class:`apps.api.schemas.PerPlayerTimelineSeriesOut`.
 *
 * Every series has the same number of points (zero-filled
 * to ``max(bucket_index)``) so the multi-line chart's
 * arrays are aligned (a strict requirement of stacked-line
 * SVG renders).
 *
 * - ``account_name`` is the operational identity (stable
 *   across uploads, the join key for the per-account
 *   cross-fight roll-up).
 * - ``name`` is the LAST-SEEN char-name (cosmetic identity,
 *   best-effort -- arcdps prefixes with ``:`` so the
 *   cosmetic name is the ``:``-stripped form per the
 *   :class:`PlayerProfileAggregator` contract).
 */
export interface PerPlayerTimelineSeries {
  account_name: string;
  name: string;
  points: PerPlayerTimelinePoint[];
}

/**
 * Per-fight per-player timeline payload from
 * ``GET /api/v1/fights/{fight_id}/timeline/players``, mirror
 * of :class:`apps.api.schemas.PerPlayerTimelineOut`
 * (apps/api 0.10.3+, plan 083 Feature 3A).
 *
 * The ``series`` array is sorted by
 * ``(-total_damage, account_name)`` (the aggregator's
 * deterministic-ordering contract). ``window_s`` +
 * ``duration_s`` echo the request params + the parser's
 * ``max(event.time_ms) / 1000.0`` so the chart can render a
 * "Showing N players (M-second window, X-second duration)"
 * caption without a second lookup. ``series`` is empty when
 * the fight has zero player agents (a 0-player NPC-only
 * fight); the per-fight timeline endpoint raises ``404`` on
 * a 0-event fight, the per-player endpoint returns ``200``
 * with empty arrays (the 2 endpoints' empty-state contracts
 * diverge by design).
 */
export interface FightPlayerTimeline {
  fight_id: string;
  window_s: number;
  duration_s: number;
  series: PerPlayerTimelineSeries[];
}

/**
 * Get the per-player timeline (1 series per player, damage +
 * healing + buff-removal over time) for one fight.
 *
 * Mirrors ``GET /api/v1/fights/{fight_id}/timeline/players``
 * in :mod:`apps.api.routes.fights`. ``windowS`` defaults to
 * 5 (the gateway default; matches the per-fight events
 * endpoint's bucketing convention + the aggregated
 * ``/timeline`` endpoint's contract). Throws :class:`ApiError`
 * on any non-2xx so the Server Component can render the
 * canonical upstream-error card (404: fight unknown OR
 * events blob missing; 422: windowS out of range; 502: blob
 * corrupt).
 *
 * The per-player timeline is a separate endpoint from
 * :func:`fetchFightTimeline` (not folded into the aggregated
 * timeline payload) for the same reason the squads + skills
 * endpoints are separate: a single bound response would
 * force the page to refetch the full event blob even when
 * only the per-player view is requested. The 2 timeline
 * endpoints share the same ``window_s`` / ``duration_s`` /
 * bucket semantics so the page can swap between them via a
 * tab toggle without re-fetching the underlying blob.
 */
export async function fetchFightPlayerTimeline(
  fightId: string,
  opts: { windowS?: number } = {},
): Promise<FightPlayerTimeline> {
  const params = new URLSearchParams();
  if (opts.windowS !== undefined) {
    params.set("window_s", String(opts.windowS));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/api/v1/fights/${encodeURIComponent(fightId)}/timeline/players${
    qs ? `?${qs}` : ""
  }`;
  const resp = await fetch(url, {
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text());
  }
  return (await resp.json()) as FightPlayerTimeline;
}
