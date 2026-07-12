/**
 * v0.10.17 D5 deliverable: cross-component anti-regression pin for the
 * :func:`fetchReplayTimeline` wrapper + the
 * :class:`ReplayPlayer` -> :func:`fetchCached` substrate contract.
 *
 * What is pinned (per the v0.10.17 D5 brief)
 * ==========================================
 *
 *   1. **URL construction omits ``?window_s=`` when ``windowS === 5``**
 *      (the gateway default). The D1 round-2 fix landed this
 *      precise behaviour so the wrapper URL collapses to a string
 *      IDENTICAL to the page's pre-D1 inline ``fetchCached`` call's
 *      URL key; the LRU substrate stays warm across the
 *      Overview <-> Replay tab toggle.
 *
 *   2. **URL construction includes ``?window_s=N`` when
 *      ``windowS !== 5``. Non-default windows produce a
 *      cache-key-shaped URL distinct from the default.
 *
 *   3. **URL ``encodeURIComponent`` defensiveness**: a fight id
 *      containing reserved URL characters is escaped to a valid
 *      URL rather than breaking the wrapper's contract.
 *
 *   4. **Invalid ``windowS`` rejection**: ``0``, ``-1``, and
 *      ``NaN`` all throw (the wrapper pre-validates BEFORE the
 *      gateway call).
 *
 *   5. **``fetchCached`` error propagation**: the wrapper
 *      surfaces the upstream error unmodified (the page.tsx
 *      ``Promise.allSettled`` consumes this rejection to flip
 *      the per-section error chimp).
 *
 *   6. **LRU cache hit across calls**. The wrapper preserves
 *      the underlying :func:`fetchCached` TTL contract: 2 same-
 *      windowS calls within 60 s result in 1 network round-trip,
 *      a 60 s+ later same call results in 1 new round-trip. This
 *      is the substrate leg of the cross-component contract --
 *      pinned here so a future wrapper refactor cannot silently
 *      bypass the LRU.
 *
 * Why D5 IS distinct from D4 (fetchCached isolation)
 * ==================================================
 *
 * The v0.10.17 D4 file (:file:`web/tests/lib/fetchCached-isolation.test.ts`)
 * pins the :func:`fetchCached` LRU + TTL + dedup + no-cache-on-error
 * substrate in pure isolation (6 sub-cases, one per behaviour).
 * D5 pins the WRAPPER layer ABOVE that substrate: URL construction
 * choices, validation ordering, encoding, error propagation, AND the
 * wrapper's preservation of the cache-key contract (the round-2
 * fix). A regression that changes the wrapper without breaking the
 * substrate (e.g. a future maintainer reverts the ``windowS === 5``
 * special-case) would PASS D4 BUT FAIL D5.
 *
 * The 6 pinned behaviours (per the v0.10.17 D5 brief)
 * ====================================================
 *
 *   1. URL omits ``?window_s=`` when ``windowS === 5``.
 *   2. URL includes ``?window_s=`` when ``windowS !== 5``.
 *   3. URL ``encodeURIComponent`` defensiveness on ``fightId``.
 *   4. Invalid ``windowS`` rejection.
 *   5. ``fetchCached`` error propagation.
 *   6. LRU cache hit across calls within TTL.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchReplayTimeline } from "@/lib/replayFetcher";
import {
  __resetCacheForTests,
  __cacheSizeForTests,
} from "@/lib/fetchCached";

const FIGHT_ID = "abc123def456";
const BASE_URL = "http://test/api";

/** A minimal :class:`FightTimeline` mock JSON body for happy-path responses. */
function makeTimelineJson(overrides: Partial<{
  fight_id: string;
  window_s: number;
  duration_s: number;
  points: unknown[];
}> = {}) {
  return JSON.stringify({
    fight_id: FIGHT_ID,
    window_s: 5,
    duration_s: 30,
    points: [],
    ...overrides,
  });
}

