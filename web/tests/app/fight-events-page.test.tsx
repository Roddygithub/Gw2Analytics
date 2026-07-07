/**
 * Phase 7 v1 of web: vitest tests for the new dynamic
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
 *   row + 3 event_windows). The page renders the header (fight_id
 *   + duration_s), all three section headings, and the
 *   canonical duration formatting.
 * - **Upstream 404**: ``fetchFightEvents`` rejects with
 *   :class:`ApiError`. The page renders the upstream-error card
 *   with the error body.
 * - **Empty roll-ups**: ``fetchFightEvents`` returns a payload
 *   with empty target_dps + target_healing + event_windows. The
 *   page still renders the header + the three section headings
 *   (the per-component empty-state message is asserted at the
 *   component level, not here).
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
// replacing ``fetchFightEvents`` with a vi.fn() so each test can
// stub its return value. ``importOriginal`` is the canonical vitest
// pattern for "mock one named export, leave the rest alone"; the
// alternative -- re-declaring the ApiError class inline in the mock
// factory -- drifts from the production shape the moment the
// constructor signature changes.
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchFightEvents: vi.fn(),
  };
});

import FightEventsPage from "@/app/fights/[id]/page";
import { fetchFightEvents, ApiError } from "@/lib/api";

const FIGHT_ID = "abc123def456";

const POPULATED_PAYLOAD = {
  fight_id: FIGHT_ID,
  duration_s: 12.5,
  target_dps: [
    { target_agent_id: 2, total_damage: 1234, dps: 1234 / 12.5 },
  ],
  target_healing: [
    { target_agent_id: 1, total_healing: 567, hps: 567 / 12.5 },
  ],
  event_windows: [
    { start_ms: 0, end_ms: 5000, damage_total: 800, healing_total: 300, event_count: 4 },
    { start_ms: 5000, end_ms: 10000, damage_total: 400, healing_total: 200, event_count: 3 },
    { start_ms: 10000, end_ms: 15000, damage_total: 34, healing_total: 67, event_count: 2 },
  ],
};

const EMPTY_PAYLOAD = {
  fight_id: FIGHT_ID,
  duration_s: 0,
  target_dps: [],
  target_healing: [],
  event_windows: [],
};

describe("FightEventsPage", () => {
  it("renders the header + section headings when fetchFightEvents returns a populated payload", async () => {
    vi.mocked(fetchFightEvents).mockResolvedValue(POPULATED_PAYLOAD);
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
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
      screen.getByRole("heading", { level: 2, name: "Event windows" }),
    ).toBeInTheDocument();
  });

  it("renders the upstream-error card when fetchFightEvents throws", async () => {
    vi.mocked(fetchFightEvents).mockRejectedValue(
      new ApiError(404, "fight not found"),
    );
    const tree = await FightEventsPage({
      params: Promise.resolve({ id: FIGHT_ID }),
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
    });
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: `Fight ${FIGHT_ID}` }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Duration: 0.00 s/)).toBeInTheDocument();
    // The three section headings always render -- the per-component
    // empty-state message lives inside the stubbed child components.
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target damage" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Per-target healing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Event windows" }),
    ).toBeInTheDocument();
  });
});
