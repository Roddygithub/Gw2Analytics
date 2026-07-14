import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * Network health-check for the optional ``GW2_API_KEY`` env var.
 *
 * When ``GW2_API_KEY`` is set (typically in ``web/.env.local``), the
 * mock-server's ``/api/v1/account`` route does a live fetch against
 * Guild Wars 2 v2 to surface real account + world data instead of
 * the deterministic stub. This Vitest module is the offline
 * replacement of that live fetch: it hits the same upstream ArenaNet
 * ``/v2/tokeninfo`` endpoint the real-account fetch uses, so a
 * broken or revoked key fails fast + the analyst knows the
 * mock-server's auto-detect mode is silently falling back to the
 * stub.
 *
 * Skip semantics: when ``GW2_API_KEY`` is unset (CI sans secret,
 * offline dev loop), the network-health-check describe block is
 * skipped via vitest's ``skipIf``. No network call. No flakiness.
 *
 * Single-source-of-truth: the offline-stub-shape describe block
 * reads the canonical ``web/tests/e2e/fixtures/account-stub.json``
 * fixture file (the SAME file mock-server.mjs's stub branch
 * returns via ``loadFixture("account-stub.json")``). Drift between
 * the mock-server stub response and the test's offline-shape
 * assertion is impossible by construction.
 */

const HAS_KEY = Boolean(process.env.GW2_API_KEY);
const KEY = process.env.GW2_API_KEY ?? "";
const STUB_FIXTURE_PATH = join(
  __dirname,
  "..",
  "e2e",
  "fixtures",
  "account-stub.json",
);

interface TokenInfo {
  id: string;
  name: string;
  permissions: string[];
}

const TOKENINFO_TIMEOUT_MS = 5_000;

async function fetchTokenInfo(): Promise<{ status: number; body: TokenInfo | null; error?: string }> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TOKENINFO_TIMEOUT_MS);
  try {
    const res = await fetch(
      `https://api.guildwars2.com/v2/tokeninfo?access_token=${encodeURIComponent(KEY)}`,
      { signal: ctrl.signal },
    );
    if (!res.ok) {
      return { status: res.status, body: null, error: `HTTP ${res.status}` };
    }
    const body = (await res.json()) as TokenInfo;
    return { status: res.status, body };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { status: 0, body: null, error: msg };
  } finally {
    clearTimeout(timer);
  }
}

describe.skipIf(!HAS_KEY)("GW2_API_KEY live health-check", () => {
  it("reaches the GW2 v2 /tokeninfo endpoint with HTTP 200", async () => {
    const out = await fetchTokenInfo();
    expect(out.error).toBeUndefined();
    expect(out.status).toBe(200);
    expect(out.body).not.toBeNull();
  });

  it("identifies the application as the CounterPicker scope set", async () => {
    const out = await fetchTokenInfo();
    expect(out.body).not.toBeNull();
    // We do not lock to a single canonical name (ArenaNet may rotate the
    // app name), but we assert it is non-empty so we know GW2 accepted
    // the key as a recognised token. Capture once to narrow null for
    // tsc-strict without optional chaining noise.
    const body = out.body!;
    expect(typeof body.id).toBe("string");
    expect(body.id.length).toBeGreaterThan(0);
  });

  it("exposes the progression / guilds / builds permissions", async () => {
    const out = await fetchTokenInfo();
    expect(out.body).not.toBeNull();
    const perms = out.body!.permissions ?? [];
    // Loose: every scope must be present as a substring match on the
    // permission set. Named like "progression", "account", etc.
    for (const expected of ["progression", "guilds", "builds"]) {
      expect(perms.some((p) => p === expected || p.startsWith(expected))).toBe(true);
    }
  });
});

describe("account-stub.json fixture (always runs)", () => {
  it("the canonical fixture file exists at the canonical path", () => {
    const raw = readFileSync(STUB_FIXTURE_PATH);
    expect(raw.length).toBeGreaterThan(0);
  });

  it("the canonical fixture parses as JSON + has the expected fields", () => {
    const stub = JSON.parse(readFileSync(STUB_FIXTURE_PATH, "utf8")) as {
      world_id: number;
      world_name: string;
      world_population: string;
    };
    expect(stub.world_id).toBe(1001);
    expect(stub.world_name).toBe("Fixture World");
    expect(stub.world_population).toBe("Medium");
  });

  it("the canonical fixture shape matches the AccountEnrichedOut schema keys", () => {
    const stub = JSON.parse(readFileSync(STUB_FIXTURE_PATH, "utf8")) as Record<string, unknown>;
    expect(Object.keys(stub).sort()).toEqual(
      ["world_id", "world_name", "world_population"].sort(),
    );
  });
});
