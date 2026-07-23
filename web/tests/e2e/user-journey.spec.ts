/**
 * Playwright E2E: full analyst user journey.
 *
 * This spec exercises the complete happy path an analyst would take:
 *   1. Land on the home page.
 *   2. Upload a ``.zevtc`` replay via the upload wizard.
 *   3. Drill into the parsed fight detail page.
 *   4. Browse the fights list.
 *   5. Browse the players list and open a player profile.
 *   6. Resolve a GW2 API key on the account page.
 *   7. Open the cross-account comparison page.
 *
 * At every step we capture a screenshot, assert that the page
 * renders the expected content, and collect any console or
 * uncaught page errors so regressions are surfaced immediately.
 *
 * The test relies on the mock HTTP server (``tests/e2e/mock-server.mjs``)
 * so it can run without the real FastAPI backend, Postgres, MinIO or
 * Redis stack. The mock server has been extended with:
 *   - ``POST /api/v1/uploads`` -> upload envelope
 *   - ``GET  /api/v1/uploads/:id`` -> completed status with ``fixture-fight-001``
 */

import { test, expect } from "@playwright/test";
import { join } from "node:path";
import { mkdirSync } from "node:fs";

const SCREENSHOT_DIR = "tests/e2e/screenshots/user-journey";

/**
 * Helper: capture a full-page screenshot with a stable file name.
 * Screenshots are written to ``web/tests/e2e/screenshots/user-journey/``
 * so they can be inspected after the run.
 */
async function screenshot(page: import("@playwright/test").Page, name: string) {
  await page.screenshot({
    path: join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  });
}

