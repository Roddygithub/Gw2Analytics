/**
 * Real-stack negative test for the Next.js dev proxy body limit.
 *
 * Next.js dev server's rewrite/proxy rejects request bodies larger than
 * 10 MB. Uploading a .zevtc larger than 10 MB WITHOUT the Playwright
 * bypass should therefore fail (network error or 500). This test proves
 * the bypass is actually necessary and not a no-op.
 *
 * Like the other real-stack specs, it is OFF by default and self-skips
 * unless the stack is reachable and a large .zevtc path is provided.
 */
import { existsSync, statSync } from "node:fs";

import { expect, test } from "@playwright/test";

const STACK_URL = process.env.E2E_STACK_URL ?? "http://localhost:3000";
const LARGE = process.env.E2E_ZEVTC_LARGE_PATH ?? "";

async function stackReachable(): Promise<boolean> {
  try {
    await fetch(STACK_URL, { signal: AbortSignal.timeout(5_000) });
    return true;
  } catch {
    return false;
  }
}

test("large .zevtc upload fails without the Next.js proxy bypass", async ({ page }) => {
  test.setTimeout(120_000);

  test.skip(
    !LARGE || !existsSync(LARGE),
    "E2E_ZEVTC_LARGE_PATH unset or missing — proxy-limit test skipped",
  );
  test.skip(
    !(await stackReachable()),
    `stack not reachable at ${STACK_URL} — proxy-limit test skipped`,
  );

  const sizeBytes = statSync(LARGE).size;
  test.skip(
    sizeBytes <= 10 * 1024 * 1024,
    `E2E_ZEVTC_LARGE_PATH is only ${sizeBytes} bytes — need >10 MiB to exercise the proxy limit`,
  );

  // Capture any failed network request (e.g. ECONNRESET from the proxy).
  const failedRequests: string[] = [];
  const onRequestFailed = (req: import("@playwright/test").Request) => {
    failedRequests.push(`${req.method()} ${req.url()}: ${req.failure()?.errorText ?? "unknown"}`);
  };
  page.once("requestfailed", onRequestFailed);

  await page.goto("/upload", { waitUntil: "domcontentloaded" });
  await page.setInputFiles('[data-testid="file-input"]', LARGE);
  await page.waitForTimeout(500);
  await page.click('[data-testid="next"]');

  // Without the bypass, the request should fail before the wizard can
  // reach the parse/done state. Race a visible error banner against a
  // failed network request so the test does not hang on transient states.
  await Promise.race([
    page.waitForSelector(
      '[data-testid="error"], [data-testid="poll-error"], [data-testid="poll-timeout"]',
      { timeout: 60_000 },
    ),
    page.waitForEvent("requestfailed", { timeout: 60_000 }),
  ]);

  const errorText = (await page.locator('[data-testid="error"]').textContent().catch(() => null)) ?? "";
  const pollErrorText = (await page.locator('[data-testid="poll-error"]').textContent().catch(() => null)) ?? "";
  const hasVisibleError = errorText.length > 0 || pollErrorText.length > 0;
  const hasFailedRequest = failedRequests.some((r) => r.includes("/api/v1/uploads"));

  test.info().annotations.push({
    type: "proxy-limit-debug",
    description: `visible="${errorText || pollErrorText}", failed=${JSON.stringify(failedRequests)}`,
  });

  expect.soft(
    hasVisibleError || hasFailedRequest,
    "upload should surface an error without the proxy bypass",
  ).toBeTruthy();
});
