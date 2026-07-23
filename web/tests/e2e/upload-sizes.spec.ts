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
import { existsSync } from "node:fs";
import { test, expect } from "@playwright/test";
import { join } from "node:path";

const PUBLIC_DIR = join(process.cwd(), "public");
const WVW_DIR = "/home/roddy/Projects/WvW/WvW (1)";

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
    path: join(WVW_DIR, "Ess Kape/20251116-224830.zevtc"),
    expectedLabel: "20251116-224830.zevtc",
    description: "5 KB real tiny (2 agents)",
  },
  {
    path: join(WVW_DIR, "Ess Kitable/20250928-230925.zevtc"),
    expectedLabel: "20250928-230925.zevtc",
    description: "28 KB real small fight",
  },
  {
    path: join(WVW_DIR, "Ber Zerk Er/20251206-003232.zevtc"),
    expectedLabel: "20251206-003232.zevtc",
    description: "657 KB real large fight",
  },
];

test.describe("upload multi-size", () => {
  test("uploads files of 4 different sizes successfully", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));

    // CI / clean laptops do NOT have the developer's local
    // ``/home/roddy/Projects/WvW/WvW (1)`` directory mounted.
    // The test is gated on at least one of the LOCAL_VWV_DIR
    // files being present; otherwise every step is skipped
    // (so the spec stays green on CI without losing local
    // coverage when the dev has the real .zevtc files).
    const presentFiles = FILES.filter((f) => existsSync(f.path));
    test.skip(
      presentFiles.length === 0,
      "no local .zevtc files available at ${WVW_DIR} -- skipping multi-size upload smoke test (see web/e2e/README.md)",
    );

    for (const fileSpec of presentFiles) {
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
