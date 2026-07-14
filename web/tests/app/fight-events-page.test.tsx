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
import {
  FAILED_TO_LOAD_PLAYER_LIST,
  FAILED_TO_LOAD_PER_PLAYER_SKILLS,
} from "@/lib/copy/error-messages";
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

// Tour 4 plan 044: the bare ``/fights/:id`` fetch-side enum
// grammar (a regex, NOT an exact match). Anchored at the
// canonical ``API_BASE_URL`` (``http://test/api`` per the
// ``setup.ts`` mock) so a future test that uses ANY fight-id
// or that adds a query-param to the URL still matches. The
// trailing ``(?:[?#]|$)`` group accepts an end-of-string OR a
// query-string start (``?``) OR a fragment start (``#``) so
// any future query-param additions don't silently drop into
// the ``throw new Error(...)`` catch-all.
const BARE_FIGHT_URL_REGEX = new RegExp(
  `^http://test/api/api/v1/fights/${FIGHT_ID}(?:[?#]|$)`,
);

// Tour 4 plan 044 fixture: populated ``FightOut`` with the
// 2-agent stub the page's ``PlayerSkillUsageFilter``
// dropdown pre-filters on. Mirrors the canonical wire shape
// so a regression in the field contract surfaces here as a
// TS compile error too.
const POPULATED_FIGHT_DETAILS: import("@/lib/api/fights").FightOut = {
  id: FIGHT_ID,
  build_version: "20250714-123456",
  encounter_id: 1,
  agent_count: 2,
  started_at: "2026-07-14T12:00:00Z",
  game_type: 4,
  agents: [
    {
      agent_id: 1234,
      name: "Fighty McFight",
      profession: "Warrior",
      elite_spec: "Berserker",
      is_player: true,
      account_name: "TestAccount.1234",
      subgroup: "1",
    },
    {
      agent_id: 5678,
      name: "Heal Bot",
      profession: "Guardian",
      elite_spec: "Firebrand",
      is_player: true,
      account_name: "TestAccount.5678",
      subgroup: "2",
    },
  ],
  skills: [],
};

// Tour 4 plan 044 fixture: populated per-player skill row
// (Whirlwind 3000dmg) for ``TestAccount.1234``. Matches the
// backend V1-stub ``PlayerSkillsOut`` shape so a regression
// in ``skill_id`` / ``skill_name`` / totals contract surfaces
// here as a TS compile error too.
const POPULATED_PLAYER_SKILLS: import("@/lib/api/fights").PlayerSkills = {
  fight_id: FIGHT_ID,
  account_name: "TestAccount.1234",
  agent_id: 1234,
  loadout: {
    profession: "Warrior",
    elite_spec: "Berserker",
    equipped_skill_ids: [],
  },
  skills: [
    {
      skill_id: 100,
      skill_name: "Whirlwind",
      hit_count: 2,
      total_damage: 3000,
      total_healing: 0,
      total_buff_removal: 0,
    },
  ],
};

/**
 * Per-URL dispatch helper. Each URL can resolve with a fixture OR
 * reject with an Error. The default for unprovided URLs is the
 * POPULATED_* fixture. String-matching order is longest-substring
 * first so ``/timeline/players`` matches BEFORE ``/timeline`` AND
 * ``/players/:account/skills`` matches BEFORE the bare fight-id
 * catch-all.
 */
