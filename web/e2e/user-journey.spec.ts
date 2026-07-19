/**
 * Full real-backend E2E user journey (no mocks).
 *
 * Drives a real user flow against a LIVE stack (Next.js -> FastAPI ->
 * Postgres + MinIO) using real .zevtc files. Captures a screenshot at
 * every step, records console errors + pageerrors + >=400 network
 * responses, and writes them to E2E_SCREENSHOT_DIR.
 *
 * This suite is OFF by default: it self-skips unless the stack is
 * reachable AND at least the small .zevtc path is provided via env.
 * See web/e2e/README.md for the full setup + env vars.
 *
 * Env vars (all optional; sensible localhost defaults):
 *   E2E_STACK_URL          default http://localhost:3000  (Next.js dev)
 *   E2E_API_URL            default http://localhost:8000  (FastAPI)
 *   E2E_ZEVTC_SMALL_PATH   real small .zevtc (required, else skip)
 *   E2E_ZEVTC_MEDIUM_PATH  optional medium .zevtc (step skipped if unset)
 *   E2E_ZEVTC_LARGE_PATH   optional >100MiB .zevtc for the cap test
 *   E2E_SCREENSHOT_DIR     default ./playwright-e2e-screenshots
 *
 * Assertions are intentionally SOFT (expect.soft) so one hiccup never
 * aborts the journey — the deliverable is the screenshot set + the
 * captured error log for visual review.
 */
import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { bypassNextJsProxyForLargeUploads } from "./helpers/proxy";

const STACK_URL = process.env.E2E_STACK_URL ?? "http://localhost:3000";
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";
const SHOTS = process.env.E2E_SCREENSHOT_DIR ?? "./playwright-e2e-screenshots";
const SMALL = process.env.E2E_ZEVTC_SMALL_PATH ?? "";
const MEDIUM = process.env.E2E_ZEVTC_MEDIUM_PATH ?? "";
const LARGE = process.env.E2E_ZEVTC_LARGE_PATH ?? "";
const GW2_API_KEY = process.env.E2E_GW2_API_KEY ?? "";

type Diag = { console: string[]; pageerrors: string[]; http4xx5xx: string[] };

async function stackReachable(): Promise<boolean> {
  try {
    await fetch(STACK_URL, { signal: AbortSignal.timeout(5_000) });
    return true;
  } catch {
    return false;
  }
}

test.describe.configure({ mode: "serial" });

