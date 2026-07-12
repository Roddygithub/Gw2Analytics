/**
 * v0.10.17 D2 deliverable: component-level vitest test for the
 * :class:`ReplayPlayer` Client Component.
 *
 * What is exercised
 * =================
 * - **Render chrome** -- scrubber, Play/Pause, Reset, the 1x/2x/4x/8x
 *   speed buttons, the 4-cell snapshot panel, the bar chart
 *   container, the legend, and the bucket count.
 * - **Initial state** -- ``currentIndex === 0`` on mount (the
 *   analyst opens the Replay tab at the fight-start bucket).
 * - **Playback engine** -- ``setInterval`` registration on
 *   Play click, ``currentIndex`` advancement per
 *   ``windowS * 1000 / speed`` ms tick, ``isPlaying === false``
 *   on Pause click, ``currentIndex === 0`` + ``isPlaying === false``
 *   on Reset click, and the auto-pause at the last bucket.
 * - **Speed toggle** -- 1x @ 5 s window = 5000 ms interval;
 *   8x @ 5 s window = 625 ms interval.
 * - **Scrubber drag** -- ``<input type="range">`` change event
 *   updates ``currentIndex`` + the snapshot panel reads.
 * - **Current bucket highlight** -- the active bucket gets a 2px
 *   border + a ``B{i+1}`` badge.
 * - **Bar chart population** -- N bucket containers + ``3 * N``
 *   sub-bars (damage / healing / strip).
 * - **Empty states** -- ``timeline === null`` renders the
 *   "Replay unavailable" caption; ``timeline.points.length === 0``
 *   renders the "Replay unavailable: zero buckets" caption.
 *
 * What is NOT exercised
 * =====================
 * - The Replay tab page routing (the page-level tab strip lives
 *   in :file:`web/src/app/fights/[id]/page.tsx` and is covered
 *   by :file:`web/tests/app/fight-events-page.test.tsx`).
 * - The :func:`fetchReplayTimeline` wrapper (covered by :file:`web/tests/lib/fetchCached-isolation.test.ts`
 *   via the underlying :func:`fetchCached` cache substrate; the
 *   wrapper itself is a one-liner URL constructor + a
 *   ``fetchCached`` passthrough).
 * - End-to-end browser interaction (covered by the Playwright
 *   spec in :file:`web/tests/e2e/fights.spec.ts` + the
 *   planned :file:`web/tests/e2e/replay-ui.spec.ts`).
 *
 * Why ``vi.useFakeTimers`` (vs real timers)
 * ==========================================
 * The :class:`ReplayPlayer` registers a real ``setInterval`` on
 * Play click + tears it down on Pause / Reset / dep change.
 * Real-timer tests would require wall-clock waits of 5+ seconds
 * per tick (the default ``windowS * 1000 / speed`` interval) +
 * would be flaky on slow CI. Fake timers let the test advance
 * the clock deterministically (``vi.advanceTimersByTime(5000)``
 * fires one tick at exactly 5 s simulated) and let the assertion
 * run on the resulting state immediately.
 *
 * Why each ``vi.advanceTimersByTime`` is wrapped in ``act()``
 * ============================================================
 * React 18+'s automatic batching queues ``setState`` calls from
 * non-event sources (including the ``setInterval`` callback) on
 * a microtask; without ``act()`` wrapping, the next test
 * statement (``screen.getByText(...)``) may read STALE DOM.
 * Synchronous ``act(() => { vi.advanceTimersByTime(N); })``
 * flushes React's update queue so the DOM re-render happens
 * BEFORE the assertion reads. Without this, 5 of 13 tests
 * fail with "stale Bucket 1 / 6 after the 5 s tick" symptoms.
 * ``fireEvent.change`` / ``fireEvent.click`` are auto-wrapped
 * by RTL so the scrubber-drag + reset-click assertions don't
 * need an explicit ``act()`` -- only the post-click
 * ``vi.advanceTimersByTime`` chain does.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { ReplayPlayer } from "@/components/ReplayPlayer";
import type { FightTimeline } from "@/lib/api/fights";

/** Build a :class:`FightTimeline` fixture with N buckets. */
function makeTimeline(windowS: number = 5, nBuckets: number = 6): FightTimeline {
  const points = [];
  for (let i = 0; i < nBuckets; i++) {
    points.push({
      window_start_ms: i * windowS * 1000,
      window_end_ms: (i + 1) * windowS * 1000,
      // Damage / healing / strip grow monotonically with bucket
      // index so a per-bucket assertion can disambiguate which
      // bucket the scrubber is on (e.g. bucket 3 has damage=4000).
      total_damage: (i + 1) * 1000,
      total_healing: (i + 1) * 500,
      total_buff_removal: (i + 1) * 50,
    });
  }
  return {
    fight_id: "abc123def456",
    window_s: windowS,
    duration_s: nBuckets * windowS,
    points,
  };
}

const FIGHT_ID = "abc123def456";

