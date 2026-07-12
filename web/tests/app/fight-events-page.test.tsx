/**
 * Phase 7 v1 + Phase 8 of web: vitest tests for the dynamic
 * ``/fights/[id]`` drill-down page.
 *
 * v0.10.17 D3 deliverable: mock-layer swap from ``@/lib/api``
 * to ``@/lib/fetchCached``. The page.tsx Server Component uses
 * :func:`fetchCached` from ``@/lib/fetchCached`` as the runtime
 * substrate for all 5 gateway fetches (events, squads, skills,
 * timeline, player-timeline). The functions in ``@/lib/api``
 * (fetchFightEvents, fetchFightSquads, etc.) are imported by the
 * page ONLY as TypeScript type constraints -- the runtime calls
 * go through ``fetchCached`` -> ``globalThis.fetch``, bypassing
 * the ``@/lib/api`` module entirely. The pre-D3 vitest setup
 * mocked ``@/lib/api``, which was a structural no-op at runtime
 * and caused all 7 tests to fail with ``<p>fetch failed</p>``
 * (the page rendered the upstream-error card because native
 * ``fetch`` in jsdom rejects for the faked API_BASE_URL).
 *
 * The D3 fix swaps the mock target to ``@/lib/fetchCached`` so
 * the mock intercepts the actual runtime round-trips. The
 * ``mockFightFetch`` helper provides a per-URL dispatch
 * (``{ events, squads, skills, timeline, playerTimeline }``)
 * where each URL can resolve with a fixture OR reject with an
 * error -- this preserves the original test contract (each test
 * can override per-fetcher behavior) while fixing the mock
 * substrate.
 *
 * Why a per-URL dispatch (vs per-test ``vi.mocked(fetchCached).mockResolvedValueOnce``):
 * the page fires 5 fetches via ``Promise.allSettled``; the per-test
 * ``mockResolvedValueOnce(...)`` call would have to fire 5 times
 * in the correct order to satisfy one test invocation. The
 * per-URL dispatch collapses the 5 ``mockResolvedValue*`` calls
 * into a single helper invocation per test + matches the page's
 * ``url.includes(...)`` dispatch table (longest URL substring
 * first, so ``/timeline/players`` matches before ``/timeline``).
 */

import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

// Mock the actual runtime substrate (``fetchCached``), NOT the
// type-only ``@/lib/api`` wrappers. ``importActual`` preserves
// the test-only hooks (`__resetCacheForTests`, `__cacheSizeForTests`)
// from the v0.10.17 D4 close-out so the D3 + D4 test hooks can
// coexist if both D3 and D4 are run together in the same vitest
// worker.
vi.mock("@/lib/fetchCached", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/fetchCached")>();
  return {
    ...actual,
    fetchCached: vi.fn(),
  };
});

import FightEventsPage from "@/app/fights/[id]/page";
import { fetchCached } from "@/lib/fetchCached";
import { ApiError } from "@/lib/api/errors";
import type {
  FightEventsSummaryRow,
  FightSquads,
  FightSkills,
  FightTimeline,
  FightPlayerTimeline,
} from "@/lib/api/fights";

const FIGHT_ID = "abc123def456";

const POPULATED_PAYLOAD: FightEventsSummaryRow = {
  fight_id: FIGHT_ID,
  duration_s: 12.5,
  target_dps: [
    { target_agent_id: 2, total_damage: 1234, dps: 1234 / 12.5, name: "HealTarget" },
  ],
  target_healing: [
    { target_agent_id: 1, total_healing: 567, hps: 567 / 12.5, name: "DPSSource" },
  ],
  target_buff_removal: [
    { target_agent_id: 1, total_buff_removal: 333, bps: 333 / 12.5, name: "DPSSource" },
  ],
  event_windows: [
    { start_ms: 0, end_ms: 5000, damage_total: 800, healing_total: 300, event_count: 4 },
    { start_ms: 5000, end_ms: 10000, damage_total: 400, healing_total: 200, event_count: 3 },
    { start_ms: 10000, end_ms: 15000, damage_total: 34, healing_total: 67, event_count: 2 },
  ],
};

