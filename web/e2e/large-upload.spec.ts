/**
 * Real-stack large-upload regression test.
 *
 * Next.js dev server's rewrite/proxy enforces a hard 10 MB request body
 * limit. Without intervention, uploading a real .zevtc larger than 10 MB
 * through the frontend fails with ECONNRESET/500. This test verifies the
 * Playwright route interception workaround: POST /api/v1/uploads is
 * forwarded directly to the FastAPI backend so the upload succeeds.
 *
 * Like user-journey.spec.ts, this suite is OFF by default and self-skips
 * unless the stack is reachable and a large .zevtc path is provided.
 */
import { existsSync, mkdirSync, statSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { bypassNextJsProxyForLargeUploads } from "./helpers/proxy";

const STACK_URL = process.env.E2E_STACK_URL ?? "http://localhost:3000";
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";
const SHOTS = process.env.E2E_SCREENSHOT_DIR ?? "./playwright-e2e-screenshots";
const LARGE = process.env.E2E_ZEVTC_LARGE_PATH ?? "";

async function stackReachable(): Promise<boolean> {
  try {
    await fetch(STACK_URL, { signal: AbortSignal.timeout(5_000) });
    return true;
  } catch {
    return false;
  }
}

test("large .zevtc upload bypasses Next.js 10 MB proxy limit", async ({ page }) => {
  test.setTimeout(300_000);

  test.skip(
    !LARGE || !existsSync(LARGE),
    "E2E_ZEVTC_LARGE_PATH unset or missing — large-upload test skipped",
  );
  test.skip(
    !(await stackReachable()),
    `stack not reachable at ${STACK_URL} — boot the full stack first`,
  );

  const sizeBytes = statSync(LARGE).size;
  test.skip(
    sizeBytes <= 10 * 1024 * 1024,
    `E2E_ZEVTC_LARGE_PATH is only ${sizeBytes} bytes — need >10 MiB to exercise the proxy bypass`,
  );

  mkdirSync(SHOTS, { recursive: true });

  // Intercept the upload POST and forward it directly to FastAPI,
  // bypassing Next.js dev server's 10 MB rewrite body limit.
  await bypassNextJsProxyForLargeUploads(page, API_URL);

  await page.goto("/upload", { waitUntil: "domcontentloaded" });
  await page.setInputFiles('[data-testid="file-input"]', LARGE);
  await page.waitForTimeout(500);
  await page.click('[data-testid="next"]');

  // Wait for a terminal state: done, timeout, or error.
  await page.waitForSelector(
    '[data-testid="step-done"], [data-testid="poll-timeout"], [data-testid="error"], [data-testid="poll-error"]',
    { timeout: 120_000 },
  );

  const done = await page.locator('[data-testid="step-done"]').count();
  expect.soft(done, "large upload should reach the done state").toBeGreaterThan(0);

  // The wizard can reach "done" even when the backend parse failed.
  // Wait for a terminal status (completed or failed) before asserting.
  const statusLocator = page
    .locator('[data-testid="step-done"] dd')
    .filter({ hasText: /^(completed|failed)$/i });
  await statusLocator.waitFor({ timeout: 120_000 }).catch(() => {});

  const statusTexts = await page.locator('[data-testid="step-done"] dd').allTextContents();
  const statusText = statusTexts.find((t) => /^(completed|failed)$/i.test(t.trim())) ?? "";
  expect.soft(statusText.trim(), "large upload should parse successfully").toBe("completed");

  const href = await page
    .locator('[data-testid="step-done"] a[href^="/fights/"]')
    .first()
    .getAttribute("href")
    .catch(() => null);
  expect.soft(href, "large upload should produce a fight detail link").toBeTruthy();

  await page.screenshot({ path: `${SHOTS}/large-upload-bypass-done.png`, fullPage: true });
});