describe("ReplayPlayer", () => {
  beforeEach(() => {
    // Fake timers for the playback engine; without these, a
    // 5 s default-window test would require 30+ seconds of
    // wall-clock wait per case (slow + flaky on CI).
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // -------------------------------------------------------------------------
  // RENDER CHROME
  // -------------------------------------------------------------------------

  it("renders scrubber + Play/Pause/Reset + speed buttons + snapshot panel + bar chart + legend", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    // Section-level aria-label.
    expect(screen.getByLabelText(`Replay fight ${FIGHT_ID}`)).toBeInTheDocument();
    // Scrubber + control row.
    expect(screen.getByTestId("replay-scrubber")).toBeInTheDocument();
    expect(screen.getByTestId("replay-play-pause")).toBeInTheDocument();
    expect(screen.getByLabelText("Reset replay")).toBeInTheDocument();
    // 4 speed buttons (1x / 2x / 4x / 8x).
    expect(screen.getByTestId("replay-speed-1x")).toBeInTheDocument();
    expect(screen.getByTestId("replay-speed-2x")).toBeInTheDocument();
    expect(screen.getByTestId("replay-speed-4x")).toBeInTheDocument();
    expect(screen.getByTestId("replay-speed-8x")).toBeInTheDocument();
    // Snapshot panel (4 cells).
    expect(screen.getByTestId("replay-current-snapshot")).toBeInTheDocument();
    // Bar chart container.
    expect(screen.getByTestId("replay-bar-chart")).toBeInTheDocument();
    // Legend.
    expect(screen.getByTestId("replay-legend")).toBeInTheDocument();
  });

  it("renders N bucket containers + 3N sub-bars (damage + healing + strip) when N buckets present", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    // 1 current bucket + (N - 1) non-current buckets. The
    // current bucket uses ``data-testid="replay-bar-current"``;
    // the others use ``"replay-bar"``. Total = N.
    expect(screen.getByTestId("replay-bar-current")).toBeInTheDocument();
    expect(screen.getAllByTestId("replay-bar")).toHaveLength(5);
    // 3 sub-bars per bucket (N total each).
    expect(screen.getAllByTestId("replay-bar-damage")).toHaveLength(6);
    expect(screen.getAllByTestId("replay-bar-healing")).toHaveLength(6);
    expect(screen.getAllByTestId("replay-bar-strip")).toHaveLength(6);
  });

  it("starts with currentIndex=0 (Bucket 1 of N at t=0s)", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);
    // "Bucket 1 / 6" — the 1-indexed display read.
    expect(screen.getByText("Bucket 1 / 6")).toBeInTheDocument();
    // t = 0:00 — the bucket-0 window_start wallclock.
    expect(screen.getByText("t = 0:00")).toBeInTheDocument();
    // Scrubber initial value.
    expect(
      (screen.getByTestId("replay-scrubber") as HTMLInputElement).value,
    ).toBe("0");
  });

  it("uses english-locale formatted totals in the snapshot panel (Damage 1,000 etc)", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);
    // Bucket 0's damage = 1000 → "1,000" (locale-formatted).
    // The snapshot panel has 4 cells: each label is unique
    // (Damage / Healing / Strip / Window) so we can find
    // their adjacent value via the parent cell.
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument(); // healing #0
    expect(screen.getByText("50")).toBeInTheDocument(); // strip #0
    expect(screen.getByText("0:00–0:05")).toBeInTheDocument(); // window range
  });

  // -------------------------------------------------------------------------
  // PLAYBACK ENGINE
  // -------------------------------------------------------------------------

  it("Play click registers a setInterval that advances currentIndex by 1 every windowS*1000/speed ms", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    // Click Play → isPlaying=true → setInterval(5000ms).
    fireEvent.click(screen.getByTestId("replay-play-pause"));
    expect(
      (screen.getByTestId("replay-play-pause") as HTMLButtonElement)
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(screen.getByText("Bucket 1 / 6")).toBeInTheDocument();

    // Advance one 5 s tick → bucket 1 → display "Bucket 2 / 6".
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("Bucket 2 / 6")).toBeInTheDocument();

    // Advance three more 5 s ticks → bucket 4 → display "Bucket 5 / 6".
    act(() => {
      vi.advanceTimersByTime(15_000);
    });
    expect(screen.getByText("Bucket 5 / 6")).toBeInTheDocument();
  });

  it("speed toggle changes the intervalMs (8x advances 1 bucket every 625ms at 5s window)", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    // Click Play at default 1x.
    fireEvent.click(screen.getByTestId("replay-play-pause"));
    act(() => {
      vi.advanceTimersByTime(5000);
    }); // 1x interval @ 5s window
    expect(screen.getByText("Bucket 2 / 6")).toBeInTheDocument();

    // Toggle to 8x. The cleanup clears the 1x interval BEFORE
    // the new effect registers the 8x interval (React effects
    // contract preserves this ordering).
    fireEvent.click(screen.getByTestId("replay-speed-8x"));
    act(() => {
      vi.advanceTimersByTime(625);
    }); // 1 8x interval @ 5s window = 5000/8
    expect(screen.getByText("Bucket 3 / 6")).toBeInTheDocument();
  });

  it("Pause click stops the setInterval advancement", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    fireEvent.click(screen.getByTestId("replay-play-pause")); // play
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(screen.getByText("Bucket 2 / 6")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("replay-play-pause")); // pause
    expect(
      (screen.getByTestId("replay-play-pause") as HTMLButtonElement)
        .getAttribute("aria-pressed"),
    ).toBe("false");
    // Advance enough wall-clock for 4+ ticks — index must NOT advance.
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(screen.getByText("Bucket 2 / 6")).toBeInTheDocument();
  });

  it("Reset click pauses + sets currentIndex=0", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    fireEvent.click(screen.getByTestId("replay-play-pause")); // play
    act(() => {
      vi.advanceTimersByTime(10_000);
    }); // 2 ticks → bucket 2
    expect(screen.getByText("Bucket 3 / 6")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Reset replay"));
    // currentIndex → 0 → display "Bucket 1 / 6".
    expect(screen.getByText("Bucket 1 / 6")).toBeInTheDocument();
    // isPlaying → false → aria-pressed flips on Play/Pause button.
    expect(
      (screen.getByTestId("replay-play-pause") as HTMLButtonElement)
        .getAttribute("aria-pressed"),
    ).toBe("false");
    // Scrubber value resets to "0".
    expect(
      (screen.getByTestId("replay-scrubber") as HTMLInputElement).value,
    ).toBe("0");
  });

  it("auto-pauses at the last bucket (no wrap-around; Play at end restarts from bucket 0)", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    fireEvent.click(screen.getByTestId("replay-play-pause")); // play
    // Advance 6 intervals → reach bucket 5 (last).
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByText("Bucket 6 / 6")).toBeInTheDocument();
    // The auto-pause's setIsPlaying(false) was deferred via
    // setTimeout(0); advance 0ms to flush the microtask.
    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(
      (screen.getByTestId("replay-play-pause") as HTMLButtonElement)
        .getAttribute("aria-pressed"),
    ).toBe("false");

    // Click Play at end → reset to 0 + start playing again.
    fireEvent.click(screen.getByTestId("replay-play-pause"));
    expect(screen.getByText("Bucket 1 / 6")).toBeInTheDocument();
    expect(
      (screen.getByTestId("replay-play-pause") as HTMLButtonElement)
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });

  // -------------------------------------------------------------------------
  // SCRUBBER DRAG
  // -------------------------------------------------------------------------

  it("scrubber drag (change event) updates currentIndex + the snapshot panel reads", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);

    const scrubber = screen.getByTestId(
      "replay-scrubber",
    ) as HTMLInputElement;

    // Drag to bucket 3 → display "Bucket 4 / 6" + t = 0:15.
    // fireEvent is auto-wrapped by RTL so the React update
    // queue flushes before the assertion reads.
    fireEvent.change(scrubber, { target: { value: "3" } });
    expect(screen.getByText("Bucket 4 / 6")).toBeInTheDocument();
    expect(screen.getByText("t = 0:15")).toBeInTheDocument();
    // Bucket 3 has damage = 4,000 (locale-formatted).
    expect(screen.getByText("4,000")).toBeInTheDocument();
    // Scrubber value committed.
    expect(scrubber.value).toBe("3");
  });

  // -------------------------------------------------------------------------
  // CURRENT-BUCKET HIGHLIGHT
  // -------------------------------------------------------------------------

  it("the current bucket gets the B{i+1} badge (1-indexed read)", () => {
    const timeline = makeTimeline(5, 6);
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={timeline} />);
    // Initial currentIndex = 0 → badge "B1".
    expect(screen.getByText("B1")).toBeInTheDocument();

    // Drag to bucket 2 → badge "B3".
    fireEvent.change(screen.getByTestId("replay-scrubber"), {
      target: { value: "2" },
    });
    expect(screen.getByText("B3")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // EMPTY STATES
  // -------------------------------------------------------------------------

  it("renders 'Replay unavailable' caption when timeline=null", () => {
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={null} />);
    expect(screen.getByTestId("replay-unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Replay unavailable/)).toBeInTheDocument();
    // The replay chrome must NOT render in the empty-state branch.
    expect(screen.queryByTestId("replay-scrubber")).not.toBeInTheDocument();
    expect(screen.queryByTestId("replay-play-pause")).not.toBeInTheDocument();
  });

  it("renders 'Replay unavailable: zero buckets' caption when timeline.points.length === 0", () => {
    const emptyTimeline: FightTimeline = {
      fight_id: FIGHT_ID,
      window_s: 5,
      duration_s: 0,
      points: [],
    };
    render(<ReplayPlayer fightId={FIGHT_ID} timeline={emptyTimeline} />);
    expect(screen.getByTestId("replay-empty")).toBeInTheDocument();
    expect(screen.getByText(/zero buckets/)).toBeInTheDocument();
    // Same chrome-not-rendered contract.
    expect(screen.queryByTestId("replay-scrubber")).not.toBeInTheDocument();
  });
});
