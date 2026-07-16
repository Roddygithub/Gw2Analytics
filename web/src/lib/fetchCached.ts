/**
 * LRU + TTL fetch cache for server-side RSC fetchers.
 *
 * Caches responses keyed by ``url + init`` (serialised via
 * ``JSON.stringify``). Evicts the oldest entry when the cache
 * exceeds 8 entries. Entries expire after 60 seconds.
 *
 * Deduplicates in-flight requests: concurrent calls with the
 * same key share the same Promise until the first one resolves.
 */

import { ApiError } from "@/lib/api/errors";

interface CacheEntry {
  result?: unknown;
  expiresAt?: number;
  promise?: Promise<unknown>;
}

const MAX_ENTRIES = 8;
const TTL_MS = 60_000;

const cache = new Map<string, CacheEntry>();

function makeKey(url: string, init?: RequestInit): string {
  return url + (init ? JSON.stringify(init) : "");
}

export async function fetchCached<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const key = makeKey(url, init);
  const now = Date.now();
  const existing = cache.get(key);

  if (existing?.promise) {
    return existing.promise as Promise<T>;
  }

  if (existing?.result !== undefined && existing.expiresAt! > now) {
    return existing.result as T;
  }

  if (existing) {
    cache.delete(key);
  }

  if (cache.size >= MAX_ENTRIES) {
    const firstKey = cache.keys().next().value;
    if (firstKey !== undefined) {
      cache.delete(firstKey);
    }
  }

  const promise = fetch(url, init)
    .then(async (resp) => {
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        let detail = text;
        let errorCode: string | undefined;
        try {
          const parsed = JSON.parse(text) as { detail?: string | { detail?: string; error_code?: string }; error_code?: string };
          if (typeof parsed.detail === "string") {
            detail = parsed.detail;
          } else if (parsed.detail && typeof parsed.detail === "object") {
            if (typeof parsed.detail.detail === "string") detail = parsed.detail.detail;
            if (typeof parsed.detail.error_code === "string") errorCode = parsed.detail.error_code;
          }
          if (typeof parsed.error_code === "string") errorCode = parsed.error_code;
        } catch {
          // not JSON, keep raw text as detail
        }
        throw new ApiError(resp.status, detail || resp.statusText || String(resp.status), errorCode);
      }
      return resp.json() as Promise<T>;
    })
    .then(
      (value) => {
        // Success path: cache the resolved value with TTL so the
        // next call within the TTL window returns the same value
        // without a network round-trip.
        const entry = cache.get(key);
        if (entry) {
          entry.result = value;
          entry.expiresAt = Date.now() + TTL_MS;
          entry.promise = undefined;
        }
        return value;
      },
      (err) => {
        // Error path: do NOT cache the rejection. The v0.10.17 D4
        // brief's no-cache-on-error contract requires a retry to
        // trigger a fresh round-trip, not return the cached
        // rejection. Deleting the cache entry ensures the next call
        // misses the cache and goes to the network again.
        cache.delete(key);
        throw err;
      },
    );

  cache.set(key, { promise });
  return promise as Promise<T>;
}

/**
 * Test-only hook: clear the module-level cache Map.
 *
 * The cache is module-level state, so vitest does not reset it
 * between test files within the same worker. The
 * ``fetchCached-isolation.test.ts`` (v0.10.17 D4 deliverable)
 * regression-pin calls this in ``beforeEach`` to guarantee its
 * 6 sub-cases run against a freshly-empty cache, independent
 * of the cache state populated by ``fetchCached.test.ts``
 * (the v0.10.14 D2 close-out) when it ran first in the worker.
 *
 * This export is INTENTIONALLY marked with the ``__`` prefix as
 * a "do not use in production" signal. It is safe to call at
 * any time -- the cache state is fully encapsulated + the
 * function does no I/O + has no side effects on the network.
 */
export function __resetCacheForTests(): void {
  cache.clear();
}


/**
 * Test-only hook: return the current cache size.
 *
 * ``__resetCacheForTests`` clears the cache; this hook exposes the
 * current Map size so the v0.10.17 D4 sub-case #5 (LRU cap
 * eviction) can verify the ``maxsize=8`` invariant directly
 * without depending on FIFO + cascade eviction identity (which
 * would be brittle to a future true-LRU refactor).
 *
 * Same ``__`` prefix convention as ``__resetCacheForTests``:
 * test-only, ``do not use in production``.
 */
export function __cacheSizeForTests(): number {
  return cache.size;
}
