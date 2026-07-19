import type { Page } from "@playwright/test";

/**
 * Bypass the Next.js dev server 10 MB request body limit for uploads.
 *
 * Next.js dev server's rewrite/proxy enforces a hard 10 MB limit on
 * request bodies. Uploading a .zevtc larger than 10 MB through the
 * frontend therefore fails with ECONNRESET/500. This helper intercepts
 * `POST /api/v1/uploads` in Playwright and continues the request
 * directly to the FastAPI backend, preserving the multipart body and
 * headers.
 *
 * @param page Playwright page object
 * @param apiUrl FastAPI base URL (e.g. http://localhost:8000)
 */
export async function bypassNextJsProxyForLargeUploads(
  page: Page,
  apiUrl: string,
): Promise<void> {
  await page.route("/api/v1/uploads", async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }

    // Continue the request to the backend URL. Playwright preserves the
    // original method, headers, and multipart body, so the upload lands
    // on FastAPI without being buffered/rejected by Next.js dev server.
    await route.continue({
      url: `${apiUrl}/api/v1/uploads`,
    });
  });
}
