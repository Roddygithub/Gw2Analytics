import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

vi.mock("@/lib/env", () => ({
  API_BASE_URL: "http://gateway:8000",
}));

describe("POST /api/account/resolve route handler", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  async function callRoute(body: unknown) {
    const req = new Request("http://localhost/api/account/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const mod = await import("@/app/api/account/resolve/route");
    return mod.POST(req);
  }

  it("returns 400 when api_key is missing", async () => {
    const res = await callRoute({});
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.detail).toBe("api_key required");
  });

  it("returns 400 when api_key is empty string", async () => {
    const res = await callRoute({ api_key: "" });
    expect(res.status).toBe(400);
  });

  it("forwards Authorization header to upstream gateway", async () => {
    mockFetch.mockResolvedValueOnce({
      status: 200,
      json: async () => ({
        world_id: 1001,
        world_name: "Test World",
        world_population: "High",
      }),
    });

    const res = await callRoute({ api_key: "test-key-123" });
    expect(res.status).toBe(200);

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe("http://gateway:8000/api/v1/account");
    expect(opts.method).toBe("GET");
    expect(opts.headers).toEqual({
      Authorization: "Bearer test-key-123",
    });
  });

  it("preserves upstream status on error", async () => {
    mockFetch.mockResolvedValueOnce({
      status: 401,
      json: async () => ({ detail: "Invalid API key" }),
    });

    const res = await callRoute({ api_key: "bad-key" });
    expect(res.status).toBe(401);
  });

  it("returns upstream body verbatim", async () => {
    const upstreamBody = {
      world_id: 2002,
      world_name: "Fortune",
      world_population: "Medium",
    };
    mockFetch.mockResolvedValueOnce({
      status: 200,
      json: async () => upstreamBody,
    });

    const res = await callRoute({ api_key: "valid" });
    const json = await res.json();
    expect(json).toEqual(upstreamBody);
  });
});