describe("fetchReplayTimeline wrapper substrate contract (v0.10.17 D5)", () => {
  beforeEach(() => {
    // Fake timers for the TTL boundary test (sub-case 6); the
    // synchronous URL-construction tests are unaffected by the
    // timer config but ``__resetCacheForTests`` is needed to
    // guarantee a clean cache regardless of vitest worker order
    // (the D4 isolation test runs first in the same worker and
    // populates the cache if we don't reset).
    vi.useFakeTimers();
    __resetCacheForTests();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("1. URL omits ?window_s= when windowS=5 (gateway default; preserves the pre-D1 fetchCached cache key)", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(makeTimelineJson({ window_s: 5 }), { status: 200 }),
      );

    await fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 5 });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    // The URL MUST be exactly `${base}/api/v1/fights/${id}/timeline`
    // (no `?window_s=` suffix) so the cache key matches the page's
    // pre-D1 inline pattern. Any future regression that re-introduces
    // the always-include `?window_s=5` will fail this assertion --
    // the cache-key preservation contract is broken.
    expect(fetchSpy.mock.calls[0][0]).toBe(
      `${BASE_URL}/api/v1/fights/${encodeURIComponent(FIGHT_ID)}/timeline`,
    );
  });

  it("2. URL includes ?window_s=N when windowS!==5 (non-default window cache-key distinct from default)", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(makeTimelineJson({ window_s: 10 }), { status: 200 }),
      );

    await fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 10 });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe(
      `${BASE_URL}/api/v1/fights/${encodeURIComponent(FIGHT_ID)}/timeline?window_s=10`,
    );
    // Verify the cache key does NOT match the default-window key
    // (a 10 s window fetches a different cache entry than a 5 s
    // window -- the LRU is keyed on ``${base}/timeline${qs}``).
    expect(__cacheSizeForTests()).toBe(1);
  });

  it("3. URL encodeURIComponent defensiveness on fightId (no special-char injection)", async () => {
    const fightIdWithReservedChars = "has space&slash?param=value";
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(makeTimelineJson(), { status: 200 }),
      );

    await fetchReplayTimeline(fightIdWithReservedChars, BASE_URL, {
      windowS: 5,
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const calledUrl = String(fetchSpy.mock.calls[0][0]);
    // The reserved characters MUST be percent-encoded so the URL
    // is valid (the gateway would otherwise parse?param=value as
    // a query string and miss the resource path).
    expect(calledUrl).toContain("has%20space%26slash%3Fparam%3Dvalue");
    // The URL MUST end with the suffix (no rogue query separator
    // injected via the un-escaped fightId).
    expect(calledUrl.endsWith("/timeline")).toBe(true);
  });

  it("4. Throws Error on invalid windowS (0, negative, NaN) BEFORE the gateway call", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(makeTimelineJson(), { status: 200 }),
      );

    // The validation rejects these inputs BEFORE the
    // gateway call -- ``fetchSpy`` must remain untouched.
    await expect(
      fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 0 }),
    ).rejects.toThrow(/must be >= 1/);
    await expect(
      fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: -1 }),
    ).rejects.toThrow(/must be >= 1/);
    await expect(
      fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: Number.NaN }),
    ).rejects.toThrow(/must be >= 1/);
    // No fetch attempted (validation rejection is upstream
    // of the network layer).
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("5. Propagates fetchCached errors (4xx, 5xx, network) unmodified to the caller", async () => {
    // Simulate a 502 Bad Gateway (the gateway returning an
    // upstream MinIO outage code). The wrapper must surface the
    // rejection (the page's ``Promise.allSettled`` consumes this
    // to flip the per-section error chimp).
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("upstream gateway failure", { status: 502 }),
    );
    await expect(
      fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 5 }),
    ).rejects.toThrow(/502/);

    // Simulate a network rejection (the globalThis.fetch resolves
    // to a rejected promise). The wrapper must propagate.
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("ECONNREFUSED"),
    );
    await expect(
      fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 5 }),
    ).rejects.toThrow(/ECONNREFUSED/);
  });

  it("6. LRU cache hit across calls within 60s TTL (the wrapper preserves the underlying fetchCached substrate contract)", async () => {
    // Use ``mockImplementation`` (NOT ``mockResolvedValue``) so each
    // ``globalThis.fetch`` call returns a FRESH ``Response`` with its
    // own body stream. ``mockResolvedValue`` would return the SAME
    // ``Response`` object across all 3 calls below; after the first
    // call's body is read (via ``resp.json()`` in fetchCached's success
    // handler), the third call would hit ``TypeError: Body is
    // unusable: Body has already been read``. ``mockImplementation``
    // creates a fresh ``new Response(...)`` per call so the body
    // stream is unconsumed on each invocation.
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() =>
        Promise.resolve(
          new Response(makeTimelineJson({ window_s: 5 }), { status: 200 }),
        ),
      );

    // First call: 1 fetch (cache MISS, fills the entry).
    await fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 5 });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(__cacheSizeForTests()).toBe(1);

    // Second call within TTL: still 1 fetch (cache HIT -- the
    // wrapper's URL key matches the first call's key so the
    // LRU returns the cached payload).
    vi.advanceTimersByTime(30_000);
    await fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 5 });
    expect(fetchSpy).toHaveBeenCalledTimes(1); // cache hit

    // Third call after TTL: 2 fetches total (cache MISS due to
    // expiry, refetches the resource). The fetch returns a FRESH
    // ``Response`` (per ``mockImplementation`` above) so the body
    // stream is unconsumed and ``resp.json()`` succeeds the second
    // time around.
    vi.advanceTimersByTime(60_001);
    await fetchReplayTimeline(FIGHT_ID, BASE_URL, { windowS: 5 });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(__cacheSizeForTests()).toBe(1); // cap still respected
  });
});
