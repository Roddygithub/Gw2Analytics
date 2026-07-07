/**
 * Playwright E2E for the v0.8.0 per-account historical
 * timeline.
 *
 * Strategy
 * ========
 * The /players/[account_name] page is a Server Component that
 * calls ``fetchPlayerTimeline(accountName)`` on the server (the
 * first page only, default ``limit=20``). The page passes the
 * initial data to a Client Component (``PlayerTimelineSection``)
 * which owns the "Load more" pagination state.
 *
 * The mock server returns a 2-point timeline fixture for
 * known players (TestAccount.1234, TestAccount.5678,
 * TestAccount.9999) and 404 for unknown players. The page
 * swallows the 404 (treated as "player has no attended
 * fights") and renders a synthetic-empty timeline with the
 * "No timeline data available." empty-state panel.
 *
 * What is exercised
 * =================
 * - Golden path: profile page renders the timeline section
 *   header + "Showing N of M" caption + the SVG line chart
 *   with 2 points x 3 series = 6 dots + the colour legend
 *   (3 swatches) + the "All fights loaded" disabled button
 *   (since total=2 <= limit=20).
 * - Empty path: unknown player (404) renders the section
 *   with "Showing 0 of 0 fights" + the empty-state panel.
 * - The "Load more" Client Component is exercised by the
 *   vitest unit tests in
 *   :file:`web/tests/components/player-timeline-section.test.tsx`
 *   (which can assert on the state-update contract
 *   deterministically without booting the browser).
 * - The hover-tooltip (``<title>`` on the group) is covered
 *   by the vitest unit tests in
 *   :file:`web/tests/components/player-timeline-chart.test.tsx`;
 *   the Playwright ``hover()`` would just assert that the
 *   native browser tooltip appears, which is a
 *   browser-internal behaviour (out of scope for the E2E).
 */
import { test, expect } from "@playwright/test";

test.describe("/players/[account_name] historical timeline (v0.8.0)", () => {
  test("renders the timeline section + chart for a known player", async ({
    page,
  }) => {
    await page.goto("/players/TestAccount.1234");

    // Section header + caption.
    await expect(
      page.getByRole("heading", { name: "Historical timeline" }),
    ).toBeVisible();
    await expect(page.getByText("Showing 2 of 2 fights")).toBeVisible();

    // 3 legend swatches (Damage / Healing / Buff removal).
    // Scoped to the legend via ``[role="list"]`` because
    // ``getByText`` is case-insensitive by default and would
    // ALSO match the "Total buff removal" stat card on the
    // same page (strict-mode violation: multiple matches).
    const legend = page.locator('[role="list"][aria-label="Timeline legend"]');
    await expect(legend.getByText("Damage")).toBeVisible();
    await expect(legend.getByText("Healing")).toBeVisible();
    await expect(legend.getByText("Buff removal")).toBeVisible();

    // Chart: 2 points x 3 series = 6 SVG ``<circle>`` dots.
    // The chart is normalised to 0-100% of per-series max so
    // the visual line height does not correspond to the raw
    // value; the absolute values are surfaced via the SVG
    // ``<title>`` tooltip (covered by the chart unit test).
    //
    // Scoped to the chart's specific SVG (via its unique
    // ``aria-label="Per-account historical timeline"``)
    // rather than a page-wide ``svg circle`` query, because
    // a page-wide query can be inflated by sibling SVGs
    // (e.g. the Next.js dev-mode error overlay, which
    // renders an ``<svg>`` icon for the hydration-warning
    // toast) -- the chart itself is the unit under test.
    const chart = page.locator('svg[aria-label="Per-account historical timeline"]');
    const circles = chart.locator("circle");
    await expect(circles).toHaveCount(6);

    // 3 polylines (one per series).
    const paths = chart.locator("path");
    await expect(paths).toHaveCount(3);

    // "Load more" button is disabled because all 2 points
    // are already loaded (total=2 <= limit=20).
    const button = page.getByRole("button", { name: /no more timeline points/i });
    await expect(button).toBeVisible();
    await expect(button).toBeDisabled();
    // The button label flips to "All fights loaded" when disabled.
    await expect(page.getByText("All fights loaded")).toBeVisible();
  });

  test("renders the empty-state panel when the timeline endpoint returns 404 (known profile)", async ({
    page,
  }) => {
    // ``empty-history.5678`` is in the mock server's
    // KNOWN_PLAYERS set, so the profile fetch returns 200
    // (the alt fixture). The timeline fetch for this
    // player is hard-coded to 404 in the mock server, so
    // the page swallows the 404 (treated as "player has
    // no attended fights") and renders the timeline
    // section with a synthetic-empty PlayerTimeline:
    // "Showing 0 of 0 fights" + the chart's empty-state
    // panel + a disabled "All fights loaded" button.
    await page.goto("/players/empty-history.5678");

    // The profile 200 path renders the normal page chrome
    // (header + stat cards + per-fight breakdown).
    await expect(
      page.getByRole("heading", { name: "Alt Char" }),
    ).toBeVisible();

    // The timeline section is ALWAYS rendered (synthetic-empty
    // on the 404 path -- the section is never silently
    // omitted).
    await expect(
      page.getByRole("heading", { name: "Historical timeline" }),
    ).toBeVisible();
    await expect(page.getByText("Showing 0 of 0 fights")).toBeVisible();
    // Chart's empty-state panel.
    await expect(
      page.getByText("No timeline data available."),
    ).toBeVisible();
    // "Load more" button is disabled (no more pages to load).
    await expect(page.getByText("All fights loaded")).toBeVisible();
  });

  test("renders the upstream-error card for an unknown player (both endpoints 404)", async ({
    page,
  }) => {
    // ``missing.9999`` is not in the mock server's KNOWN_PLAYERS
    // set, so BOTH the profile fetch AND the timeline fetch
    // return 404. The profile 404 is fatal (the page renders
    // the upstream-error card before the timeline section is
    // touched). The 404 path is the same one exercised by the
    // v0.7.1 /players/[account_name] tests; this E2E simply
    // confirms the v0.8.0 page extension didn't regress the
    // error rendering.
    await page.goto("/players/missing.9999");
    await expect(
      page.getByRole("heading", { name: "Player missing.9999" }),
    ).toBeVisible();
    await expect(
      page.getByText(/Upstream error: 404: .*player not found/),
    ).toBeVisible();
  });
});