test.describe("full analyst user journey", () => {
  test.beforeAll(() => {
    mkdirSync(SCREENSHOT_DIR, { recursive: true });
  });

  test("upload, browse fights/players, resolve API key, compare accounts", async ({
    page,
  }) => {
    // -----------------------------------------------------------------
    // Error collectors
    // -----------------------------------------------------------------
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on("pageerror", (err) => pageErrors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    // -----------------------------------------------------------------
    // 1. Landing page
    // -----------------------------------------------------------------
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "GW2Analytics", level: 1 }),
    ).toBeVisible();
    // The 4 feature cards on the home page expose stable
    // ``home-nav-*`` data-testids (``src/app/page.tsx``) instead
    // of relying on the French card title. This keeps the
    // assertions independent of any future copy / i18n change.
    await expect(page.getByTestId("home-nav-fights")).toBeVisible();
    await expect(page.getByTestId("home-nav-players")).toBeVisible();
    await expect(page.getByTestId("home-nav-compare")).toBeVisible();
    await expect(page.getByTestId("home-nav-upload")).toBeVisible();
    await screenshot(page, "01-landing");

    // -----------------------------------------------------------------
    // 2. Upload wizard
    // -----------------------------------------------------------------
    await page.goto("/upload");
    await expect(
      page.getByRole("heading", { name: "Upload a .zevtc replay", level: 1 }),
    ).toBeVisible();
    await expect(page.getByTestId("file-input")).toBeAttached();
    await expect(page.getByTestId("next")).toBeDisabled();

    // Select the test fixture file.
    const fileInput = page.getByTestId("file-input");
    await fileInput.setInputFiles(join("tests/e2e/fixtures", "test.zevtc"));
    await expect(page.getByTestId("file-chip")).toContainText("test.zevtc");
    await expect(page.getByTestId("next")).toBeEnabled();
    await screenshot(page, "02-upload-pick");

    // Advance to upload/parse.
    await page.getByTestId("next").click();
    await expect(page.getByTestId("step-upload")).toBeVisible();
    await screenshot(page, "03-upload-uploading");

    // Wait for the wizard to reach the "done" step.
    await expect(page.getByTestId("step-done")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Upload complete")).toBeVisible();
    await expect(page.getByText("completed")).toBeVisible();
    await screenshot(page, "04-upload-done");

    // Drill into the parsed fight.
    const fightLink = page.getByRole("link", { name: "/fights/fixture-fight-001" });
    await expect(fightLink).toBeVisible();
    await fightLink.click();
    await expect(page).toHaveURL(/\/fights\/fixture-fight-001/);
    // v0.10.17+ default tab is "readout" (Analyse); the
    // ``Per-target damage`` heading below is rendered only in
    // the Overview tab content, so explicitly navigate to it
    // after the link click.
    await page.goto("/fights/fixture-fight-001?tab=overview");

    // -----------------------------------------------------------------
    // 3. Fight detail page
    // -----------------------------------------------------------------
    await expect(
      page.getByRole("heading", { name: "Fight fixture-fight-001" }),
    ).toBeVisible();
    // The fight detail page defaults to the Overview tab.
    await expect(page.getByRole("heading", { name: "Per-target damage" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Per-target healing" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-target buff removal" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Per-subgroup (squad)" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Per-skill" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Event windows" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Per-fight timeline" })).toBeVisible();
    await screenshot(page, "05-fight-detail-overview");

    // Switch to the Readout tab to exercise the per-player roll-up.
    await page.getByTestId("page-tab-readout").click();
    // v0.12.3+ removed the standalone "Combat readout loaded"
    // status banner (the page-tab readout now starts rendering
    // straight from the per-aspect sub-tabs; the page-level
    // banner was deprecated by the readiness-banner refactor).
    // The duration-strip assertion below stays (renders under
    // whichever sub-tab is active).
    await expect(page.getByText(/durée\s+\d+(?:[.,]\d+)?\s*s/i)).toBeVisible();
    // The 4 per-aspect section headings render under their
    // own localisable sub-tab buttons (Dégâts / Soins / Boons
    // / Défense & Positionnement); default is Dégâts.
    // Click each sub-tab before asserting its heading so the
    // panel mounts and the heading appears.
    await page.getByRole("button", { name: /Dégâts/i }).click();
    await expect(page.getByRole("heading", { name: /Dégâts/i })).toBeVisible();
    await page.getByRole("button", { name: /Soins/i }).click();
    await expect(page.getByRole("heading", { name: /Soins/i })).toBeVisible();
    await page.getByRole("button", { name: /Boons/i }).click();
    await expect(page.getByRole("heading", { name: /Boons/i })).toBeVisible();
    await page.getByRole("button", { name: /Défense/i }).click();
    await expect(page.getByRole("heading", { name: /Défense/i })).toBeVisible();
    await screenshot(page, "05b-fight-detail-readout");

    // -----------------------------------------------------------------
    // 4. Fights list
    // -----------------------------------------------------------------
    await page.goto("/fights");
    await expect(page.getByRole("heading", { name: "Fights", level: 1 })).toBeVisible();
    await expect(page.getByText("2 fights parsed and persisted.")).toBeVisible();
    await expect(page.getByRole("link", { name: "fixture-fight-001" })).toBeVisible();
    await expect(page.getByRole("link", { name: "fixture-fight-002" })).toBeVisible();
    await screenshot(page, "06-fights-list");

    // -----------------------------------------------------------------
    // 5. Players list + profile
    // -----------------------------------------------------------------
    await page.goto("/players");
    await expect(page.getByRole("heading", { name: "Players", level: 1 })).toBeVisible();
    await expect(page.getByText("3 players across the cross-fight roll-up.")).toBeVisible();
    await expect(page.getByRole("link", { name: "TestAccount.1234" })).toBeVisible();
    await expect(page.getByRole("link", { name: "TestAccount.5678" })).toBeVisible();
    await expect(page.getByRole("link", { name: "TestAccount.9999" })).toBeVisible();
    await screenshot(page, "07-players-list");

    await page.getByRole("link", { name: "TestAccount.1234" }).click();
    await expect(page).toHaveURL(/\/players\/TestAccount\.1234/);
    await expect(page.getByRole("heading", { name: "Test Char" })).toBeVisible();
    await expect(
      page.getByText("TestAccount.1234 · ELEMENTALIST · ELITE(68)"),
    ).toBeVisible();
    await expect(page.getByText("Fights attended")).toBeVisible();
    await expect(page.getByRole("link", { name: "fixture-fight-001" })).toBeVisible();
    await screenshot(page, "08-player-profile");

    // -----------------------------------------------------------------
    // 6. Account / API key resolve
    // -----------------------------------------------------------------
    await page.goto("/account");
    await expect(
      page.getByRole("heading", { name: "Resolve GW2 API key", level: 1 }),
    ).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeAttached();
    await expect(page.getByRole("button", { name: /Resolve/ })).toBeVisible();
    await screenshot(page, "09-account-form");

    await page.locator('input[type="password"]').fill("test-api-key-123");
    await page.getByRole("button", { name: /Resolve/ }).click();
    await expect(page.getByText("Resolved world")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Fixture World")).toBeVisible();
    await screenshot(page, "10-account-resolved");

    // -----------------------------------------------------------------
    // 7. Cross-account comparison
    // -----------------------------------------------------------------
    await page.goto(
      "/players/compare?accounts=TestAccount.1234&accounts=TestAccount.5678",
    );
    await expect(page.getByRole("heading", { name: "Compare accounts" })).toBeVisible();
    await expect(page.getByText("TestAccount.1234 · TestAccount.5678")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Comparison timeline" })).toBeVisible();
    await screenshot(page, "11-players-compare");

    // -----------------------------------------------------------------
    // Final assertions: no uncaught page errors, no console errors.
    // -----------------------------------------------------------------
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});
