/**
 * v0.7.1 of web: page-level vitest cases for the
 * ``/players/[account_name]`` cross-fight profile page.
 * Mirrors the existing
 * :file:`web/tests/app/fight-events-page.test.tsx` pattern --
 * the Server Component is invoked as a plain async function
 * with a stubbed ``params`` Promise.
 *
 * Why CI smoke only (not a full rendering test)
 * ============================================
 * The page's only job is to (a) call :func:`fetchPlayer` and
 * (b) render the cross-fight stat cards + the per-fight
 * breakdown table. A full rendering test would require the
 * next/router runtime; the page-level smoke locks the
 * render contract (heading + stat cards + breakdown table)
 * via JSON-string matching.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, type PlayerProfile } from "@/lib/api";

/**
 * ``vi.hoisted`` ensures the mock factory runs AFTER the
 * variable is defined. Without it, vitest hoists the
 * ``vi.mock("@/lib/api", ...)`` call to the top of the file
 * (before any ``const`` declarations) and the factory's
 * reference to ``fetchPlayerMock`` throws
 * "Cannot access 'fetchPlayerMock' before initialization".
 *
 * v0.8.0 of web: the page now also calls ``fetchPlayerTimeline``
 * (to seed the historical-timeline section on the server).
 * We mock that too so the page tests can exercise the
 * page's own render contract without the timeline mock
 * hitting the real gateway.
 */
const { fetchPlayerMock, fetchPlayerTimelineMock } = vi.hoisted(() => ({
  fetchPlayerMock: vi.fn<(accountName: string) => Promise<PlayerProfile>>(),
  fetchPlayerTimelineMock: vi.fn<
    (
      accountName: string,
      opts: { limit?: number; offset?: number },
    ) => Promise<unknown>
  >(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchPlayer: fetchPlayerMock,
    fetchPlayerTimeline: fetchPlayerTimelineMock,
  };
});

import PlayerProfilePage from "@/app/players/[account_name]/page";

const EMPTY_TIMELINE = {
  account_name: ":synth.aaa",
  total: 0,
  limit: 20,
  offset: 0,
  points: [],
};

const POPULATED: PlayerProfile = {
  account_name: ":synth.aaa",
  name: "Warrior One",
  profession: "PROF(2)",
  elite_spec: "ELITE(18)",
  fights_attended: 2,
  total_damage: 7_890,
  total_healing: 0,
  total_buff_removal: 300,
  attended_fight_ids: ["fight-a", "fight-b"],
  per_fight_breakdown: [
    {
      fight_id: "fight-a",
      started_at: "2025-01-01T12:00:00Z",
      total_damage: 1_234,
      total_healing: 0,
      total_buff_removal: 100,
    },
    {
      fight_id: "fight-b",
      started_at: "2025-01-02T12:00:00Z",
      total_damage: 6_656,
      total_healing: 0,
      total_buff_removal: 200,
    },
  ],
};

describe("/players/[account_name] page", () => {
  beforeEach(() => {
    fetchPlayerMock.mockReset();
    fetchPlayerTimelineMock.mockReset();
  });

  it("renders the populated profile (stat cards + breakdown rows)", async () => {
    fetchPlayerMock.mockResolvedValueOnce(POPULATED);
    fetchPlayerTimelineMock.mockResolvedValueOnce(EMPTY_TIMELINE);
    const tree = await PlayerProfilePage({
      params: Promise.resolve({ account_name: ":synth.aaa" }),
    });
    const html = JSON.stringify(tree);
    expect(html).toContain("Warrior One");
    expect(html).toContain(":synth.aaa");
    expect(html).toContain("PROF(2)");
    expect(html).toContain("ELITE(18)");
    expect(html).toContain("Per-fight breakdown");
    expect(html).toContain("fight-a");
    expect(html).toContain("fight-b");
    expect(html).toContain("Fights attended");
  });

  it("renders the empty breakdown panel when per_fight_breakdown is empty", async () => {
    fetchPlayerMock.mockResolvedValueOnce({
      ...POPULATED,
      per_fight_breakdown: [],
      attended_fight_ids: [],
      fights_attended: 0,
    });
    fetchPlayerTimelineMock.mockResolvedValueOnce(EMPTY_TIMELINE);
    const tree = await PlayerProfilePage({
      params: Promise.resolve({ account_name: ":synth.aaa" }),
    });
    const html = JSON.stringify(tree);
    expect(html).toContain("No attended fights");
  });

  it("renders the upstream-error card on a 404 from the gateway", async () => {
    fetchPlayerMock.mockRejectedValueOnce(new ApiError(404, "player not found"));
    const tree = await PlayerProfilePage({
      params: Promise.resolve({ account_name: ":synth.unknown" }),
    });
    const html = JSON.stringify(tree);
    expect(html).toContain("Upstream error: 404: 404: player not found");
  });

  it("renders the upstream-error card on a 502 from the gateway", async () => {
    fetchPlayerMock.mockRejectedValueOnce(new ApiError(502, "upstream gateway"));
    const tree = await PlayerProfilePage({
      params: Promise.resolve({ account_name: ":synth.aaa" }),
    });
    const html = JSON.stringify(tree);
    expect(html).toContain("Upstream error: 502: 502: upstream gateway");
  });
});
