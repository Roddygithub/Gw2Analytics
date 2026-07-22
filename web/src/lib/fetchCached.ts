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
        }
        throw new ApiError(resp.status, detail || resp.statusText || String(resp.status), errorCode);
      }
      return resp.json() as Promise<T>;
    })
    .then(
      (value) => {
        const entry = cache.get(key);
        if (entry) {
          entry.result = value;
          entry.expiresAt = Date.now() + TTL_MS;
          entry.promise = undefined;
        }
        return value;
      },
      (err) => {
        cache.delete(key);
        throw err;
      },
    );

  cache.set(key, { promise });
  return promise as Promise<T>;
}

export const __resetCacheForTests = process.env.NODE_ENV === "test"
  ? () => { cache.clear(); }
  : () => {};
export const __cacheSizeForTests = process.env.NODE_ENV === "test"
  ? () => cache.size
  : () => 0;
