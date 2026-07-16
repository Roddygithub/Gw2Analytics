import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchCached } from "@/lib/fetchCached";
import { ApiError } from "@/lib/api/errors";

describe("fetchCached", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("returns the fetched value", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const result = await fetchCached<{ ok: boolean }>("http://test/api/v1/data");
    expect(result).toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("deduplicates concurrent in-flight requests", async () => {
    let callCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      callCount++;
      return Promise.resolve(
        new Response(JSON.stringify({ count: callCount }), { status: 200 }),
      );
    });

    const [a, b] = await Promise.all([
      fetchCached<{ count: number }>("http://test/api/v1/dedup"),
      fetchCached<{ count: number }>("http://test/api/v1/dedup"),
    ]);

    expect(a).toEqual(b);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("evicts oldest entry when cache is full (LRU 8)", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((url) =>
      Promise.resolve(
        new Response(JSON.stringify({ url }), { status: 200 }),
      ),
    );

    for (let i = 0; i < 9; i++) {
      await fetchCached(`http://test/api/v1/page/${i}`);
    }

    expect(fetch).toHaveBeenCalledTimes(9);

    // Entry 0 should have been evicted; re-fetching it triggers a new fetch
    await fetchCached("http://test/api/v1/page/0");
    expect(fetch).toHaveBeenCalledTimes(10);
  });

  it("returns cached value within TTL window", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ts: 1 }), { status: 200 }),
    );

    const first = await fetchCached<{ ts: number }>("http://test/api/v1/ttl");
    expect(first).toEqual({ ts: 1 });

    // 30s later — still cached
    vi.advanceTimersByTime(30_000);
    const second = await fetchCached<{ ts: number }>("http://test/api/v1/ttl");
    expect(second).toEqual({ ts: 1 });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("expires after TTL and re-fetches", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ts: 1 }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ts: 2 }), { status: 200 }),
      );

    await fetchCached<{ ts: number }>("http://test/api/v1/ttl-expire");

    // 61s later — expired
    vi.advanceTimersByTime(61_000);
    const result = await fetchCached<{ ts: number }>("http://test/api/v1/ttl-expire");
    expect(result).toEqual({ ts: 2 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("propagates non-200 as an error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not found", { status: 404 }),
    );

    const err = (await fetchCached("http://test/api/v1/missing").catch(
      (e) => e,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe("not found");
  });
});
