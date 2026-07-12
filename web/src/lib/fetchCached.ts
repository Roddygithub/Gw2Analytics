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
        throw new Error(`${resp.status}: ${text}`);
      }
      return resp.json() as Promise<T>;
    })
    .finally(() => {
      const entry = cache.get(key);
      if (entry) {
        entry.result = entry.promise;
        entry.expiresAt = Date.now() + TTL_MS;
        entry.promise = undefined;
      }
    });

  cache.set(key, { promise });
  return promise as Promise<T>;
}
