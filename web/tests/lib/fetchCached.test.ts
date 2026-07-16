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
// Locks the wire-contract parsing precedence. The branches in
// ``fetchCached.ts`` run in a fixed ORDER -- a future refactor that
// reorders them MUST update these specs + this comment block
// together so the contract remains a single source of truth.
//
// Precedence contract (from ``fetchCached.ts``, the 5 ``if`` lines
// inside the ``fetch().then(...)`` callback):
//
//     detail precedence (assignment, NOT overwrite):
//       (a) parsed.detail as a top-level string  - highest
//       (b) parsed.detail.detail (nested string)  - fall-back if (a) is null/object
//       (c) raw response text                     - default
//
//     error_code precedence (assignment WITH last-wins overwrite):
//       (i)  parsed.detail.error_code  (nested shape)   - SET FIRST
//       (ii) parsed.error_code         (flat envelope)  - OVERWRITES (i)
//
// The asymmetry (detail uses fall-back, error_code uses overwrite)
// is what the current code does: the bottom ``if`` is UNCONDITIONAL.
// This means a present flat envelope ALWAYS beats a nested
// ``error_code`` even if both are populated. Today only one shape
// exists per endpoint (no coexistence) so the precedence is harmless.
// If a future v0.11 refactor introduces mixed envelopes (CDN
// rewrites / proxy adapters), the precedence determines which
// discriminator the consumers see -- the /fights/[id] page branches
// on EVENTS_UNAVAILABLE which today's blob_loader.py emits ONLY in
// the nested shape, so the flat envelope currently surfaces no
// error_code and the nested path is the discriminator's source of
// truth.
//
// The specs below pin BOTH the "nested-only" path AND the
// "flat-overwrites-nested" path so a future flip is a CI-visible
// diff (you cannot satisfy all of these tests AND change the code
// without explicitly updating them together).
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

  it("does NOT crash when the nested shape's ``detail`` field is null", async () => {
    // Edge case: the API may legitimately return ``{detail: null}`` if
    // the gateway short-circuits an error before building the nested
    // envelope (e.g. a FastAPI handler that returns ``HTTPException``
    // without a JSON detail). The fetchCached.ts guard
    // ``parsed.detail && typeof parsed.detail === "object"`` is the
    // CRITICAL null-safety: the ``&&`` short-circuits when
    // ``parsed.detail`` is null (null is falsy), so the ``else if``
    // branch is skipped AND the bottom ``if`` runs the flat check.
    //
    // Pin this so a future maintainer who refactors the guard to
    // ``typeof parsed.detail === "object"`` WITHOUT the null check
    // gets a TypeError in CI instead of a production 500.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ detail: null, error_code: "GATEWAY_NULL" }),
        { status: 502 },
      ),
    );
    const err = (await fetchCached(
      "http://test/api/v1/shape-5-null-nested-detail",
    ).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(502);
    // Flat error_code wins (the nested path is skipped because
    // parsed.detail is null -- the ``else if`` requires both
    // truthy AND object).
    expect(err.error_code).toBe("GATEWAY_NULL");
    // Tighten the message to ``toBe`` (NOT ``toContain`` -- the
    // previous hardening pass used just ``error_code`` which did
    // not pin the verbatim-fallback). The ``else if`` guard
    // ``parsed.detail && typeof ... === "object"`` is the
    // null-safety contract; the unexpected path is
    // ``message = parsed.error_code`` (substituting the code for
    // the body), which would still pass a too-loose assertion.
    // ``JSON.stringify`` of the same fixture is deterministic
    // (no whitespace + insertion-order keys), so equality is
    // stable across vitest runs.
    expect(err.message).toBe(
      JSON.stringify({ detail: null, error_code: "GATEWAY_NULL" }),
    );
  });

  it("falls back to raw JSON when nested shape has only nested.error_code (no nested inner 'detail')", async () => {
    // Edge case: an envelope like ``{detail: {error_code: "X"}}``
    // with NO inner ``detail`` string. fetchCached.ts's inner
    // assignment requires ``typeof parsed.detail.detail === "string"``;
    // if missing, the inner detail stays undefined and the outer
    // ``detail = raw_text`` default surfaces. Pin this so a future
    // refactor that changes the guard to ``parsed.detail.detail !==
    // undefined`` doesn't silently surface ``undefined`` in the
    // ApiError message.
    //
    // Also pins that the flat ``error_code`` still OVERWRITES the
    // nested one even when the nested envelope doesn't carry an
    // inner ``detail``. The two channels are paired: when nested
    // wins on detail, flat wins on error_code.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { error_code: "NESTED_ONLY" },
          error_code: "FLAT_BEATS_NESTED_ONLY",
        }),
        { status: 503 },
      ),
    );
    const err = (await fetchCached(
      "http://test/api/v1/shape-6-nested-no-inner-detail",
    ).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(503);
    // Flat OVERWRITES nested error_code (the locked contract).
    expect(err.error_code).toBe("FLAT_BEATS_NESTED_ONLY");
    // Tighten the raw-text fallback contract with ``toBe`` (NOT
    // ``toContain`` -- the previous hardening pass asserted
    // ``toContain(\"FLAT_BEATS_NESTED_ONLY\")`` AND
    // ``toContain(\"NESTED_ONLY\")``, both of which were too
    // loose: a refactor that maps ``detail = parsed.error_code``
    // (a misguided optimization that would put the flat code in
    // the message body) ALSO produces a message that contains
    // both substrings, so the old assertions would silently
    // pass. ``JSON.stringify`` of the same fixture is
    // deterministic (no whitespace + insertion-order keys), so
    // equality is stable across vitest runs AND locks the
    // raw-text fallback semantic -- a refactor that diverges
    // from ``detail = text`` (the typedef-defaulted value at
    // the top of the ``if/else if`` chain) breaks the assertion.
    expect(err.message).toBe(
      JSON.stringify({
        detail: { error_code: "NESTED_ONLY" },
        error_code: "FLAT_BEATS_NESTED_ONLY",
      }),
    );
  });
});
