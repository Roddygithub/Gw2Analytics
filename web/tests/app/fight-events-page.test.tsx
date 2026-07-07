/**
 * Phase 7 v1 + Phase 8 of web: vitest tests for the dynamic
 * ``/fights/[id]`` drill-down page.
 *
 * Mirrors the CI-smoke pattern from
 * :file:`web/tests/app/fights-page.test.tsx` -- the Server
 * Component is invoked as a plain async function, not inside
 * Next.js's RSC runtime. This trades full SSR coverage for
 * test-runtime independence (no jsdom-rendered React-tree on the
 * headers() / cookies() / streaming path), which is the
 * canonical choice for a page whose data source is a single
 * ``fetchFightEvents`` call.
 *
 * What is exercised
 * =================
 * - **Happy path**: ``fetchFightEvents`` returns a populated
 *   ``FightEventsSummaryRow`` (1 target_dps row + 1 target_healing
 *   row + 1 target_buff_removal row + 3 event_windows). The page
 *   renders the header (fight_id + duration_s), all FOUR section
 *   headings (Phase 8 added the buff-removal sibling), and the
 *   canonical duration formatting.
 * - **Upstream 404**: ``fetchFightEvents`` rejects with
 *   :class:`ApiError`. The page renders the upstream-error card
 *   with the error body.
 * - **Empty roll-ups**: ``fetchFightEvents`` returns a payload
 *   with empty target_dps + target_healing + target_buff_removal +
 *   event_windows. The page still renders the header + the four
 *   section headings (the per-component empty-state message is
 *   asserted at the component level, not here).
 * - **Window-s selector wiring**: ``searchParams.window_s`` is
 *   forwarded to ``fetchFightEvents`` (Phase 7 v2).
 * - **Window-s clamp**: out-of-range ``window_s`` is clamped to
 *   the gateway default (5s) instead of forwarding a bogus value
 *   upstream.
 * - **Per-target filter wiring**: ``searchParams.target`` is
 *   parsed and the page renders the "filtered to target" sub-label
 *   (Phase 8 v2 of web).
 * - **Per-target filter fallback**: an unparseable target
 *   (``not-a-number``) falls back to the unfiltered view (no
 *   "filtered to target" sub-label).
 *
 * What is NOT exercised
 * =====================
 * - The :class:`TargetRollupsGrid` + :class:`EventWindowsTable`
 *   internals (their renders are stubbed out by
 *   :file:`web/tests/setup.ts` global mocks). Component-level
 *   tests would need to either boot the real AG Grid in jsdom
 *   (slow + fragile) or hand-roll a much larger mock surface
 *   (defeats the point of the test).
 * - The Gateway behaviour (response codes, gzip decompression,
 *   aggregator wiring) -- those live in the apps/api e2e test
 *   (:file:`apps/api/tests/test_uploads_e2e.py`).
 */

import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

// Partial-mock the @/lib/api module: keep the real ``ApiError`` class
// (the test uses it to construct the upstream-error fixture) while
// replacing ``fetchFightEvents`` + ``fetchFightSquads`` +
// ``fetchFightSkills`` with vi.fn() so each test can stub its
// return value. ``importOriginal`` is the canonical vitest
// pattern for "mock one named export, leave the rest alone"; the
// alternative -- re-declaring the ApiError class inline in the mock
// factory -- drifts from the production shape the moment the
// constructor signature changes.
//
// v0.7.1 of web: the page now fires 3 parallel fetchers via
// ``Promise.allSettled``; if any of the 3 is unmocked the test
// would try to make a real HTTP call and time out at the 5s
// vitest default. The 2 new fetchers need the same vi.fn()
// treatment as the original.
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchFightEvents: vi.fn(),
    fetchFightSquads: vi.fn(),
    fetchFightSkills: vi.fn(),
  };
});

import FightEventsPage from "@/app/fights/[id]/page";
import {
  fetchFightEvents,
  fetchFightSquads,
  fetchFightSkills,
  ApiError,
} from "@/lib/api";

const FIGHT_ID = "abc123def456";

const POPULATED_PAYLOAD = {
  fight_id: FIGHT_ID,
  duration_s: 12.5,
  target_dps: [
    // v0.8.3: the optional ``name`` field mirrors the gateway's
    // player-name denormalisation. A real string for resolved
    // players, ``null`` for NPCs / unresolved.
    { target_agent_id: 2, total_damage: 1234, dps: 1234 / 12.5, name: "HealTarget" },
  ],
  target_healing: [
    { target_agent_id: 1, total_healing: 567, hps: 567 / 12.5, name: "DPSSource" },
  ],
  // Phase 8: third sibling roll-up, mirroring the populated DPS +
  // healing rows on the same target (agent 1) so the per-target
  // filter can be exercised against all three roll-ups at once.
  target_buff_removal: [
    { target_agent_id: 1, total_buff_removal: 333, bps: 333 / 12.5, name: "DPSSource" },
  ],
  event_windows: [
    { start_ms: 0, end_ms: 5000, damage_total: 800, healing_total: 300, event_count: 4 },
    { start_ms: 5000, end_ms: 10000, damage_total: 400, healing_total: 200, event_count: 3 },
    { start_ms: 10000, end_ms: 15000, damage_total: 34, healing_total: 67, event_count: 2 },
  ],
};

