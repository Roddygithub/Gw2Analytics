/**
 * v0.10.17 D1: thin wrapper around :func:`fetchCached` that fetches
 * the per-fight timeline rollup used as the
 * :class:`ReplayPlayer` playback substrate.
 *
 * Why a wrapper (vs inlining :func:`fetchCached` inside the
 * component)
 * ===============================================================
 * The :class:`ReplayPlayer` component owns the playback concerns
 * (scrubber, play/pause, speed toggle, per-bucket visualisation).
 * Mirroring :func:`fetchCached` directly inside the component would
 * couple those concerns to the URL construction (``?window_s=...``
 * templating), the cache-key derivation, and the response typing. The
 * wrapper exposes ONE typed entry point
 * (:func:`fetchReplayTimeline`) that hides the URL template + cache
 * wiring behind a single function call. A future cycle that swaps
 * the substrate from ``/timeline`` (per-bucket rollup) to a new
 * ``/events-blob`` endpoint (gzipped JSONL events) only touches
 * this wrapper -- every consumer continues to call
 * :func:`fetchReplayTimeline` unchanged.
 *
 * Why :func:`fetchCached` (vs raw ``fetch``)
 * ==========================================
 * The page.tsx Server Component already loads the per-fight
 * timeline via :func:`fetchCached` for its existing render path.
 * Re-using the same substrate inside the ReplayPlayer keeps the
 * LRU + TTL + dedup + no-cache-on-error (the v0.10.14 D2 + v0.10.17
 * D4 close-out contracts) consistent across both surfaces: the
 * Replay tab + the page's timeline chart share the cache, so the
 * navigation from the timeline section to the Replay tab is a
 * cache hit (no second MinIO round-trip).
 *
 * Why the per-bucket substrate (vs the raw gzipped events blob)
 * ==============================================================
 * The per-fight replay ideally subscribes to the raw events
 * JSONL blob for per-event fidelity (per-skill attribution,
 * per-target attribution within a bucket, sub-bucket scrubbing).
 * The current cycle's brief constraint ("D1 does NOT touch the
 * backend") -- and the absence of a public gateway endpoint that
 * exposes the raw blob -- bound the substrate to the per-bucket
 * /timeline rollup. Per-event fidelity is deferred to a future
 * cycle when a /events-blob gateway endpoint lands.
 */

import { fetchCached } from "./fetchCached";
import type { FightTimeline } from "./api/fights";

/** Options for :func:`fetchReplayTimeline`. */
export interface ReplayTimelineOptions {
  /**
   * The bucket-granularity window size in seconds. The gateway
   * returns one ``PerFightTimelinePoint`` per ``window_s`` of
   * fight duration; typical values are 5 (the page default),
   * 10, 30, or 60. The ReplayPlayer scrubs between buckets at
   * this granularity (1x speed advances one bucket per
   * ``window_s`` of wall-clock time, scaled by the speed toggle).
   */
  windowS: number;
}

/**
 * Fetch the per-fight timeline rollup for the given fight id +
 * bucket window. Pure pass-through to :func:`fetchCached` with the
 * canonical ``/api/v1/fights/{id}/timeline?window_s=...`` URL
 * template. The cached envelope (``LRU + TTL + dedup``) is
 * preserved across calls so a navigation from the page's
 * timeline section to the Replay tab is a cache hit.
 */
export async function fetchReplayTimeline(
  fightId: string,
  apiBaseUrl: string,
  options: ReplayTimelineOptions,
): Promise<FightTimeline> {
  if (!Number.isFinite(options.windowS) || options.windowS < 1) {
    throw new Error(
      `ReplayTimelineOptions.windowS must be >= 1, got ${options.windowS}`,
    );
  }
  // v0.10.17 D1 round-2 fix: the wrapper URL omits the
  // ``?window_s=`` query param when ``windowS === 5`` (the
  // gateway default). This MATCHES the inline URL pattern
  // the page.tsx Server Component used pre-D1 -- so the
  // fetchCached cache key stays the same across the wrapper
  // adoption (a 5-second-window fetch via the wrapper hits
  // the same cache entry as the pre-wrapper inline call).
  // Without this, the wrapper would generate a DIFFERENT cache
  // key for the default window case (cache MISS after the
  // fetchCached LRU is warm), doubling the gateway load on
  // every Replay-tab navigation.
  const qs = options.windowS !== 5 ? `?window_s=${options.windowS}` : "";
  const url =
    `${apiBaseUrl}/api/v1/fights/${encodeURIComponent(fightId)}` +
    `/timeline${qs}`;
  return await fetchCached<FightTimeline>(url);
}