const POPULATED_SQUADS: FightSquads = {
  fight_id: FIGHT_ID,
  duration_s: 12.5,
  squads: [
    {
      subgroup: "",
      total_damage: 1234,
      total_healing: 567,
      total_buff_removal: 333,
      dps: 1234 / 12.5,
      hps: 567 / 12.5,
      bps: 333 / 12.5,
    },
  ],
};

const POPULATED_SKILLS: FightSkills = {
  fight_id: FIGHT_ID,
  skills: [
    { skill_id: 100, skill_name: "Whirlwind", hit_count: 1, total_damage: 1234, total_healing: 0, total_buff_removal: 0 },
    { skill_id: 200, skill_name: "Heal", hit_count: 1, total_damage: 0, total_healing: 567, total_buff_removal: 333 },
  ],
};

const POPULATED_TIMELINE: FightTimeline = {
  fight_id: FIGHT_ID,
  window_s: 5,
  duration_s: 15.0,
  points: [
    { window_start_ms: 0, window_end_ms: 5_000, total_damage: 1_000, total_healing: 200, total_buff_removal: 50 },
    { window_start_ms: 5_000, window_end_ms: 10_000, total_damage: 3_000, total_healing: 100, total_buff_removal: 75 },
    { window_start_ms: 10_000, window_end_ms: 15_000, total_damage: 2_000, total_healing: 300, total_buff_removal: 25 },
  ],
};

// v0.10.17 D3 addition: 5th fetcher fixture (``fetchFightPlayerTimeline``).
// The page.tsx was updated in v0.8.9 (plan/002) to fire this 5th
// fetcher, but the test file's fixture set was never extended to
// mock the player-timeline. The pre-D3 tests passed-by-luck for
// the rendering assertions because the player-timeline default
// fetch resolved accidentally (jsdom native-fetch rejected for all
// URLs) -- the error path was already triggering on events alone.
const POPULATED_PLAYER_TIMELINE: FightPlayerTimeline = {
  fight_id: FIGHT_ID,
  window_s: 5,
  duration_s: 15.0,
  series: [
    {
      account_name: "player.1234",
      name: "DPSSource",
      points: [
        { window_start_ms: 0, window_end_ms: 5_000, total_damage: 800, total_healing: 0, total_buff_removal: 0 },
        { window_start_ms: 5_000, window_end_ms: 10_000, total_damage: 600, total_healing: 0, total_buff_removal: 0 },
      ],
    },
  ],
};

const EMPTY_PAYLOAD: FightEventsSummaryRow = {
  fight_id: FIGHT_ID,
  duration_s: 0,
  target_dps: [],
  target_healing: [],
  target_buff_removal: [],
  event_windows: [],
};

/**
 * Per-URL dispatch helper. Each URL can resolve with a fixture OR
 * reject with an Error. The default for unprovided URLs is the
 * POPULATED_* fixture. String-matching order is longest-substring
 * first so ``/timeline/players`` matches BEFORE ``/timeline``.
 */
function mockFightFetch(
  mocks: {
    events?: FightEventsSummaryRow | Error;
    squads?: FightSquads | Error;
    skills?: FightSkills | Error;
    timeline?: FightTimeline | Error;
    playerTimeline?: FightPlayerTimeline | Error;
  } = {},
): void {
  vi.mocked(fetchCached).mockImplementation(async (url: string) => {
    if (url.includes("/timeline/players")) {
      const m = mocks.playerTimeline ?? POPULATED_PLAYER_TIMELINE;
      if (m instanceof Error) throw m;
      return m;
    }
    if (url.includes("/timeline")) {
      const m = mocks.timeline ?? POPULATED_TIMELINE;
      if (m instanceof Error) throw m;
      return m;
    }
    if (url.includes("/events")) {
      const m = mocks.events ?? POPULATED_PAYLOAD;
      if (m instanceof Error) throw m;
      return m;
    }
    if (url.includes("/squads")) {
      const m = mocks.squads ?? POPULATED_SQUADS;
      if (m instanceof Error) throw m;
      return m;
    }
    if (url.includes("/skills")) {
      const m = mocks.skills ?? POPULATED_SKILLS;
      if (m instanceof Error) throw m;
      return m;
    }
    throw new Error(`Unexpected fetch URL in mockFightFetch: ${url}`);
  });
}

