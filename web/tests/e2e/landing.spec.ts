/**
 * Playwright E2E for the v0.4.0-web landing page (/).
 *
 * The landing page is a pure Server Component (no client fetch);
 * it renders the brand strip + 4 navigation cards. The E2E
 * proves the SSR pipeline returns a fully-rendered tree for
 * the root path (so a regression in the home-page route is
 * caught) and that no uncaught exception fires during the
 * page load.
 *
 * Why a single smoke test (vs 1 per nav card)
 * ===========================================
 * The 4 nav cards all share the same SSR render path; the
 * per-card destination pages have their own dedicated
 * e2e specs (``fights.spec.ts``, ``players.spec.ts``,
 * ``account.spec.ts``, ``upload.spec.ts``). The e2e only
 * needs to prove that the SSR pipeline returns a
 * fully-rendered tree for the root path, so a single
 * heading + 4-card check is enough.
 */
import { test, expect } from "@playwright/test";

test.describe("/ (v0.4.0-web landing)", () => {
  test("renders the brand strip + 4 navigation cards", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));

    const response = await page.goto("/");
    expect(response?.status()).toBe(200);

    // Brand strip
    await expect(
      page.getByRole("heading", { name: "GW2Analytics", level: 1 }),
    ).toBeVisible();

    // 4 navigation cards. Use the ``home-nav-*`` data-testids
    // declared on each card in ``src/app/page.tsx`` so the
    // assertions stay stable across copy / i18n changes
    // (the previous regex selectors assumed an English-language
    // nav ("Browse fights", "Upload replay", ...); the page
    // has since been localised to French).
    await expect(page.getByTestId("home-nav-fights")).toBeVisible();
    await expect(page.getByTestId("home-nav-players")).toBeVisible();
    await expect(page.getByTestId("home-nav-compare")).toBeVisible();
    await expect(page.getByTestId("home-nav-upload")).toBeVisible();

    // No uncaught exceptions during page load. (We use
    // ``pageerror`` rather than ``console.error`` because the
    // latter also fires on dev-mode React hydration warnings,
    // which are benign and would false-positive the check.)
    expect(pageErrors).toEqual([]);
  });
});
