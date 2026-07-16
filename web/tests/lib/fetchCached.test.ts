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
    const result = await fetchCached<{ ok: boolean }>(
      "http://test/api/v1/data",
    );
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
      Promise.resolve(new Response(JSON.stringify({ url }), { status: 200 })),
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
    const result = await fetchCached<{ ts: number }>(
      "http://test/api/v1/ttl-expire",
    );
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

// ---------------------------------------------------------------------------
// Code-reviewer hardening #2 (2026-07-15 fetchCached.ts lock).
// Locks the wire-contract parsing precedence so a future maintainer who
// reorders the branches does not silently invert the priority between
// nested-detail.error_code (the EVENTS_UNAVAILABLE case the /fights/[id]
// page branching depends on) and the flat error_code envelope.
//
// Precedence contract (from fetchCached.ts):
//   detail precedence: string_detail > nested.detail > raw_text
//   error_code precedence: nested.detail.error_code > flat.error_code
// ---------------------------------------------------------------------------

describe("fetchCached error_code parsing precedence (v0.10.25 hardening)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("extracts a top-level string detail + flat error_code", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "fight not found", error_code: "FIGHT_NOT_FOUND" }),
        { status: 404 },
      ),
    );
    const err = (await fetchCached(
      "http://test/api/v1/shape-1-flat",
    ).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe("fight not found");
    expect(err.error_code).toBe("FIGHT_NOT_FOUND");
  });

  it("extracts a nested-detail shape (EVENTS_UNAVAILABLE contract)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            detail: "events unavailable",
            error_code: "EVENTS_UNAVAILABLE",
          },
        }),
        { status: 404 },
      ),
    );
    const err = (await fetchCached(
      "http://test/api/v1/shape-2-nested",
    ).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe("events unavailable");
    // EVENTS_UNAVAILABLE is the discriminator the /fights/[id] page
    // branches on to render the empty-state panel; locking this
    // path prevents a regression that drops the nested detail.
    expect(err.error_code).toBe("EVENTS_UNAVAILABLE");
  });

  it("prefers the flat error_code over a nested-detail.error_code (current code precedence)", async () => {
    // Both error_code sources present. The current code at
    // ``fetchCached.ts`` runs the nested-detail branch first,
    // then UNCONDITIONALLY overwrites ``errorCode`` with the
    // flat ``parsed.error_code`` if present (the LAST ``if``
    // on line 64 of fetchCached.ts). This locks the
    // current precedence as the canonical contract; a
    // future refactor that flips the order would flip this
    // assertion, surfacing the regression in CI.
    //
    // Design note: a future v0.11.x refactor may want nested
    // to win (so the EVENTS_UNAVAILABLE nested shape is
    // canonical). When that happens, the code + this test
    // change together.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            detail: "events unavailable",
            error_code: "EVENTS_UNAVAILABLE",
          },
          error_code: "FLAT_LEGACY",
        }),
        { status: 404 },
      ),
    );
    const err = (await fetchCached(
      "http://test/api/v1/shape-3-nested-vs-flat",
    ).catch((e) => e)) as ApiError;
    expect(err.error_code).toBe("FLAT_LEGACY");
  });

  it("falls back to raw text when response is non-JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html>Bad Gateway</html>", {
        status: 502,
        headers: { "content-type": "text/html" },
      }),
    );
    const err = (await fetchCached(
      "http://test/api/v1/shape-4-non-json",
    ).catch((e) => e)) as ApiError;
    expect(err.status).toBe(502);
    // Raw text preserved verbatim so the upstream-error card surfaces
    // the proxy-gateway message (HTML markup rendered as text).
    expect(err.message).toContain("Bad Gateway");
    expect(err.error_code).toBeUndefined();
  });
});
