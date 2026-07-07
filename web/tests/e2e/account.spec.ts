/**
 * Playwright E2E for the v0.2.0-api /account page.
 *
 * The /account page is a Client Component that collects a
 * GW2 API key and posts it (as Bearer) to
 * ``/api/v1/account`` to resolve the user's world triple. The
 * E2E proves the form renders correctly (heading + password
 * input + Resolve button) and that no uncaught exception
 * fires during the page load.
 *
 * Why we do NOT actually POST a real API key
 * ==========================================
 * The real GW2 v2 API would reject a test key. The mock
 * server's ``POST /api/v1/account`` handler is in place (see
 * tests/e2e/mock-server.mjs) but we intentionally do not
 * exercise it here. The spec only asserts the SSR +
 * form-rendering contract. The full Client Component
 * behaviour (state, error handling, result rendering) is
 * covered by the vitest unit tests under web/tests/app/.
 */
import { test, expect } from "@playwright/test";

test.describe("/account (v0.2.0-api world enrichment)", () => {
  test("renders the heading + password input + Resolve button", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));

    const response = await page.goto("/account");
    expect(response?.status()).toBe(200);

    // Heading
    await expect(
      page.getByRole("heading", { name: "Resolve GW2 API key", level: 1 }),
    ).toBeVisible();

    // Password input -- the input has no <label> association, so
    // the accessible name is empty. Use the direct ``locator``
    // (rather than ``getByRole``) for a stable query.
    await expect(page.locator('input[type="password"]')).toBeAttached();

    // Submit button (text is "Resolve" or "Resolving…" depending
    // on the in-flight state)
    await expect(
      page.getByRole("button", { name: /Resolve/ }),
    ).toBeVisible();

    // No uncaught exceptions during page load. (We use
    // ``pageerror`` rather than ``console.error`` because the
    // latter also fires on dev-mode React hydration warnings,
    // which are benign and would false-positive the check.)
    expect(pageErrors).toEqual([]);
  });
});