function mockFightFetch(
  mocks: {
    events?: FightEventsSummaryRow | Error;
    squads?: FightSquads | Error;
    skills?: FightSkills | Error;
    timeline?: FightTimeline | Error;
    playerTimeline?: FightPlayerTimeline | Error;
    fightDetails?: import("@/lib/api/fights").FightOut | Error;
    playerSkills?: import("@/lib/api/fights").PlayerSkills | Error;
  } = {},
): void {
  vi.mocked(fetchCached).mockImplementation(async (url: string) => {
    // Tour 4 plan 044: the per-player fetch URL is the most
    // specific (it has 2 path segments after ``/fights/`` AND the
    // path-after-``/players/`` includes ``/skills``). Check
    // FIRST so the bare ``/fights/:id`` (which is also a fetch)
    // matches the fightDetails slot instead of the playerSkills
    // slot -- a bare ``url.includes("/players/")`` substring
    // check would otherwise be ambiguous between the two.
    const playerSkillsPathMatch = url.match(
      /\/api\/v1\/fights\/[^/]+\/players\/[^/]+\/skills/,
    );
    if (playerSkillsPathMatch !== null) {
      const m = mocks.playerSkills ?? POPULATED_PLAYER_SKILLS;
      if (m instanceof Error) throw m;
      return m;
    }
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
    // Tour 4 bare ``/fights/:id`` catch-all: must be checked
    // LAST so it doesn't shadow any of the more-specific
    // sub-path handlers above. The page.tsx fires this fetch
    // via ``fetchCached<import("@/lib/api").FightOut>(base)``
    // for the player dropdown options. The regex (NOT an exact
    // match) accepts any trailing query-string or fragment so
    // a future test or refactor that adds params doesn't
    // silently fall through to the ``throw`` catch-all.
    if (BARE_FIGHT_URL_REGEX.test(url)) {
      const m = mocks.fightDetails ?? POPULATED_FIGHT_DETAILS;
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

  // -------------------------------------------------------------------------
  // Tour 4 v0.10.13 plan 044 page-level coverage: the per-player
  // section on ``/fights/[id]`` with the ``?account=`` URL filter.
  // -------------------------------------------------------------------------

  it("renders the per-player section heading + the prompt placeholder on first load (no ?account= URL filter)", async () => {
    // First-load state: no ``?account=`` URL filter. The page
    // shows the per-player section heading + the
    // ``PlayerSkillUsageFilter`` dropdown + the "Pick a player"
    // prompt placeholder. The dedicated component-level vitest
    // tests (in :file:`web/tests/components/player-skill-usage-filter.test.tsx`)
    // cover the dropdown's interaction contract; this page-level
    // assertion pins the WRAPPING chrome.
    mockFightFetch({ events: POPULATED_PAYLOAD });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({}),
    });
    render(tree);
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: /Per-player \(SkillUsage attribution\)/,
      }),
    ).toBeInTheDocument();
    // The "Pick a player" prompt placeholder carries the
    // canonical ``player-skill-prompt`` testid so the
    // screenshot-script can locate it without a label query.
    expect(screen.getByTestId("player-skill-prompt")).toBeInTheDocument();
    expect(screen.getByText(/Pick a player/i)).toBeInTheDocument();
  });

  it("renders the section-level error chip when ?account= points at an account NOT in the fight's agents", async () => {
    // Lenient contract: an analyst mistyping ``?account=`` to a
    // value that's not in the fight's agent list surfaces a
    // section-level diagnostic chimp (``player-skill-error``)
    // rather than the page-level 404 card. The page.tsx agent
    // lookup filters for ``is_player === true && account_name
    // === accountFilter``; an unmatched account raises the
    // canonical "Player ... not found in this fight" string
    // (NOT a 404 -- the 404 contract is the gateway's, NOT the
    // page's).
    mockFightFetch({ events: POPULATED_PAYLOAD });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ account: "UnknownAccount.9999" }),
    });
    render(tree);
    // The per-player section still renders (the prompt
    // placeholder is NOT shown when ``accountFilter !== null``
    // AND ``accountSkills === null``).
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: /Per-player \(SkillUsage attribution\)/,
      }),
    ).toBeInTheDocument();
    // The section-level error chip carries the
    // ``player-skill-error`` testid.
    expect(screen.getByTestId("player-skill-error")).toBeInTheDocument();
    expect(screen.getByText(/not found in this fight/i)).toBeInTheDocument();
    // The prompt placeholder is NOT shown when an account is set
    // (the per-player-section body has only 3 valid states:
    // prompt / error / table; the prompt is suppressed when the
    // URL points at an account).
    expect(
      screen.queryByTestId("player-skill-prompt"),
    ).not.toBeInTheDocument();
  });

  it("renders the upstream error chip when the per-player fetch throws (accountSkillsError !== null from the page's fetch catch)", async () => {
    // The page.tsx cascades an upstream error from the per-player
    // fetch into the section's ``accountSkillsError`` field.
    // The page renders the ``player-skill-error`` chimp with
    // the upstream error message. This test pins the
    // error-propagation contract independently from the
    // agent-not-found path (a different error class -- gateway
    // throws 502 vs page-level agent-mismatch).
    mockFightFetch({
      events: POPULATED_PAYLOAD,
      playerSkills: new ApiError(502, "events blob corrupt"),
    });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ account: "TestAccount.1234" }),
    });
    render(tree);
    expect(screen.getByTestId("player-skill-error")).toBeInTheDocument();
    expect(screen.getByText(/events blob corrupt/i)).toBeInTheDocument();
  });

  it("renders the agents-fetch error chip when the bare /fights/:id fetch fails (cascades to per-player section)", async () => {
    // The page.tsx cascades the agents-fetch error to the per-
    // player section's ``accountSkillsError`` field as well --
    // "Failed to load player list: ..." -- so the analyst sees
    // the root cause rather than a misleading "not found in
    // this fight".
    mockFightFetch({
      events: POPULATED_PAYLOAD,
      fightDetails: new ApiError(502, "fight unavailable"),
    });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ account: "TestAccount.1234" }),
    });
    render(tree);
    // The agents-fetch-specific chip carries the
    // ``player-skill-agents-error`` testid; the per-player
    // section chip carries ``player-skill-error`` (the latter
    // is the user-facing one because it explains the per-player
    // section's failure mode). We scope the text-content
    // assertion to the agents-error chip (NOT a document-wide
    // ``getByText``) because the same upstream error string
    // cascades to the per-player chip too -- a document-wide
    // query would throw ``getMultipleElementsFoundError``.
    expect(
      screen.getByTestId("player-skill-agents-error"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("player-skill-agents-error"),
    ).toHaveTextContent(/fight unavailable/i);
  });

  // -------------------------------------------------------------------------
  // v0.10.18 regression-locking test: the dual-banner cascade
  // contract. When the bare ``/fights/:id`` (agents-list) fetch
  // throws 502, the page.tsx cascades the upstream error into
  // BOTH chips: ``player-skill-agents-error`` (the agents-
  // dropdown diagnostic) AND ``player-skill-error`` (the
  // per-player-section diagnostic). The same substring "fight
  // unavailable" appears in 2 places. The pre-fix test used
  // ``screen.getByText(/fight unavailable/i)`` which threw
  // ``getMultipleElementsFoundError`` -- the fix scopes
  // assertions to the specific testid. This regression test
  // pins:
  //   1. BOTH chips are present
  //   2. BOTH chips carry the upstream error substring
  //   3. the per-player chip carries the canonical
  //      "Failed to load per-player skills:" prefix that
  //      distinguishes it from the agents-dropdown chip
  //   4. exactly 2 elements match the cascade substring
  //      (forbids a 3rd duplicate chip -- the original bug
  //      class)
  //   5. the prompt placeholder is hidden when accountFilter
  //      is set (preserves the 3-state body contract)
  // -------------------------------------------------------------------------
  it("locks the dual-banner cascade contract on agents-fetch 502 (regression)", async () => {
    mockFightFetch({
      events: POPULATED_PAYLOAD,
      fightDetails: new ApiError(502, "fight unavailable"),
    });
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ account: "TestAccount.1234" }),
    });
    render(tree);
    // BOTH chips are present.
    expect(
      screen.getByTestId("player-skill-agents-error"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("player-skill-error")).toBeInTheDocument();
    // BOTH chips cascade the upstream error substring. Testid-
    // scoped (NOT `screen.getByText` which would throw
    // MultipleElementsFoundError on the 2-match case).
    expect(
      screen.getByTestId("player-skill-agents-error"),
    ).toHaveTextContent(/fight unavailable/i);
    expect(
      screen.getByTestId("player-skill-error"),
    ).toHaveTextContent(/fight unavailable/i);
    // The per-player chip carries the canonical user-facing
    // prefix (FAILED_TO_LOAD_PER_PLAYER_SKILLS) that
    // distinguishes it from the agents-dropdown chip
    // (FAILED_TO_LOAD_PLAYER_LIST). Locks down the
    // cascade-wrapping semantics so a future refactor can't
    // accidentally strip the prefix and surface the raw
    // upstream error (which would be confusing -- the analyst
    // can't tell which fetch failed). The assertions below
    // pass the constant directly to toHaveTextContent --
    // jest-dom matches by substring for a string argument,
    // so the @/lib/copy/error-messages module remains the
    // sole English-coupling point (a future i18n refactor
    // edits only that module).
    expect(
      screen.getByTestId("player-skill-error"),
    ).toHaveTextContent(FAILED_TO_LOAD_PER_PLAYER_SKILLS);
    expect(
      screen.getByTestId("player-skill-agents-error"),
    ).toHaveTextContent(FAILED_TO_LOAD_PLAYER_LIST);
    // Exactly 2 elements match the cascade substring -- forbids
    // a 3rd duplicate chip. RTL counts matches by element (1
    // match per `<p>` containing the substring), so 2 chips
    // yields 2 matches. A future refactor that adds a 3rd
    // warning banner reusing the upstream text would explode
    // this assertion -- which is the original bug class
    // (cascading error string missing the per-section scoping).
    expect(screen.getAllByText(/fight unavailable/i)).toHaveLength(2);
    // Prompt placeholder hidden when accountFilter is set
    // (preserves the canonical 3-state body contract: prompt /
    // error / table, with the prompt suppressed on the URL-
    // filtered path).
    expect(
      screen.queryByTestId("player-skill-prompt"),
    ).not.toBeInTheDocument();
  });
});
