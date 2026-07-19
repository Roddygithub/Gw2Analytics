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
import { statSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { parseLargeZevtcPaths } from "./helpers/env";
import { safeFileLabel } from "./helpers/string";

const STACK_URL = process.env.E2E_STACK_URL ?? "http://localhost:3000";
const LARGE_PATHS = parseLargeZevtcPaths();

async function stackReachable(): Promise<boolean> {
  try {
    await fetch(STACK_URL, { signal: AbortSignal.timeout(5_000) });
    return true;
  } catch {
    return false;
  }
}

for (const filePath of LARGE_PATHS) {
  const fileLabel = safeFileLabel(filePath);

  test(`large .zevtc upload fails without the Next.js proxy bypass: ${fileLabel}`, async ({ page }) => {
    test.setTimeout(120_000);

    test.skip(
      !(await stackReachable()),
      `stack not reachable at ${STACK_URL} — proxy-limit test skipped`,
    );

    const sizeBytes = statSync(filePath).size;
    test.skip(
      sizeBytes <= 10 * 1024 * 1024,
      `${fileLabel} is only ${sizeBytes} bytes — need >10 MiB to exercise the proxy limit`,
    );

    await page.goto("/upload", { waitUntil: "domcontentloaded" });
    await page.setInputFiles('[data-testid="file-input"]', filePath);
    await page.waitForTimeout(500);
    await page.click('[data-testid="next"]');

    // Without the bypass, the request should fail before the wizard can
    // reach the parse/done state. Race a visible error banner against a
    // failed network request so the test does not hang on transient states.
    const failedRequestPromise = page.waitForEvent("requestfailed", { timeout: 60_000 });
    const visibleErrorPromise = page.waitForSelector(
      '[data-testid="error"], [data-testid="poll-error"], [data-testid="poll-timeout"]',
      { timeout: 60_000 },
    );
    const failedRequest = await Promise.race([
      failedRequestPromise.then((req) => req),
      visibleErrorPromise.then(() => null),
    ]);

    const errorText =
      (await page.locator('[data-testid="error"]').textContent().catch(() => null)) ?? "";
    const pollErrorText =
      (await page.locator('[data-testid="poll-error"]').textContent().catch(() => null)) ?? "";
    const hasVisibleError = errorText.length > 0 || pollErrorText.length > 0;
    const failedRequestInfo = failedRequest
      ? `${failedRequest.method()} ${failedRequest.url()}: ${failedRequest.failure()?.errorText ?? "unknown"}`
      : "";
    const hasFailedRequest = failedRequestInfo.includes("/api/v1/uploads");

    test.info().annotations.push({
      type: "proxy-limit-debug",
      description: `visible="${errorText || pollErrorText}", failed="${failedRequestInfo}"`,
    });

    expect.soft(
      hasVisibleError || hasFailedRequest,
      "upload should surface an error without the proxy bypass",
    ).toBeTruthy();
  });
}
