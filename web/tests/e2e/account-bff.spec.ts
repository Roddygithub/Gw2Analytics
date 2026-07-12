import { test, expect } from "@playwright/test";

const BFF_URL = "/api/account/resolve";

const VALID_WORLD = {
  world_id: 1001,
  world_name: "Fixture World",
  world_population: "Medium",
};

function mockBff(page: import("@playwright/test").Page, status: number, body: unknown) {
  return page.route(`**${BFF_URL}`, (route) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
}

test.describe("/account BFF proxy", () => {
  test("valid key → resolves world", async ({ page }) => {
    await mockBff(page, 200, VALID_WORLD);
    await page.goto("/account");

    await page.locator('input[type="password"]').fill("test-api-key-123");
    const btn = page.getByRole("button", { name: /Resolve/ });
    await expect(btn).toBeEnabled({ timeout: 5000 });
    await btn.click();

    await expect(page.getByText("Fixture World")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("1001")).toBeVisible();
    await expect(page.getByText("Medium")).toBeVisible();
  });

  test("missing key → 401 error", async ({ page }) => {
    await mockBff(page, 401, { detail: "Invalid API key" });
    await page.goto("/account");

    await page.locator('input[type="password"]').fill("missing-key");
    const btn = page.getByRole("button", { name: /Resolve/ });
    await btn.click();

    await expect(page.getByText(/401|Invalid/)).toBeVisible({ timeout: 10_000 });
  });

  test("malformed key → 400 error", async ({ page }) => {
    await mockBff(page, 400, { detail: "malformed key" });
    await page.goto("/account");

    await page.locator('input[type="password"]').fill("not-a-real-key");
    const btn = page.getByRole("button", { name: /Resolve/ });
    await btn.click();

    await expect(page.getByText(/400|malformed/)).toBeVisible({ timeout: 10_000 });
  });

  test("network error → 502 gateway error", async ({ page }) => {
    await mockBff(page, 502, { detail: "Bad Gateway" });
    await page.goto("/account");

    await page.locator('input[type="password"]').fill("any-key");
    const btn = page.getByRole("button", { name: /Resolve/ });
    await btn.click();

    await expect(page.getByText(/502|Gateway/)).toBeVisible({ timeout: 10_000 });
  });

  test("resolve button disabled when key is empty", async ({ page }) => {
    await page.goto("/account");
    const btn = page.getByRole("button", { name: /Resolve/ });
    await expect(btn).toBeDisabled();
  });
});
