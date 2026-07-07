/**
 * Playwright E2E for the v0.5.0-web /upload page.
 *
 * The /upload page is a Client Component that posts a
 * ``.zevtc`` combat log as ``multipart/form-data`` to
 * ``/api/v1/uploads``. The E2E proves the form renders
 * correctly (heading + file input + Upload button -- with
 * the Upload button correctly disabled when no file is
 * selected) and that no uncaught exception fires during
 * the page load.
 *
 * Why we do NOT actually upload a file
 * ====================================
 * The real gateway would reject a test blob + the parser
 * would surface a useless error. The mock server's
 * ``POST /api/v1/uploads`` handler is in place (see
 * tests/e2e/mock-server.mjs) but we intentionally do not
 * exercise it here. The spec only asserts the SSR +
 * form-rendering contract. The full Client Component
 * behaviour (file selection, extension validation, error
 * handling, result rendering) is covered by the vitest
 * unit tests under web/tests/app/.
 */
import { test, expect } from "@playwright/test";

test.describe("/upload (v0.5.0-web combat log uploader)", () => {
  test("renders the heading + file input + disabled submit button", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));

    const response = await page.goto("/upload");
    expect(response?.status()).toBe(200);

    // Heading
    await expect(
      page.getByRole("heading", { name: "Upload a .zevtc replay", level: 1 }),
    ).toBeVisible();

    // File input (the page uses ``data-testid="file-input"``)
    await expect(page.getByTestId("file-input")).toBeAttached();

    // Submit button (the page uses ``data-testid="submit"``;
    // disabled by default because no file is selected)
    await expect(page.getByTestId("submit")).toBeAttached();
    await expect(page.getByTestId("submit")).toBeDisabled();

    // No uncaught exceptions during page load. (We use
    // ``pageerror`` rather than ``console.error`` because the
    // latter also fires on dev-mode React hydration warnings,
    // which are benign and would false-positive the check.)
    expect(pageErrors).toEqual([]);
  });
});
