/**
 * Playwright E2E for the v0.5.0-web /upload page.
 *
 * The /upload page is a Client Component that posts a
 * ``.zevtc`` combat log as ``multipart/form-data`` to
 * ``/api/v1/uploads``. The E2E proves:
 *   1. The form renders correctly (heading + file input +
 *      disabled submit button).
 *   2. Client-side validation catches bad extensions and
 *      oversized files before any network call.
 *   3. Server-side errors (500 from the upload POST, poll
 *      failures, poll timeouts) surface as visible error
 *      banners so the analyst always knows what happened.
 */
import { test, expect } from "@playwright/test";
import { openSync, writeSync, closeSync, unlinkSync } from "node:fs";
import { join } from "node:path";

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

    // Submit button (the page uses ``data-testid="next"``
    // on the Pick step; disabled by default because no file
    // is selected)
    await expect(page.getByTestId("next")).toBeAttached();
    await expect(page.getByTestId("next")).toBeDisabled();

    // No uncaught exceptions during page load. (We use
    // ``pageerror`` rather than ``console.error`` because the
    // latter also fires on dev-mode React hydration warnings,
    // which are benign and would false-positive the check.)
    expect(pageErrors).toEqual([]);
  });
});

test.describe("/upload error cases", () => {
  test("rejects non-.zevtc file extension", async ({ page }) => {
    await page.goto("/upload");

    // Upload a .txt file -- the client-side extension guard
    // should reject it before any network call.
    const fileInput = page.getByTestId("file-input");
    await fileInput.setInputFiles({
      name: "report.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("not a combat log"),
    });

    // Rejection message is visible and Next is disabled.
    await expect(page.getByTestId("rejected")).toBeVisible();
    await expect(page.getByTestId("rejected")).toHaveText(
      "Only .zevtc files are accepted.",
    );
    await expect(page.getByTestId("next")).toBeDisabled();
  });

  test("accepts .ZEVTC uppercase extension (case-insensitive guard)", async ({
    page,
  }) => {
    await page.goto("/upload");

    const fileInput = page.getByTestId("file-input");
    await fileInput.setInputFiles({
      name: "combat.ZEVTC",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("EVTC"),
    });

    // .ZEVTC (uppercase) should be accepted -- the guard
    // uses .toLowerCase(). The Next button should be ENABLED.
    await expect(page.getByTestId("rejected")).toHaveCount(0);
    await expect(page.getByTestId("next")).toBeEnabled();
  });

  test("rejects file exceeding 100 MiB client-side cap", async ({
    page,
  }) => {
    // Playwright's setInputFiles rejects buffers >50 MiB, so we
    // write a sparse file to disk and pass the path instead.
    // The file is sparse (only the first byte is allocated) so
    // it takes negligible disk space while reporting the correct
    // file.size to the browser's File API.
    const filePath = join(
      process.cwd(),
      "tests",
      "e2e",
      "fixtures",
      `huge-sparse-${Date.now()}.zevtc`,
    );

    // Create a file with a sparse hole: write 1 byte at offset
    // 100*1024*1024. The OS reports size_bytes=100*1024*1024+1
    // but only allocates 1 disk block for the data.
    const fd = openSync(filePath, "w");
    writeSync(fd, Buffer.from([0xff]), 0, 1, 100 * 1024 * 1024);
    closeSync(fd);

    try {
      await page.goto("/upload");

      const fileInput = page.getByTestId("file-input");
      await fileInput.setInputFiles(filePath);

      await expect(page.getByTestId("rejected")).toBeVisible();
      await expect(page.getByTestId("rejected")).toContainText("too large");
      await expect(page.getByTestId("next")).toBeDisabled();
    } finally {
      // Cleanup the sparse file even if assertions fail.
      try {
        unlinkSync(filePath);
      } catch {
        /* already gone */
      }
    }
  });

  test("shows error banner when upload POST returns 500", async ({ page }) => {
    // Intercept the upload POST and return a server error.
    await page.route("**/api/v1/uploads", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: "internal server error" }),
        });
      }
      return route.continue();
    });

    await page.goto("/upload");

    const fileInput = page.getByTestId("file-input");
    await fileInput.setInputFiles({
      name: "fight.zevtc",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("EVTC"),
    });
    await page.getByTestId("next").click();

    // The wizard stays on the upload step and shows the error.
    await expect(page.getByTestId("step-upload")).toBeVisible();
    await expect(page.getByTestId("error")).toBeVisible();
    await expect(page.getByTestId("error")).toContainText("500");
  });

  test("shows poll error when upload status GET returns 500", async ({
    page,
  }) => {
    // POST succeeds with a dummy envelope.
    await page.route("**/api/v1/uploads", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "error-test-001",
            sha256: "a".repeat(64),
            status: "pending",
          }),
        });
      }
      return route.continue();
    });

    // GET polling fails.
    await page.route("**/api/v1/uploads/error-test-001", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: "poll failed" }),
        });
      }
      return route.continue();
    });

    await page.goto("/upload");

    const fileInput = page.getByTestId("file-input");
    await fileInput.setInputFiles({
      name: "fight.zevtc",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("EVTC"),
    });
    await page.getByTestId("next").click();

    // The wizard transitions to parse, then surfaces the poll error.
    await expect(page.getByTestId("step-parse")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("poll-error")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("shows timeout banner when poll never resolves", async ({ page }) => {
    // NOTE: This test takes ~32s (15 polls × 2s interval + buffer).
    // The vitest unit tests cover the timeout path with mocked
    // timers; this E2E test validates the real timer behaviour.
    test.setTimeout(45_000);

    // POST succeeds.
    await page.route("**/api/v1/uploads", (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "timeout-test-001",
            sha256: "b".repeat(64),
            status: "pending",
          }),
        });
      }
      return route.continue();
    });

    // GET always returns "pending" -- the poll will never resolve.
    await page.route("**/api/v1/uploads/timeout-test-001", (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "timeout-test-001",
            sha256: "b".repeat(64),
            status: "pending",
          }),
        });
      }
      return route.continue();
    });

    await page.goto("/upload");

    const fileInput = page.getByTestId("file-input");
    await fileInput.setInputFiles({
      name: "fight.zevtc",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("EVTC"),
    });
    await page.getByTestId("next").click();

    // Wait for the parse step to appear.
    await expect(page.getByTestId("step-parse")).toBeVisible({
      timeout: 10_000,
    });

    // The wizard polls 15 times at 2s intervals = 30s total.
    // Wait for the timeout banner (with generous buffer).
    await expect(page.getByTestId("poll-timeout")).toBeVisible({
      timeout: 40_000,
    });
    await expect(page.getByTestId("poll-timeout")).toContainText(
      "Still parsing",
    );
  });
});
