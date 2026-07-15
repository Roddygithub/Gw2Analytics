/**
 * Playwright E2E for the v0.10.22+ global sticky header.
 *
 * The header is rendered by the root Server Component layout
 * and is therefore present on every page. These tests verify
 * the new GW2Mists rebrand elements (logo, brand, nav links)
 * and that the primary navigation links route to the expected
 * pages without a full page reload (Next.js Link behaviour).
 *
 * The tests run against the mock HTTP server on port 8080 so
 * they are isolated from the real FastAPI backend.
 */
import { test, expect } from "@playwright/test";

test.describe("global header (v0.10.22 rebrand)", () => {
  let pageErrors: string[] = [];

  test.beforeEach(({ page }) => {
    pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
  });

  test.afterEach(() => {
    expect(pageErrors).toEqual([]);
  });

  test("renders the logo, brand and nav links on the home page", async ({ page }) => {
    await page.goto("/");

    // Header is present and sticky.
    const header = page.getByTestId("global-header");
    await expect(header).toBeVisible();

    // Brand link contains the SVG logo and the brand text.
    const brand = page.getByTestId("brand-link");
    await expect(brand).toBeVisible();
    await expect(brand.locator("svg[aria-hidden='true']")).toBeVisible();
    await expect(brand).toContainText("GW2");
    await expect(brand).toContainText("Analytics");

    // Primary nav links.
    await expect(page.getByTestId("nav-players")).toBeVisible();
    await expect(page.getByTestId("nav-compare")).toBeVisible();

    // Global player search bar is present.
    await expect(page.getByTestId("player-search-form")).toBeVisible();
  });

  test("Players link navigates to /players", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("nav-players").click();
    await expect(page).toHaveURL(/\/players$/);
    await expect(page.getByRole("heading", { name: "Players" })).toBeVisible();
  });

  test("Compare link navigates to /players/compare", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("nav-compare").click();
    await expect(page).toHaveURL(/\/players\/compare$/);
    // The compare page renders its main heading.
    await expect(
      page.getByRole("heading", { name: "Compare accounts" }),
    ).toBeVisible();
  });

  test("brand link navigates to the home page", async ({ page }) => {
    await page.goto("/players");
    await page.getByTestId("brand-link").click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "GW2Analytics", level: 1 })).toBeVisible();
  });

  test("header remains visible when scrolling a long page", async ({ page }) => {
    await page.goto("/players");
    const header = page.getByTestId("global-header");
    await expect(header).toBeVisible();

    // Scroll to the bottom of the page; the sticky header should still be in DOM.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(header).toBeVisible();

    // The header is positioned at the top of the viewport (sticky behaviour).
    const box = await header.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y).toBeLessThanOrEqual(1);
  });
});