describe("FightEventsPage", () => {
  beforeEach(() => {
    // Default: all 5 fetchers return populated fixtures. Tests
    // that need a different dispatch override via ``mockFightFetch({ ... })``
    // inside the test body (the override REPLACES the default for
    // THAT test invocation, not the beforeEach default).
    mockFightFetch();
  });

  it("renders the header + section headings when fetchCached returns a populated payload", async () => {
    mockFightFetch({ events: POPULATED_PAYLOAD });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({}),
    });
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: `Fight ${FIGHT_ID}` }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Duration: 12.50 s/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target damage" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target healing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target buff removal" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: /Per-subgroup/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-skill" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Event windows" }),
    ).toBeInTheDocument();
  });

  it("renders the upstream-error card when fetchCached throws for /events", async () => {
    mockFightFetch({ events: new ApiError(404, "fight not found") });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({}),
    });
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: `Fight ${FIGHT_ID}` }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Upstream error: 404: 404: fight not found/),
    ).toBeInTheDocument();
  });

  it("renders the header + section headings on empty roll-ups (parser yielded zero events)", async () => {
    mockFightFetch({ events: EMPTY_PAYLOAD });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({}),
    });
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: `Fight ${FIGHT_ID}` }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Duration: 0.00 s/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target damage" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target healing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target buff removal" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: /Per-subgroup/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-skill" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Event windows" }),
    ).toBeInTheDocument();
  });

  it("forwards searchParams.window_s to the gateway URL via fetchCached (window-s selector wiring)", async () => {
    const fetchSpy = vi.mocked(fetchCached);
    mockFightFetch({ events: POPULATED_PAYLOAD });
    await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ window_s: "30" }),
    });
    // The page must encode ``window_s=30`` in the events URL so
    // the gateway returns 30-second buckets. This locks down the
    // URL -> gateway wiring (a refactor that drops the URL param
    // would silently fall back to the default 5s).
    const eventsCall = fetchSpy.mock.calls.find((c) => c[0].includes("/events"));
    expect(eventsCall).toBeDefined();
    expect(eventsCall![0]).toMatch(/window_s=30/);
  });

  it("clamps an out-of-range window_s to the gateway default (no upstream 422)", async () => {
    const fetchSpy = vi.mocked(fetchCached);
    mockFightFetch({ events: POPULATED_PAYLOAD });
    await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ window_s: "9999" }),
    });
    const eventsCall = fetchSpy.mock.calls.find((c) => c[0].includes("/events"));
    expect(eventsCall).toBeDefined();
    expect(eventsCall![0]).not.toMatch(/window_s=9999/);
    // The default window is 5s; the gateway treats window_s=5
    // (or omitted) as the canonical 5s view.
  });

  it("filters the three roll-up tables to a single target when ?target=N is set", async () => {
    const multiPayload: FightEventsSummaryRow = {
      ...POPULATED_PAYLOAD,
      target_dps: [
        { target_agent_id: 1, total_damage: 100, dps: 100 / 12.5, name: "DPSSource" },
        { target_agent_id: 2, total_damage: 1234, dps: 1234 / 12.5, name: "HealTarget" },
      ],
      target_healing: [
        { target_agent_id: 1, total_healing: 567, hps: 567 / 12.5, name: "DPSSource" },
      ],
      target_buff_removal: [
        { target_agent_id: 1, total_buff_removal: 333, bps: 333 / 12.5, name: "DPSSource" },
        { target_agent_id: 2, total_buff_removal: 99, bps: 99 / 12.5, name: "HealTarget" },
      ],
    };
    mockFightFetch({ events: multiPayload });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ target: "1" }),
    });
    render(tree);
    expect(screen.getByText(/filtered to target 1/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target damage" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target healing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target buff removal" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: /Per-subgroup/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-skill" }),
    ).toBeInTheDocument();
  });

  it("falls back to the unfiltered view when ?target= is malformed", async () => {
    mockFightFetch({ events: POPULATED_PAYLOAD });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ target: "not-a-number" }),
    });
    render(tree);
    expect(screen.queryByText(/filtered to target/)).not.toBeInTheDocument();
    expect(screen.getByText(/Duration: 12.50 s/)).toBeInTheDocument();
  });
});