test("full user journey (small + medium + large .zevtc)", async ({ page }) => {
  test.setTimeout(300_000);

  // --- Preconditions: skip cleanly if the stack or the small fixture
  //     is unavailable (so CI / a laptop without the stack stays green).
  test.skip(
    !SMALL || !existsSync(SMALL),
    "E2E_ZEVTC_SMALL_PATH unset or missing — real-stack journey skipped (see web/e2e/README.md)",
  );
  test.skip(
    !(await stackReachable()),
    `stack not reachable at ${STACK_URL} — boot the full stack first (see web/e2e/README.md)`,
  );

  mkdirSync(SHOTS, { recursive: true });
  const diag: Diag = { console: [], pageerrors: [], http4xx5xx: [] };

  page.on("console", (m) => {
    if (m.type() === "error") diag.console.push(`[console.error] ${m.text()}`);
  });
  page.on("pageerror", (e) => diag.pageerrors.push(`[pageerror] ${e.message}`));
  page.on("response", (r) => {
    const s = r.status();
    if (s >= 400) diag.http4xx5xx.push(`${s} ${r.request().method()} ${r.url()}`);
  });

  const shot = async (name: string) => {
    const path = `${SHOTS}/${name}.png`;
    await page.screenshot({ path, fullPage: true }).catch(() => {});
    // Lightweight render check: the screenshot must exist and be non-empty.
    const size = existsSync(path) ? statSync(path).size : 0;
    expect.soft(size, `screenshot ${name}.png should be non-empty`).toBeGreaterThan(0);
  };

  // Upload a file through the wizard; returns fight id (or null if the
  // client rejected the file, e.g. the >100 MiB cap).
  const uploadThrough = async (
    filePath: string,
    prefix: string,
  ): Promise<{ fightId: string | null; rejected: string | null }> => {
    await page.goto("/upload", { waitUntil: "domcontentloaded" });
    await shot(`${prefix}-upload-pick`);
    await page.setInputFiles('[data-testid="file-input"]', filePath);
    await page.waitForTimeout(500);
    const rejected = await page
      .locator('[data-testid="rejected"]')
      .textContent()
      .catch(() => null);
    if (rejected) {
      await shot(`${prefix}-upload-rejected`);
      return { fightId: null, rejected };
    }
    await shot(`${prefix}-upload-ready`);
    await page.click('[data-testid="next"]');
    await page.waitForSelector('[data-testid="step-parse"]', { timeout: 5_000 }).catch(() => {});
    await shot(`${prefix}-upload-progress`);
    await page.waitForSelector(
      '[data-testid="step-done"], [data-testid="poll-timeout"], [data-testid="error"], [data-testid="poll-error"]',
      { timeout: 120_000 },
    );
    await shot(`${prefix}-upload-done`);
    const href = await page
      .locator('[data-testid="step-done"] a[href^="/fights/"]')
      .first()
      .getAttribute("href")
      .catch(() => null);
    return { fightId: href ? (href.split("/").pop() ?? null) : null, rejected: null };
  };

  const browseFightDetail = async (fightId: string, prefix: string) => {
    await page.goto(`/fights/${fightId}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot(`${prefix}-fight-overview`);
    const sections: [string, RegExp][] = [
      ["events", /event/i],
      ["timeline", /timeline/i],
      ["skills", /skill/i],
      ["per-target", /target|dps|damage|healing|strip/i],
      ["per-squad", /squad|subgroup/i],
    ];
    for (const [name, re] of sections) {
      try {
        const h = page.getByRole("heading", { name: re }).first();
        if (await h.count()) {
          await h.scrollIntoViewIfNeeded();
          await page.waitForTimeout(300);
        }
        await page.screenshot({ path: `${SHOTS}/${prefix}-${name}.png`, fullPage: false });
      } catch {
        /* section absent (e.g. error page) — captured in diag */
      }
    }
  };

  await test.step("01 landing", async () => {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await shot("01-landing");
    await expect.soft(page.getByRole("heading", { name: /GW2Analytics/i })).toBeVisible();
  });

  let smallFight: string | null = null;
  await test.step("SMALL upload + parse", async () => {
    const r = await uploadThrough(SMALL, "02-small");
    smallFight = r.fightId;
    expect.soft(r.rejected, "small should not be client-rejected").toBeNull();
  });

  await test.step("05 fights list", async () => {
    await page.goto("/fights", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot("05-fights-list");
    expect.soft(await page.locator('a[href^="/fights/"]').count()).toBeGreaterThan(0);
  });

  await test.step("06-11 fight detail sections", async () => {
    if (!smallFight) {
      smallFight =
        (await page.locator('a[href^="/fights/"]').first().getAttribute("href"))
          ?.split("/")
          .pop() ?? null;
    }
    if (smallFight) await browseFightDetail(smallFight, "06-small");
  });

  await test.step("12 player detail", async () => {
    await page.goto("/players", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot("12a-players-list");
    const playerLink = page.locator('a[href^="/players/"]').first();
    if (await playerLink.count()) {
      await playerLink.click();
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(1500);
      await shot("12b-player-detail");
    }
  });

  await test.step("20 medium upload + browse", async () => {
    if (!MEDIUM || !existsSync(MEDIUM)) {
      test.info().annotations.push({ type: "skip-step", description: "no medium .zevtc" });
      return;
    }
    const r = await uploadThrough(MEDIUM, "20-medium");
    if (r.fightId) await browseFightDetail(r.fightId, "20-medium");
  });

  await test.step("30 large upload + browse", async () => {
    if (!LARGE || !existsSync(LARGE)) {
      test.info().annotations.push({ type: "skip-step", description: "no large .zevtc" });
      return;
    }
    await bypassNextJsProxyForLargeUploads(page, API_URL);
    const r = await uploadThrough(LARGE, "30-large");
    expect.soft(r.rejected, "large should not be client-rejected").toBeNull();
    expect.soft(r.fightId, "large upload should produce a fight id").toBeTruthy();
    if (r.fightId) await browseFightDetail(r.fightId, "30-large");
  });

  await test.step("31 account / API key", async () => {
    await page.goto("/account", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot("31-account-form");
    await expect.soft(page.getByRole("heading", { name: /Resolve GW2 API key/i })).toBeVisible();
    const input = page.locator('input[type="password"]').first();
    const btn = page.getByRole("button", { name: /Resolve/ }).first();
    if ((await input.count()) > 0 && (await btn.count()) > 0) {
      await input.fill(GW2_API_KEY || "test-api-key-12345");
      await btn.click();
      // Wait for the resolved result or an error banner to appear.
      await page
        .locator("text=/Resolved world/i")
        .or(page.locator("text=/Error:/i"))
        .waitFor({ timeout: 10_000 })
        .catch(() => {});
      await shot("31-account-resolved");
      const body = (await page.locator("body").textContent()) ?? "";
      const hasResolved = body.includes("Resolved world") || body.includes("resolved world");
      // The page shows "Error: <status>" for invalid/rejected keys.
      const hasError = body.includes("Error:");
      if (GW2_API_KEY) {
        expect.soft(
          hasResolved || hasError,
          "account page should resolve the provided real GW2 API key or show an error",
        ).toBeTruthy();
      } else {
        expect.soft(
          hasResolved || hasError,
          "account page shows resolved state or error feedback",
        ).toBeTruthy();
      }
    }
  });

  await test.step("32 players compare", async () => {
    await page.goto("/players/compare", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot("32-players-compare");
    await expect.soft(page.getByRole("heading", { name: /Compare accounts/i })).toBeVisible();
  });

  await test.step("33 webhooks", async () => {
    await page.goto("/webhooks", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
    await shot("33-webhooks");
    await expect.soft(page.getByRole("heading", { name: /Webhook/i })).toBeVisible();
  });

  writeFileSync(`${SHOTS}/_diagnostics.json`, JSON.stringify(diag, null, 2));
});
