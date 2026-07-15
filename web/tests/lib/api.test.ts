/**
 * Unit tests for the API client wrappers in :mod:`@/lib/api`.
 *
 * These are thin ``fetch()`` wrappers; the tests pin the
 * happy-path request shaping and the ``ApiError`` throw on
 * non-2xx responses. They do NOT hit a real backend --
 * ``globalThis.fetch`` is mocked per-test.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  ApiError,
  formatApiError,
  fetchPlayers,
  fetchPlayer,
  fetchPlayerTimeline,
  fetchPlayerCompareTimeline,
  fetchFights,
  fetchFight,
  fetchFightEvents,
  fetchFightSquads,
  fetchFightSkills,
  fetchFightTimeline,
  fetchFightPlayerTimeline,
  fetchFightPlayerSkills,
  fetchFightReadout,
  uploadLog,
  fetchUploadStatus,
  fetchWebhookDeliveries,
  replayDlq,
  resolveAccount,
  resolveAccountViaProxy,
} from "@/lib/api";

const mockFetch = vi.fn();

beforeEach(() => {
  mockFetch.mockReset();
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const okResponse = (body: unknown) =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response);

const errorResponse = (status: number, body: string) =>
  Promise.resolve({
    ok: false,
    status,
    json: () => Promise.reject(new Error("no json")),
    text: () => Promise.resolve(body),
  } as Response);

describe("ApiError + formatApiError", () => {
  it("carries status and message", () => {
    const err = new ApiError(404, "not found");
    expect(err.status).toBe(404);
    expect(err.message).toContain("not found");
  });

  it("formats ApiError with the upstream prefix", () => {
    const err = new ApiError(500, "boom");
    expect(formatApiError(err)).toContain("500: boom");
  });

  it("formats generic Error instances", () => {
    expect(formatApiError(new Error("oops"))).toBe("oops");
  });

  it("stringifies non-error values", () => {
    expect(formatApiError(42)).toBe("42");
  });
});

describe("players API", () => {
  it("fetchPlayers requests /api/v1/players with query params", async () => {
    mockFetch.mockResolvedValueOnce(okResponse([{ account_name: "A.1" }]));
    const rows = await fetchPlayers({ limit: 10, offset: 5, profession: "MESMER" });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/players?limit=10&offset=5&profession=MESMER"),
      expect.any(Object),
    );
    expect(rows).toEqual([{ account_name: "A.1" }]);
  });

  it("fetchPlayers throws on non-array upstream", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fights: [] }));
    await expect(fetchPlayers()).rejects.toBeInstanceOf(ApiError);
  });

  it("fetchPlayer requests the profile endpoint", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ account_name: "A.1" }));
    await fetchPlayer("A.1");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/players/A.1"),
      expect.any(Object),
    );
  });

  it("fetchPlayerTimeline requests the timeline with query params", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ account_name: "A.1", points: [] }));
    await fetchPlayerTimeline("A.1", { limit: 5, offset: 1, bucket: "day", tz: "UTC" });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/players/A.1/timeline?limit=5&offset=1&bucket=day&tz=UTC"),
      expect.any(Object),
    );
  });

  it("fetchPlayerCompareTimeline requests compare/timeline", async () => {
    mockFetch.mockResolvedValueOnce(okResponse([]));
    await fetchPlayerCompareTimeline(["A.1", "B.2"], { bucket: "day", tz: "UTC" });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/players/compare/timeline?"),
      expect.any(Object),
    );
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("accounts=A.1");
    expect(url).toContain("accounts=B.2");
  });
});

describe("fights API", () => {
  it("fetchFights requests /api/v1/fights and unwraps paginated page", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fights: [{ id: "f1" }] }));
    const rows = await fetchFights();
    expect(rows).toEqual([{ id: "f1" }]);
  });

  it("fetchFights handles legacy array response", async () => {
    mockFetch.mockResolvedValueOnce(okResponse([{ id: "f1" }]));
    const rows = await fetchFights();
    expect(rows).toEqual([{ id: "f1" }]);
  });

  it("fetchFights throws on non-array", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ not_fights: [] }));
    await expect(fetchFights()).rejects.toBeInstanceOf(ApiError);
  });

  it("fetchFight requests a single fight", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ id: "f1" }));
    await fetchFight("f1");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1"),
      expect.any(Object),
    );
  });

  it("fetchFightEvents requests events with window_s", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fight_id: "f1" }));
    await fetchFightEvents("f1", { windowS: 5 });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1/events?window_s=5"),
      expect.any(Object),
    );
  });

  it("fetchFightSquads requests squads", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fight_id: "f1", squads: [] }));
    await fetchFightSquads("f1");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1/squads"),
      expect.any(Object),
    );
  });

  it("fetchFightSkills requests skills", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fight_id: "f1", skills: [] }));
    await fetchFightSkills("f1");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1/skills"),
      expect.any(Object),
    );
  });

  it("fetchFightTimeline requests timeline with window_s", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fight_id: "f1", points: [] }));
    await fetchFightTimeline("f1", { windowS: 10 });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1/timeline?window_s=10"),
      expect.any(Object),
    );
  });

  it("fetchFightPlayerTimeline requests player timeline with window_s", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fight_id: "f1", series: [] }));
    await fetchFightPlayerTimeline("f1", { windowS: 10 });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1/timeline/players?window_s=10"),
      expect.any(Object),
    );
  });

  it("fetchFightPlayerSkills requests player skills", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fight_id: "f1", account_name: "A.1" }));
    await fetchFightPlayerSkills("f1", "A.1");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1/players/A.1/skills"),
      expect.any(Object),
    );
  });

  it("fetchFightReadout requests readout", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ fight_id: "f1", players: [] }));
    await fetchFightReadout("f1");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/fights/f1/readout"),
      expect.any(Object),
    );
  });
});

describe("upload API", () => {
  it("uploadLog POSTs a FormData file", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ id: "u1" }));
    const file = new File(["blob"], "test.zevtc");
    const result = await uploadLog(file);
    expect(result.id).toBe("u1");
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("fetchUploadStatus requests the upload status", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ id: "u1", status: "completed" }));
    const result = await fetchUploadStatus("u1");
    expect(result.status).toBe("completed");
  });
});

describe("webhooks API", () => {
  it("fetchWebhookDeliveries requests DLQ with filters", async () => {
    mockFetch.mockResolvedValueOnce(okResponse([{ id: "d1" }]));
    await fetchWebhookDeliveries({ subscriptionId: "s1", limit: 10, offset: 0 });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/webhooks/dlq?subscription_id=s1&limit=10&offset=0"),
      expect.any(Object),
    );
  });

  it("fetchWebhookDeliveries throws on non-array", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ rows: [] }));
    await expect(fetchWebhookDeliveries()).rejects.toBeInstanceOf(ApiError);
  });

  it("replayDlq POSTs replay endpoint", async () => {
    mockFetch.mockResolvedValueOnce(okResponse(undefined));
    await replayDlq("d1");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/webhooks/dlq/d1/replay"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("account API", () => {
  it("resolveAccount sends Authorization header", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ world_id: 1 }));
    await resolveAccount("key");
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(init.headers).toEqual({ Authorization: "Bearer key" });
  });

  it("resolveAccountViaProxy posts to BFF endpoint", async () => {
    mockFetch.mockResolvedValueOnce(okResponse({ world_id: 1 }));
    await resolveAccountViaProxy("key");
    expect(mockFetch.mock.calls[0][0]).toBe("/api/account/resolve");
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
  });
});

describe("error handling", () => {
  it.each([
    ["fetchPlayers", () => fetchPlayers()],
    ["fetchPlayer", () => fetchPlayer("A.1")],
    ["fetchPlayerTimeline", () => fetchPlayerTimeline("A.1")],
    ["fetchPlayerCompareTimeline", () => fetchPlayerCompareTimeline(["A.1"])],
    ["fetchFights", () => fetchFights()],
    ["fetchFight", () => fetchFight("f1")],
    ["fetchFightEvents", () => fetchFightEvents("f1")],
    ["fetchFightSquads", () => fetchFightSquads("f1")],
    ["fetchFightSkills", () => fetchFightSkills("f1")],
    ["fetchFightTimeline", () => fetchFightTimeline("f1")],
    ["fetchFightPlayerTimeline", () => fetchFightPlayerTimeline("f1")],
    ["fetchFightPlayerSkills", () => fetchFightPlayerSkills("f1", "A.1")],
    ["fetchFightReadout", () => fetchFightReadout("f1")],
    ["uploadLog", () => uploadLog(new File([""], "x"))],
    ["fetchUploadStatus", () => fetchUploadStatus("u1")],
    ["fetchWebhookDeliveries", () => fetchWebhookDeliveries()],
    ["replayDlq", () => replayDlq("d1")],
    ["resolveAccount", () => resolveAccount("key")],
    ["resolveAccountViaProxy", () => resolveAccountViaProxy("key")],
  ])("%s throws ApiError on non-2xx response", async (_name, fn) => {
    mockFetch.mockResolvedValueOnce(errorResponse(500, "boom"));
    await expect(fn()).rejects.toBeInstanceOf(ApiError);
  });
});
