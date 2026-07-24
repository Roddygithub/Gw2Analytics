import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createWebhook,
  DEFAULT_WEBHOOK_FILTER,
  fetchWebhookSubscriptions,
  revokeWebhook,
} from "@/lib/api/webhooks";
import { API_BASE_URL } from "@/lib/env";

/**
 * Network-boundary tests for the webhook API client.
 *
 * The React form test (tests/components/CreateWebhookPanel.test.tsx)
 * covers the call-site path: it spies on the createWebhook export and
 * asserts that the React form invokes ``createWebhook`` with the right
 * payload after the user submits. That's a layer-1 boundary (the
 * component ⇄ api client).
 *
 * This spec covers the layer-2 boundary: the api client ⇄ HTTP wire.
 * If a future refactor accidentally drops the ``DEFAULT_WEBHOOK_FILTER``
 * default-out inside createWebhook, the form-layer test will still
 * pass (it only inspects the spy argument). Only THIS spec, by reading
 * the parsed JSON body of the actual fetch call, will catch the
 * regression. The cost is one ``vi.stubGlobal("fetch", ...)`` per
 * test case (~2 ms) and the ``vi.unstubAllGlobals`` cleanup in
 * ``afterEach`` so the cache between tests stays hermetic.
 */

describe("createWebhook network boundary", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("defaults filter to {kind: upload_completed} when the caller omits filter", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 201,
      text: () => Promise.resolve("{}"),
      json: () =>
        Promise.resolve({
          id: "whsub_test",
          url: "https://example.com/wh",
          description: null,
          filter: DEFAULT_WEBHOOK_FILTER,
          created_at: "2026-07-24T00:00:00+00:00",
          secret: "whsec_DEMO",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createWebhook({ url: "https://example.com/wh" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, calledInit] = fetchMock.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(calledUrl).toBe(`${API_BASE_URL}/api/v1/webhooks`);
    expect(calledInit.method).toBe("POST");
    const sentBody = JSON.parse(String(calledInit.body));
    expect(sentBody).toEqual({
      url: "https://example.com/wh",
      description: null,
      filter: { kind: "upload_completed" },
    });
  });

  it("defaults filter to {kind: upload_completed} when the caller passes an empty object", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 201,
      text: () => Promise.resolve("{}"),
      json: () => Promise.resolve({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createWebhook({
      url: "https://example.com/wh",
      filter: {},
    });

    const sentBody = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(sentBody.filter).toEqual({ kind: "upload_completed" });
  });

  it("honours a caller-supplied non-empty filter (no default over-write)", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 201,
      text: () => Promise.resolve("{}"),
      json: () => Promise.resolve({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createWebhook({
      url: "https://example.com/wh",
      filter: { kind: "upload_completed", extra: "tag" },
    });

    const sentBody = JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(sentBody.filter).toEqual({
      kind: "upload_completed",
      extra: "tag",
    });
  });

  it("propagates the upstream 422 + non-2xx body via ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 422,
        text: () =>
          Promise.resolve(
            '{"detail":[{"type":"value_error","loc":["body","filter"],"msg":"filter.kind is required"}]}',
          ),
      }),
    );

    await expect(
      createWebhook({ url: "https://example.com/wh", filter: {} }),
    ).rejects.toMatchObject({
      status: 422,
    });
  });
});

describe("fetchWebhookSubscriptions network boundary", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("forwards limit + offset as query string params", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.resolve("[]"),
      json: () => Promise.resolve([]),
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchWebhookSubscriptions({ limit: 5, offset: 10 });

    const [calledUrl] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe(
      `${API_BASE_URL}/api/v1/webhooks?limit=5&offset=10`,
    );
  });
});

describe("revokeWebhook network boundary", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends a DELETE to /api/v1/webhooks/{id}", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 204,
      text: () => Promise.resolve(""),
      json: () => Promise.reject(new Error("no body")),
    });
    vi.stubGlobal("fetch", fetchMock);

    await revokeWebhook("whsub_xyz789");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [calledUrl, calledInit] = fetchMock.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(calledUrl).toBe(
      `${API_BASE_URL}/api/v1/webhooks/whsub_xyz789`,
    );
    expect(calledInit.method).toBe("DELETE");
  });
});
