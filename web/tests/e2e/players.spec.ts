/**
 * Playwright E2E for the v0.7.1 /players + /players/[account_name]
 * pages.
 *
 * Strategy
 * ========
 * The /players page is a Server Component that calls
 * ``fetchPlayers()`` at request time. The /players/[account_name]
 * page calls ``fetchPlayer(accountName)`` for the URL-decoded
 * segment. Both fetches go to the mock HTTP server on port 8080
 * (see tests/e2e/mock-server.mjs) so the tests are isolated from
 * the real FastAPI backend.
 *
 * Why smoke + golden-path only
 * ============================
 * The full happy path (Server Component renders the grid ->
 * analyst clicks an account link -> Server Component fetches
 * the profile -> breakdown table renders) plus the canonical
 * error path (unknown account -> upstream-error card) is
 * enough to prove the SSR + RSC contract is intact. The unit
 * tests under tests/app/ cover the fetcher-level edge cases.
 */
import { test, expect } from "@playwright/test";

test.describe("/players (v0.7.1)", () => {
  test("renders the cross-fight roll-up header", async ({ page }) => {
    await page.goto("/players");

    // Header + count sub-line (3 fixture players, plural).
    await expect(
      page.getByRole("heading", { name: "Players" }),
    ).toBeVisible();
    await expect(page.getByText("3 players across the cross-fight roll-up.")).toBeVisible();
  });

  test("renders the AG Grid with the 3 fixture rows", async ({ page }) => {
    await page.goto("/players");

    // AG Grid renders each row as a ``[role="row"]`` with
    // ``[role="gridcell"]`` children. The first column is the
    // account_name anchor; check for the 3 fixture accounts.
    await expect(page.getByRole("link", { name: "TestAccount.1234" })).toBeVisible();
    await expect(page.getByRole("link", { name: "TestAccount.5678" })).toBeVisible();
    await expect(page.getByRole("link", { name: "TestAccount.9999" })).toBeVisible();
  });

  test("clicking an account link navigates to the profile page", async ({ page }) => {
    await page.goto("/players");
    await page.getByRole("link", { name: "TestAccount.1234" }).click();
    await expect(page).toHaveURL(/\/players\/TestAccount\.1234$/);
    await expect(
      page.getByRole("heading", { name: "Test Char" }),
    ).toBeVisible();
  });
});

test.describe("/players/[account_name] (v0.7.1)", () => {
  test("renders the cross-fight stat cards + per-fight breakdown", async ({ page }) => {
    await page.goto("/players/TestAccount.1234");

    // Header strip
    await expect(
      page.getByRole("heading", { name: "Test Char" }),
    ).toBeVisible();
    await expect(
      page.getByText("TestAccount.1234 · ELEMENTALIST · ELITE(68)"),
    ).toBeVisible();

    // 4 stat cards
    await expect(page.getByText("Fights attended")).toBeVisible();
    await expect(page.getByText("42")).toBeVisible();
    await expect(page.getByText("Total damage")).toBeVisible();
    await expect(page.getByText("1200000")).toBeVisible();
    await expect(page.getByText("Total healing")).toBeVisible();
    await expect(page.getByText("250000")).toBeVisible();
    await expect(page.getByText("Total buff removal")).toBeVisible();
    await expect(page.getByText("300")).toBeVisible();

    // Per-fight breakdown: 2 rows (descending by started_at)
    await expect(page.getByRole("heading", { name: "Per-fight breakdown" })).toBeVisible();
    await expect(page.getByRole("link", { name: "fixture-fight-001" })).toBeVisible();
    await expect(page.getByRole("link", { name: "fixture-fight-002" })).toBeVisible();
  });

  test("back link returns to the players list", async ({ page }) => {
    await page.goto("/players/TestAccount.1234");
    await page.getByRole("link", { name: "← Back to players" }).click();
    await expect(page).toHaveURL(/\/players$/);
    await expect(
      page.getByRole("heading", { name: "Players" }),
    ).toBeVisible();
  });

  test("renders the upstream-error card for an unknown account", async ({ page }) => {
    // ``missing.9999`` is not in the mock server's KNOWN_PLAYERS
    // set, so the /players/:name fetch returns 404, the page
    // catches the ``ApiError``, and renders the upstream-error
    // card (the page does NOT raise 404 itself; the canonical
    // 404 lives at the API boundary).
    await page.goto("/players/missing.9999");

    // Header still renders, with the raw account name.
    await expect(
      page.getByRole("heading", { name: "Player missing.9999" }),
    ).toBeVisible();
    // The error card inlines the gateway's error body. The
    // exact text is wrapped by ``formatApiError`` (e.g.
    // "Upstream error: 404: ...").
    await expect(
      page.getByText(/Upstream error: 404: .*player not found/),
    ).toBeVisible();
  });
});
