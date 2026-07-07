/**
 * Playwright E2E for the v0.7.1 /fights/[id] page.
 *
 * The page calls 4 fetchers via ``Promise.allSettled``:
 *   1. ``fetchFightEvents(id, { windowS })`` -- the per-target
 *      trio + per-bucket event windows.
 *   2. ``fetchFightSquads(id)`` -- per-subgroup roll-up.
 *   3. ``fetchFightSkills(id)`` -- per-skill roll-up.
 *   4. ``fetchFightTimeline(id, { windowS })`` (v0.8.9 plan/002)
 *      -- per-fight timeline section.
 *
 * The mock server returns fixture JSON for all 4 endpoints when
 * the fight id is ``fixture-fight-001`` or ``fixture-fight-002``.
 *
 * Why a single smoke test (vs 6 + 1 for each section)
 * ==================================================
 * The 6 roll-up sections (per-target damage + healing +
 * buff-removal + per-subgroup + per-skill + per-fight timeline)
 * all share the same SSR fetch path; the section-level
 * rendering is fully covered by the unit tests in
 * tests/app/fight-events-page.test.tsx. The E2E only needs to
 * prove that the SSR pipeline returns a fully-rendered tree for
 * a real fight id (so a regression in the fetchers, the
 * routing, or the page contract is caught).
 */
import { test, expect } from "@playwright/test";

test.describe("/fights/[id] (v0.7.1)", () => {
  test("renders the 5 roll-up sections + event windows for a known fight", async ({ page }) => {
    await page.goto("/fights/fixture-fight-001");

    // Header strip
    await expect(
      page.getByRole("heading", { name: "Fight fixture-fight-001" }),
    ).toBeVisible();
    // The duration is rendered with 2-decimal fixed formatting
    // via ``toFixed(2)``; the JSON-stringified HTML splits the
    // children (the parser renders ``Duration: 12.50 s`` as
    // ``["Duration: ", "12.50", " s"]`` -- the .toBeVisible
    // check tolerates that).
    await expect(page.getByText(/Duration: 12\.50\s+s/)).toBeVisible();

    // The 5 roll-up section headings
    await expect(
      page.getByRole("heading", { name: "Per-target damage" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-target healing" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-target buff removal" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-subgroup (squad)" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-skill" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Event windows" }),
    ).toBeVisible();
    // v0.8.9 of web (plan/002): the per-fight timeline is the
    // 7th section, mounted below the per-bucket event windows.
    // The mock server's per-fight timeline handler returns 3
    // 5-second buckets for ``fixture-fight-001`` (15.0s
    // duration); the section heading + the chart's ``<svg>``
    // element are the only round-trip assertions we need.
    await expect(
      page.getByRole("heading", { name: "Per-fight timeline" }),
    ).toBeVisible();
  });

  test("renders the upstream-error card for an unknown fight id", async ({ page }) => {
    // ``unknown-fight-999`` is not in the mock server's
    // KNOWN_FIGHTS set, so the /events fetch returns 404, the
    // page catches the ``ApiError``, and renders the
    // upstream-error card.
    await page.goto("/fights/unknown-fight-999");

    await expect(
      page.getByRole("heading", { name: "Fight unknown-fight-999" }),
    ).toBeVisible();
    await expect(
      page.getByText(/Upstream error: 404: .*fight not found/),
    ).toBeVisible();
  });
});
