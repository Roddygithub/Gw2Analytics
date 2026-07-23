/**
 * Playwright E2E: upload wizard with different file sizes (real .zevtc).
 *
 * Tests the upload wizard's client-side pipeline with real WvW .zevtc
 * files of different sizes:
 *   - 143 B   sample.zevtc (tiny synthetic)
 *   - 5 KB    20251116-224830.zevtc (real tiny WvW log, 2 agents)
 *   - 28 KB   20250928-230925.zevtc (real small WvW fight)
 *   - 657 KB  20251206-003232.zevtc (real large WvW fight)
 *
 * All files have the .zevtc extension, so the client-side guard
 * (.toLowerCase().endsWith('.zevtc')) accepts them natively.
 * The mock server returns a deterministic stub regardless of content,
 * so this tests the client-side UI pipeline, not the server parse.
 */
import { test, expect } from "@playwright/test";
import { join } from "node:path";

const PUBLIC_DIR = join(process.cwd(), "public");
// Repo-resident fixtures shipped under web/tests/e2e/fixtures/
// (the 3 WvW .zevtc files were moved out of the developer's
// local directory so the spec ships REAL coverage on CI,
// not a no-op skip).
const FIXTURES_DIR = join(process.cwd(), "tests", "e2e", "fixtures");

interface FileSpec {
  path: string;
  expectedLabel: string;
  description: string;
}

const FILES: FileSpec[] = [
  {
    path: join(PUBLIC_DIR, "sample.zevtc"),
    expectedLabel: "sample.zevtc",
    description: "143 B tiny synthetic",
  },
  {
    path: join(FIXTURES_DIR, "wvw-tiny-2agents.zevtc"),
    expectedLabel: "wvw-tiny-2agents.zevtc",
    description: "5 KB real tiny (2 agents)",
  },
  {
    path: join(FIXTURES_DIR, "wvw-small-fight.zevtc"),
    expectedLabel: "wvw-small-fight.zevtc",
    description: "28 KB real small fight",
  },
  {
    path: join(FIXTURES_DIR, "wvw-large-fight.zevtc"),
    expectedLabel: "wvw-large-fight.zevtc",
    description: "657 KB real large fight",
  },
];

test.describe("upload multi-size", () => {
  test("uploads files of 4 different sizes successfully", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));

    for (const fileSpec of FILES) {
      await test.step(`upload ${fileSpec.description}`, async () => {
        await page.goto("/upload");
        await expect(
          page.getByRole("heading", { name: /upload.*zevtc/i }),
        ).toBeVisible();

        // Select the file (all files have .zevtc extension natively)
        const fileInput = page.getByTestId("file-input");
        await fileInput.setInputFiles(fileSpec.path);

        // Verify the file chip shows the filename
        await expect(page.getByTestId("file-chip")).toContainText(
          fileSpec.expectedLabel,
        );

        // Next button should be enabled
        await expect(page.getByTestId("next")).toBeEnabled();

        // Click Next to advance to upload step
        await page.getByTestId("next").click();

        // The wizard shows the uploading step (the mock server responds fast)
        await expect(page.getByTestId("step-upload")).toBeVisible({
          timeout: 5_000,
        });

        // Wait for completion (mock server returns completed instantly)
        await expect(page.getByTestId("step-done")).toBeVisible({
          timeout: 10_000,
        });

        // Verify fight link is present
        const fightLink = page.getByRole("link", { name: /fights\// });
        await expect(fightLink).toBeVisible();
      });
    }

    // No uncaught errors across all uploads
    expect(pageErrors).toEqual([]);
  });
});
