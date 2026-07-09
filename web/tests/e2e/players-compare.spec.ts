/**
 * v0.10.0 plan 032: e2e coverage for the cross-account
 * comparison page.
 *
 * Verifies the full RSC + Client Component pipeline:
 *  1. The Server Component fetches the mock-server
 *     payload on first paint.
 *  2. The Client Component renders the chart + the 2
 *     account chips.
 *  3. The metric radio toggles re-render the chart with
 *     a different metric's data shape (the chart's
 *     caption text changes from "Damage" to "Healing").
 *  4. The empty-state copy renders when fewer than 2
 *     ``?accounts=`` params are supplied.
 *
 * Why a real Next.js dev server (not page.route() mocking)
 * ========================================================
 * The page is a Server Component; its data fetch happens
 * in the Node.js process during SSR, BEFORE the browser
 * receives the HTML. ``page.route()`` runs in the browser
 * context and cannot reach those SSR fetches. We rely on
 * the existing mock-server.mjs (port 8080) which the
 * Playwright config's ``webServer`` block spawns.
 */

import { expect, test } from "@playwright/test";

test.describe("/players/compare (v0.10.0 plan 032)", () => {
  test("renders the cross-account chart with 2 accounts", async ({ page }) => {
    await page.goto(
      "/players/compare?accounts=TestAccount.1234&accounts=TestAccount.5678",
      { waitUntil: "networkidle" },
    );
    // The page header.
    await expect(
      page.getByRole("heading", { name: "Compare accounts" }),
    ).toBeVisible();
    // The two account chips (last-seen char-name, falling back to account_name).
    await expect(page.getByText("Test Char")).toBeVisible();
    await expect(page.getByText("Other Char")).toBeVisible();
    // The chart caption should reference the default metric (Damage).
    await expect(page.getByText(/Damage trend/)).toBeVisible();
    // The chart SVG must be present.
    const svg = page.locator("svg[aria-label*='comparison']");
    await expect(svg).toBeVisible();
  });

  test("metric radio toggles update the chart caption", async ({ page }) => {
    await page.goto(
      "/players/compare?accounts=TestAccount.1234&accounts=TestAccount.5678",
      { waitUntil: "networkidle" },
    );
    // Default: Damage.
    await expect(page.getByText(/Damage trend/)).toBeVisible();
    // Click the Healing radio.
    await page.getByRole("button", { name: "healing metric" }).click();
    await expect(page.getByText(/Healing trend/)).toBeVisible();
    // Click the Buff removal radio.
    await page.getByRole("button", { name: "strip metric" }).click();
    await expect(page.getByText(/Buff removal trend/)).toBeVisible();
  });

  test("renders the empty-state copy with 0 accounts", async ({ page }) => {
    await page.goto("/players/compare", { waitUntil: "networkidle" });
    await expect(
      page.getByRole("heading", { name: "Compare accounts" }),
    ).toBeVisible();
    await expect(page.getByText(/Add at least 2 accounts/)).toBeVisible();
  });
});
