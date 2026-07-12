import { test, expect } from "@playwright/test";

test.describe("/account BFF proxy flow", () => {
  test("submits a fake key and shows the resolved world", async ({
    page,
  }) => {
    await page.goto("/account");

    // Type into the password input (triggers React onChange)
    const input = page.locator('input[type="password"]');
    await input.click();
    await input.type("test-api-key-123");

    // Button should be enabled after typing
    const btn = page.getByRole("button", { name: /Resolve/ });
    await expect(btn).toBeEnabled({ timeout: 5000 });

    // Click Resolve
    await btn.click();

    // Wait for the result to appear (mock-server returns Fixture World)
    await expect(page.getByText("Fixture World")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("1001")).toBeVisible();
    await expect(page.getByText("Medium")).toBeVisible();
  });

  test("shows error when submitting empty key", async ({ page }) => {
    await page.goto("/account");

    const btn = page.getByRole("button", { name: /Resolve/ });
    await expect(btn).toBeDisabled();
  });
});
