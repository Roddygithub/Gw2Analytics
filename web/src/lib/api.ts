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
 * One per-target damage roll-up row, mirror of
 * :class:`apps.api.schemas.TargetDpsRowOut` (apps/api 0.3.0+).
 *
 * The aggregator-side ``attack_count`` field is dropped from the
 * API surface (analyst-only signal; the UI shows ``total_damage`` +
 * ``dps`` only). The ``dps`` rate is computed by the gateway from
 * ``total_damage / duration_s``; ``duration_s`` itself is on
 * :class:`FightEventsSummaryRow`.
 */
export interface TargetDpsRow {
  target_agent_id: number;
  total_damage: number;
  dps: number;
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
 */
export async function fetchPlayers(
  opts: { limit?: number; offset?: number } = {},
): Promise<PlayerListRow[]> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
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