// v0.7.1 of web: parallel squad + skill roll-up payloads
// returned by the (now-mocked) ``fetchFightSquads`` + ``fetchFightSkills``
// fetchers. Each test must call the .mockResolvedValue on the
// corresponding vi.fn() or the page will see ``undefined`` and
// render the "No squad roll-up rows" / "No skill roll-up rows"
// empty-state panels.
const POPULATED_SQUADS = {
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
const POPULATED_SKILLS = {
  fight_id: FIGHT_ID,
  skills: [
    { skill_id: 100, skill_name: "Whirlwind", hit_count: 1, total_damage: 1234, total_healing: 0, total_buff_removal: 0 },
    { skill_id: 200, skill_name: "Heal", hit_count: 1, total_damage: 0, total_healing: 567, total_buff_removal: 333 },
  ],
};

const EMPTY_PAYLOAD = {
  fight_id: FIGHT_ID,
  duration_s: 0,
  target_dps: [],
  target_healing: [],
  target_buff_removal: [],
  event_windows: [],
};

describe("FightEventsPage", () => {
  beforeEach(() => {
    vi.mocked(fetchFightSquads).mockResolvedValue(POPULATED_SQUADS);
    vi.mocked(fetchFightSkills).mockResolvedValue(POPULATED_SKILLS);
  });

  it("renders the header + section headings when fetchFightEvents returns a populated payload", async () => {
    vi.mocked(fetchFightEvents).mockResolvedValue(POPULATED_PAYLOAD);
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
    // v0.7.1 of web: two new sibling sections (per-subgroup +
    // per-skill) added below the per-target trio. The mocked
    // component stubs render nothing, so we lock the section
    // heading presence here and the component-level renders
    // are covered by the SquadRollupsGrid / SkillUsageTable
    // component tests (to be added in a follow-up if the AG
    // Grid runtime can be booted in jsdom).
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

  it("renders the upstream-error card when fetchFightEvents throws", async () => {
    vi.mocked(fetchFightEvents).mockRejectedValue(
      new ApiError(404, "fight not found"),
    );
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({}),
    });
    render(tree);
    // Header still renders (analyst can see WHICH fight id failed),
    // but the body is the canonical upstream-error card.
    expect(
      screen.getByRole("heading", { level: 1, name: `Fight ${FIGHT_ID}` }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Upstream error: 404: 404: fight not found/),
    ).toBeInTheDocument();
  });

  it("renders the header + section headings on empty roll-ups (parser yielded zero events)", async () => {
    vi.mocked(fetchFightEvents).mockResolvedValue(EMPTY_PAYLOAD);
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({}),
    });
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: `Fight ${FIGHT_ID}` }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Duration: 0.00 s/)).toBeInTheDocument();
    // The six section headings always render -- the per-component
    // empty-state message lives inside the stubbed child components.
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

  it("forwards searchParams.window_s to fetchFightEvents (window-s selector wiring)", async () => {
    vi.mocked(fetchFightEvents).mockResolvedValue(POPULATED_PAYLOAD);
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ window_s: "30" }),
    });
    render(tree);
    // The page must pass { windowS: 30 } to fetchFightEvents so the
    // gateway returns 30-second buckets. This locks down the
    // URL -> fetchFightEvents wiring (a refactor that drops the
    // searchParams parse would silently fall back to the default
    // 5s and the analyst would see wrong-sized buckets).
    expect(vi.mocked(fetchFightEvents)).toHaveBeenCalledWith(FIGHT_ID, {
      windowS: 30,
    });
    // Header + section headings still render.
    expect(
      screen.getByRole("heading", { level: 1, name: `Fight ${FIGHT_ID}` }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Event windows" }),
    ).toBeInTheDocument();
  });

  it("clamps an out-of-range window_s to the gateway default (no upstream 422)", async () => {
    vi.mocked(fetchFightEvents).mockResolvedValue(POPULATED_PAYLOAD);
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      // 9999 is well outside the gateway's [1, 600] range; the
      // page should clamp to 5s (the gateway default) instead of
      // forwarding the bogus value to fetchFightEvents.
      searchParams: Promise.resolve({ window_s: "9999" }),
    });
    render(tree);
    expect(vi.mocked(fetchFightEvents)).toHaveBeenCalledWith(FIGHT_ID, {
      windowS: 5,
    });
  });

  it("filters the three roll-up tables to a single target when ?target=N is set", async () => {
    // Multi-target payload: agent 1 appears in target_healing +
    // target_buff_removal; agent 2 appears only in target_dps.
    // Filtering to agent 1 should narrow the damage roll-up to
    // empty (agent 1 has no incoming damage) and keep the
    // healing + strip rows for agent 1. The "filtered to target"
    // sub-label on the duration line confirms the parseTarget
    // path is wired.
    const multiTarget = {
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
    vi.mocked(fetchFightEvents).mockResolvedValue(multiTarget);
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ target: "1" }),
    });
    render(tree);
    // Sub-label confirms the filter is active and the target id
    // is rendered for the analyst. Locks down the parseTarget
    // -> "filtered to target" wiring on the duration line.
    expect(screen.getByText(/filtered to target 1/)).toBeInTheDocument();
    // All six section headings still render (the per-target
    // filter narrows the rows inside, not the sections).
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
    // An unparseable target (non-numeric) must fall back to the
    // unfiltered view rather than render an error card. Mirrors
    // the parseWindowS leniency contract.
    vi.mocked(fetchFightEvents).mockResolvedValue(POPULATED_PAYLOAD);
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
      searchParams: Promise.resolve({ target: "not-a-number" }),
    });
    render(tree);
    // No "filtered to target" sub-label -- the filter was rejected
    // and the page rendered the unfiltered view.
    expect(screen.queryByText(/filtered to target/)).not.toBeInTheDocument();
    expect(screen.getByText(/Duration: 12.50 s/)).toBeInTheDocument();
  });
});
