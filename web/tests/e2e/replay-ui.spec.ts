/**
 * v0.10.18 D3: Playwright e2e spec for the Replay UI tab on
 * ``/fights/[id]?tab=replay`` (the Replay tab added by v0.10.17 D1).
 *
 * Why a deferred-from-v0.10.17 spec
 * ===================================
 * The v0.10.17 cycle shipped the ReplayPlayer Client Component
 * + vitest unit tests, but the Playwright e2e layer (which
 * exercises the FULL Server-Component-SSR -> Client-Component
 * hydration -> user-interaction path through a real browser)
 * was deferred. This spec closes the gap and gives the Replay
 * UI an anti-regression surface at the e2e layer.
 *
 * Substrate
 * =========
 * The mock-server (`tests/e2e/mock-server.mjs`) already serves
 * ``GET /api/v1/fights/:id/timeline?window_s=N`` with a
 * hard-coded inline 3-bucket stub (5s window, 1_000/3_000/2_000
 * damage). No mock-server edit is required -- the stub is
 * sufficient for the 4 assertions below (Replay tab renders,
 * scrubber responds, play/pause toggle works, no console
 * errors). The 3-bucket count drives the upstream
 * ``currentIndex`` upper bound (``max=N-1=2``).
 *
 * Anti-regression
 * ===============
 * A regression in:
 *   - page.tsx tab routing (e.g. removing the Replay tab)
 *   - ReplayPlayer's aria-pressed wiring
 *   - the scrubber's keyboard accessibility (focus + arrow
 *     keys trigger the React onChange handler)
 *   - the playback engine's setInterval cleanup (would
 *     produce a console error on unmount)
 * would each surface in this spec. The mock-server stub
 * also de-fans a regression in the timeline URL template
 * (the v0.10.17 D1 round-2 fix-shape is preserved by the
 * fixture's inline timeline payload).
 */

import { expect, test } from "@playwright/test";

test.describe("Replay UI (v0.10.18 D3)", () => {
  // The Replay tab is triggered by ``?tab=replay`` query param
  // per the page.tsx tab nav. The mock-server's KNOWN_FIGHTS
  // set accepts ``fixture-fight-001`` (the inline /timeline
  // stub serves 3 buckets with total_damage=1_000/3_000/2_000
  // for the 3 contiguous 1-second bucket windows).
  const FIGHT_ID = "fixture-fight-001";
  const REPLAY_URL = `/fights/${encodeURIComponent(FIGHT_ID)}?tab=replay`;

  test("page tab strip shows the Replay tab on /fights/[id]?tab=replay", async ({
    page,
  }) => {
    await page.goto(REPLAY_URL);
    // The Replay section testid is ``replay-player`` per
    // ReplayPlayer.tsx. Its presence confirms the page.tsx tab
    // nav routed the Replay component into the panel.
    const replaySection = page.locator('[data-testid="replay-player"]');
    await expect(replaySection).toBeVisible();
    // The section heading includes the fight id -- the
    // component renders "Replay — fight {fightId}".
    await expect(replaySection).toContainText(`Replay — fight ${FIGHT_ID}`);
    // The component initialises with the controls row +
    // scrubber + snapshot panel + bar chart visible. Skip
    // granular per-children assertions -- the v0.10.17 D2
    // vitest specs already cover the per-child happy paths.
    await expect(
      page.locator('[data-testid="replay-controls"]'),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="replay-bar-chart"]'),
    ).toBeVisible();
  });

  test("scrubber responds to keyboard nav (ArrowRight increments currentIndex)", async ({
    page,
  }) => {
    await page.goto(REPLAY_URL);
    const scrubber = page.locator('[data-testid="replay-scrubber"]');
    await expect(scrubber).toBeVisible();
    // ``aria-valuenow`` starts at 0 (currentIndex = 0). Range
    // inputs in React 18+ fire ``onChange`` ONLY when the
    // underlying DOM event fires (focus + arrow keys is the
    // canonical accessibility path).
    await expect(scrubber).toHaveAttribute("aria-valuenow", "0");
    // Focus + ArrowRight 2 times to advance from bucket 0 to
    // bucket 2 (the spec targets bucket 2 = third bucket so
    // the bar chart's "current" highlight visibly moves).
    await scrubber.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(scrubber).toHaveAttribute("aria-valuenow", "2");
    // The current bucket visual moves accordingly: exactly
    // ONE bar should carry the ``replay-bar-current`` testid
    // (the others carry ``replay-bar``).
    await expect(
      page.locator('[data-testid="replay-bar-current"]'),
    ).toHaveCount(1);
    // The "B3" badge floats above the third bucket (B{i+1}
    // where i is the current index; index=2 -> B3).
    await expect(
      page.locator('[data-testid="replay-bar-current"]'),
    ).toContainText("B3");
  });

  test("play/pause toggle flips aria-pressed without console errors", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.goto(REPLAY_URL);
    const playPause = page.locator('[data-testid="replay-play-pause"]');
    // Initial state: paused (``aria-pressed="false"``). The
    // button label is "▶ Play".
    await expect(playPause).toHaveAttribute("aria-pressed", "false");
    await expect(playPause).toContainText("Play");
    // Click → playing (``aria-pressed="true"``, label switches
    // to "❚❚ Pause").
    await playPause.click();
    await expect(playPause).toHaveAttribute("aria-pressed", "true");
    await expect(playPause).toContainText("Pause");
    // Click again → paused again. The setInterval must be
    // cleared on the off-click; a leak would surface as a
    // delayed "currentIndex" advance after the click. The
    // console-errors collector catches any cleanup failure
    // (e.g. the v0.10.17 D1 round-2 fix suppresses the
    // ``setIsPlaying during setInterval callback`` React
    // warning by deferring via `setTimeout(0)` -- if that
    // defer regressed, React would log "Cannot update a
    // component while rendering a different component" --
    // which the error collector catches).
    await playPause.click();
    await expect(playPause).toHaveAttribute("aria-pressed", "false");
    expect(errors).toEqual([]);
  });

  test("speed toggle button reflects the active speed via aria-pressed", async ({
    page,
  }) => {
    await page.goto(REPLAY_URL);
    // Default speed is 1x; the 1x button is active
    // (aria-pressed="true"), the 2x/4x/8x buttons are inactive
    // (aria-pressed="false"). The component renders one button
    // per speed (1x / 2x / 4x / 8x) with testid
    // ``replay-speed-${s}x``.
    await expect(
      page.locator('[data-testid="replay-speed-1x"]'),
    ).toHaveAttribute("aria-pressed", "true");
    for (const s of ["2x", "4x", "8x"] as const) {
      await expect(
        page.locator(`[data-testid="replay-speed-${s}"]`),
      ).toHaveAttribute("aria-pressed", "false");
    }
    // Click 4x → 4x is now active, 1x is no longer the
    // active speed. This is the speed-toggle inversion
    // test.
    await page.locator('[data-testid="replay-speed-4x"]').click();
    await expect(
      page.locator('[data-testid="replay-speed-4x"]'),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.locator('[data-testid="replay-speed-1x"]'),
    ).toHaveAttribute("aria-pressed", "false");
  });
});
