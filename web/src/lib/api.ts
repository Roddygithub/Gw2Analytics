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
