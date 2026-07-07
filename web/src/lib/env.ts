/**
 * Env-driven gateway base URL constants.
 *
 * Split out of ``lib/api.ts`` so Server-Component-only callers
 * (e.g. the landing hero footer) can import the displayed URL
 * without dragging the fetcher's ``ApiError`` class + row types
 * into the homepage bundle. ``lib/api.ts`` re-reads these
 * constants so there is a single source of truth at runtime.
 */

const API_BASE_URL =
  process.env.API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

export { API_BASE_URL };

/**
 * User-facing display string for the gateway base URL.
 *
 * Same value as ``API_BASE_URL``; exported as a stable named
 * symbol so SSR components cannot drift from the trimmed URL the
 * fetcher actually uses.
 */
export const displayedApiBaseUrl = API_BASE_URL;
