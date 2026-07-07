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
