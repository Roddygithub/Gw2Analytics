/**
 * Env-driven gateway base URL constants.
 *
 * Split out of ``lib/api.ts`` so Server-Component-only callers
 * (e.g. the landing hero footer) can import the displayed URL
 * without dragging the fetcher's ``ApiError`` class + row types
 * into the homepage bundle. ``lib/api.ts`` re-reads these
 * constants so there is a single source of truth at runtime.
 *
 * ## SSR vs client split (v0.9.9 plan 033)
 *
 * Next.js requires the ``NEXT_PUBLIC_*`` prefix for env vars
 * to be available on the client. The current ``API_BASE_URL``
 * is server-side only (the fetchers in ``lib/api.ts`` are only
 * called from Server Components, never from Client
 * Components).
 *
 * A future Client Component that needs the URL should import
 * :data:`displayedApiBaseUrl` (which is the same value as
 * ``API_BASE_URL`` but exposed as a stable named symbol) OR
 * the ``NEXT_PUBLIC_API_BASE_URL`` env var (which Next.js
 * inlines at build time so it is available on the client).
 * Do NOT import ``API_BASE_URL`` directly into a Client
 * Component -- the value would be the build-time value, not
 * the runtime value.
 *
 * ## Production validation (v0.9.9 plan 033)
 *
 * In production (``NODE_ENV === \"production\"``), the
 * module-load check fails fast if ``API_BASE_URL`` is unset
 * or invalid. In dev, the localhost fallback is preserved so
 * the dev loop works without any env var setup.
 */

// Raw, untrimmed value. May be undefined.
const RAW_API_BASE_URL = process.env.API_BASE_URL?.trim();

/**
 * Trimmed, trailing-slash-stripped, validated URL.
 *
 * - In dev (``NODE_ENV !== \"production\"``): the
 *   ``API_BASE_URL`` env var is used if set; otherwise the
 *   localhost fallback is used.
 * - In production: the ``API_BASE_URL`` env var is REQUIRED;
 *   the module throws at load time if it is unset. The URL
 *   is validated via ``new URL()`` to fail fast on typos.
 */
function _resolveApiBaseUrl(): string {
  const raw = RAW_API_BASE_URL;
  // Guard: this module is sometimes imported transitively by
  // Client Components (e.g. via ``@/lib/api``). Next.js bundles
  // those imports for the browser, where ``process.env.API_BASE_URL``
  // is undefined unless it is prefixed with ``NEXT_PUBLIC_``. The
  // server-side fetchers still read the env var at runtime, so the
  // production assertion only needs to run on the server. Skipping
  // the throw on the client prevents hydration crashes while keeping
  // the fail-fast behaviour for server boot / SSR.
  const isServer = typeof window === "undefined";
  if (process.env.NODE_ENV === "production" && isServer) {
    if (!raw) {
      throw new Error(
        "API_BASE_URL is required in production. Set it " +
          "in your deployment environment (e.g. Caddy, " +
          "Docker, Kubernetes) or in a `.env.production` " +
          "file. The localhost fallback is intentionally " +
          "disabled in production.",
      );
    }
    try {
      // The URL constructor validates the URL. A typo or a
      // non-URL throws ``TypeError``.
      const parsed = new URL(raw);
      // Strip trailing slashes from the pathname (the
      // ``origin`` alone is a hostname; the pathname is
      // usually \"/\" which we strip).
      return parsed.origin + parsed.pathname.replace(/\/+$/, "");
    } catch (err) {
      throw new Error(
        `API_BASE_URL is not a valid URL: ${raw!}. ` +
          `Error: ${
            err instanceof Error ? err.message : String(err)
          }`,
        { cause: err },
      );
    }
  }
  // Dev: localhost fallback if unset. Strip trailing slashes
  // from the trimmed value.
  return (raw ?? "http://localhost:8000").replace(/\/+$/, "");
}

const API_BASE_URL = _resolveApiBaseUrl();

export { API_BASE_URL };

/**
 * User-facing display string for the gateway base URL.
 *
 * Same value as ``API_BASE_URL``; exported as a stable named
 * symbol so SSR components cannot drift from the trimmed +
 * validated URL the fetcher actually uses.
 */
export const displayedApiBaseUrl = API_BASE_URL;

/**
 * Client-side alias for the gateway base URL (v0.9.9
 * plan 033). When a future Client Component needs the URL,
 * it should import ``clientApiBaseUrl`` rather than
 * ``API_BASE_URL`` -- ``clientApiBaseUrl`` is sourced from
 * the ``NEXT_PUBLIC_API_BASE_URL`` env var (which Next.js
 * inlines at build time so it is available on the client).
 * Unset in dev (falls back to ``displayedApiBaseUrl`` so the
 * landing hero footer still renders).
 */
export const clientApiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "") ??
  displayedApiBaseUrl;
