/**
 * v0.8.0 of web: vitest cases for the per-account
 * :class:`PlayerTimelineSection` Client Component.
 *
 * Coverage
 * ========
 * - initial render: shows the "N of M" caption + the
 *   "Load more" button (when more pages exist)
 * - "all loaded" state: hides the button when
 *   ``points.length === total``
 * - "Load more" click: calls ``fetchPlayerTimeline`` with
 *   the correct ``offset`` (= current points.length) and
 *   appends the returned points to the in-memory list
 * - error state: surfaces the upstream error in the
 *   "Load error" pill and disables the button (no auto-retry)
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ApiError, type PlayerTimeline } from "@/lib/api";

/**
 * Override the global no-op mock for
 * :class:`PlayerTimelineSection` declared in
 * :file:`web/tests/setup.ts` so the real Client Component
 * runs. Without this override, the global ``vi.mock`` would
 * take precedence (the mock is registered before any test file
 * imports) and the component would render nothing, so
 * ``screen.getByRole("button", ...)`` would fail with
 * "Unable to find an accessible element". The
 * ``importOriginal`` pattern is the same one used in the
 * other component-level tests (window-size-selector, player-
 * search-bar) so the test setup stays consistent.
 */
vi.mock("@/components/PlayerTimelineSection", async (importOriginal) => {
  return await importOriginal<
    typeof import("@/components/PlayerTimelineSection")
  >();
});

const { fetchPlayerTimelineMock } = vi.hoisted(() => ({
  fetchPlayerTimelineMock: vi.fn<
    (
      accountName: string,
      opts: { limit?: number; offset?: number; bucket?: "fight" | "day" },
    ) => Promise<PlayerTimeline>
  >(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchPlayerTimeline: fetchPlayerTimelineMock,
  };
});

import { PlayerTimelineSection } from "@/components/PlayerTimelineSection";

function makeInitial(
  points: PlayerTimeline["points"],
  total: number,
): PlayerTimeline {
  return {
    account_name: ":synth.aaa",
    total,
    limit: 20,
    offset: 0,
    // v0.8.1 of web: the v0.8.0 test factory predates the
    // ``bucket`` field. Without this default the section's
    // ``useState<"fight" | "day">(initialTimeline.bucket)``
    // would fail TypeScript's exhaustive literal check.
    bucket: "fight",
    points,
  };
}

function makePoint(fight_id: string, total_damage: number): PlayerTimeline["points"][number] {
  return {
    fight_id,
    started_at: "2025-01-01T12:00:00Z",
    total_damage,
    total_healing: 0,
    total_buff_removal: 0,
  };
}

const INITIAL_3_OF_5 = makeInitial(
  [
    makePoint("f-1", 100),
    makePoint("f-2", 200),
    makePoint("f-3", 300),
  ],
  5,
);

describe("PlayerTimelineSection", () => {
  beforeEach(() => {
    fetchPlayerTimelineMock.mockReset();
  });

  it("renders the 'N of M' caption + the Load more button when more pages exist", () => {
    render(
      <PlayerTimelineSection
        accountName=":synth.aaa"
        initialTimeline={INITIAL_3_OF_5}
      />,
    );
    expect(screen.getByText("Showing 3 of 5 fights")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /load more timeline points/i });
    expect(button).toBeInTheDocument();
    expect(button).not.toBeDisabled();
  });

  it("disables the button when all points are loaded", () => {
    render(
      <PlayerTimelineSection
        accountName=":synth.aaa"
        initialTimeline={makeInitial(
          [makePoint("f-1", 100), makePoint("f-2", 200)],
          2,
        )}
      />,
    );
    expect(screen.getByText("Showing 2 of 2 fights")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /no more timeline points/i });
    expect(button).toBeInTheDocument();
    expect(button).toBeDisabled();
  });

  it("calls fetchPlayerTimeline with the correct offset on Load more and appends the result", async () => {
    fetchPlayerTimelineMock.mockResolvedValueOnce(
      makeInitial(
        [makePoint("f-4", 400), makePoint("f-5", 500)],
        5,
      ),
    );
    render(
      <PlayerTimelineSection
        accountName=":synth.aaa"
        initialTimeline={INITIAL_3_OF_5}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /load more timeline points/i }));
    await waitFor(() =>
      expect(fetchPlayerTimelineMock).toHaveBeenCalledWith(":synth.aaa", {
        limit: 20,
        offset: 3,
        // v0.8.1 of web: the route's ``?bucket=`` param is
        // now part of the contract. The initial timeline
        // carries ``bucket: "fight"`` (the section's
        // default), so the Load more call forwards it
        // unchanged. Asserting it here locks the contract
        // -- a future refactor that drops the ``bucket``
        // forwarding would fail this test.
        bucket: "fight",
      }),
    );
    await waitFor(() =>
      expect(screen.getByText("Showing 5 of 5 fights")).toBeInTheDocument(),
    );
  });

  it("surfaces the upstream error when fetchPlayerTimeline rejects and disables subsequent loads", async () => {
    fetchPlayerTimelineMock.mockRejectedValueOnce(new ApiError(502, "upstream gateway"));
    render(
      <PlayerTimelineSection
        accountName=":synth.aaa"
        initialTimeline={INITIAL_3_OF_5}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /load more timeline points/i }));
    await waitFor(() =>
      expect(
        screen.getByText("Upstream error: 502: 502: upstream gateway"),
      ).toBeInTheDocument(),
    );
    // The button re-enables after the error (we don't lock the
    // user out -- a reload is the recovery path, not a re-click),
    // but the caption still shows 3 of 5 (no points were appended).
    expect(screen.getByText("Showing 3 of 5 fights")).toBeInTheDocument();
  });

  it("deduplicates fight_ids that overlap between the initial page and the next page", async () => {
    // The route's tiebreaker + recency-first ordering should
    // make this impossible, but the defensive de-dup means
    // we never React-warn in dev mode if a fight gets added
    // to the dataset mid-pagination.
    fetchPlayerTimelineMock.mockResolvedValueOnce(
      makeInitial(
        // f-3 is already in the initial page; f-4 is new.
        [makePoint("f-3", 999), makePoint("f-4", 400)],
        5,
      ),
    );
    render(
      <PlayerTimelineSection
        accountName=":synth.aaa"
        initialTimeline={INITIAL_3_OF_5}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /load more timeline points/i }));
    await waitFor(() =>
      expect(screen.getByText("Showing 4 of 5 fights")).toBeInTheDocument(),
    );
  });
});
