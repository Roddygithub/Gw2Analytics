#!/usr/bin/env node
/**
 * Take full-page PNG screenshots of every GW2Analytics route
 * via the local dev server (Next.js 16 on :3000 + mock server
 * on :8080). Saves the PNGs to ./screenshots/ at the project
 * root.
 *
 * Usage:
 *   node web/scripts/screenshots.mjs
 *
 * Requirements:
 *   - The mock server (port 8080) and `pnpm dev` (port 3000)
 *     are both up and responding 200 on /api/v1/fights and /
 *     respectively. The script does NOT start them; it just
 *     consumes the running stack.
 *   - The Playwright chromium browser is already installed
 *     (`pnpm exec playwright install chromium` is part of the
 *     project's E2E setup).
 */
// Import via ``@playwright/test`` (the project's installed
// dev dependency) instead of ``playwright`` directly: in a pnpm
// workspace, ``playwright`` lives in the store but is not
// hoisted into ``web/node_modules/``; only ``@playwright/test``
// is. Both packages re-export ``chromium`` so the API is
// identical.
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

// Anchor OUT_DIR to the repo root *from the script's
// own location*, not from the caller's CWD. This way
// ``node web/scripts/screenshots.mjs`` from the repo
// root AND ``pnpm screenshots`` from inside ``web/`` both
// write to the same ``/screenshots/`` directory at the
// repo root -- never to the legacy ``web/screenshots/``
// dir that the round-148 chore commit told everyone to
// stop writing to.
// Uses ``import.meta.dirname`` (Node 20.11+, safely
// supported since Next.js 16 mandates Node 20+).
const OUT_DIR = resolve(import.meta.dirname, "..", "..", "screenshots");
const BASE = "http://127.0.0.1:3000";

// (label, path, wait-selector?, extra-pre-screenshot-delay-ms)
const PAGES = [
  ["01-landing",                       "/",                                        null,   300],
  ["02-account",                       "/account",                                 null,   200],
  ["03-upload",                        "/upload",                                  null,   200],
  ["04-fights",                        "/fights",                                  ".ag-root", 1200],
  ["05-players",                       "/players",                                 ".ag-root", 1200],
  ["06-player-profile-with-timeline", "/players/TestAccount.1234",                "svg[aria-label='Per-account historical timeline']", 800],
  ["07-player-empty-timeline",         "/players/empty-history.5678",              null,   500],
  ["08-fight-drilldown",               "/fights/fixture-fight-001",                "svg[aria-label='Per-bucket event damage and healing']", 800],
];

await mkdir(OUT_DIR, { recursive: true });

const browser = await chromium.launch({ headless: true });
try {
  // Desktop Chrome viewport: 1440x900, like the Playwright E2E
  // Desktop Chrome device profile.
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  page.on("pageerror", (err) => console.log(`[pageerror] ${err.message}`));

  for (const [label, route, waitFor, extraDelay] of PAGES) {
    const url = `${BASE}${route}`;
    process.stdout.write(`  -> ${label} (${url}) ... `);
    try {
      const resp = await page.goto(url, {
        waitUntil: "domcontentloaded",
        timeout: 30000,
      });
      try {
        await page.waitForLoadState("networkidle", { timeout: 15000 });
      } catch (_) {
        // Best-effort; some pages never reach networkidle.
      }
      if (waitFor) {
        try {
          await page.waitForSelector(waitFor, { timeout: 10000 });
        } catch (_) {
          console.log(`(selector '${waitFor}' missing)`);
        }
      }
      if (extraDelay) {
        await page.waitForTimeout(extraDelay);
      }
      const outPath = resolve(OUT_DIR, `${label}.png`);
      await page.screenshot({ path: outPath, fullPage: true });
      const status = resp ? resp.status() : "?";
      console.log(`OK (HTTP ${status} -> ${outPath})`);
    } catch (err) {
      console.log(`FAILED: ${err.message}`);
    }
  }
} finally {
  await browser.close();
}

console.log(`\nScreenshots written to ${OUT_DIR}`);
