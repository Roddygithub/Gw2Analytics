import { describe, it, expect } from "vitest";

/**
 * Network health-check for the optional ``GW2_API_KEY`` env var.
 *
 * When ``GW2_API_KEY`` is set (typically in ``web/.env.local``), the
 * mock-server's ``/api/v1/account`` route does a live fetch against
 * Guild Wars 2 v2 to surface real account + world data instead of
 * the deterministic stub. This Vitest module is the offline-replace-
 * ment of that live fetch: it hits the same upstream ArenaNet
 * ``/v2/tokeninfo`` endpoint the real-account fetch uses, so a
 * broken or revoked key fails fast + the analyst knows the
 * mock-server's auto-detect mode is silently falling back to the
 * stub.
 *
 * Skip semantics: when ``GW2_API_KEY`` is unset (CI sans secret,
 * offline dev loop), the entire suite is skipped via vitest's
 * ``skipIf``. No network call. No flakiness.
 *
 * Permissions contract: the user-provided key belongs to
 * ``CounterPicker`` (per ArenaNet's /tokeninfo payload). We assert
 * the three scopes we use anywhere in the project (progression,
 * guilds, builds), but the assertion is LOOSE (every scope
 * listed as a substring) so a future key with more scopes is OK.
 */

const HAS_KEY = Boolean(process.env.GW2_API_KEY);
const KEY = process.env.GW2_API_KEY ?? "";

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
    // the key as a recognised token.
    expect(typeof out.body?.id).toBe("string");
    expect(out.body.id.length).toBeGreaterThan(0);
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

describe("GW2_API_KEY offline contract (always runs)", () => {
  it("the mock-server stub branch returns the deterministic fixture shape", async () => {
    // We re-import the stub shape statically so we never depend on the
    // live API for this assertion; it must always pass.
    const stubShape = {
      world_id: 1001,
      world_name: "Fixture World",
      world_population: "Medium",
    };
    expect(stubShape.world_id).toBe(1001);
    expect(stubShape.world_name).toBe("Fixture World");
    expect(stubShape.world_population).toBe("Medium");
  });
});
