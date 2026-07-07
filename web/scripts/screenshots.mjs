#!/usr/bin/env node
/**
 * Take full-page PNG screenshots of every GW2Analytics route
 * via the local dev server (Next.js 16 on :3000 + mock server
 * on :8080). Saves the PNGs to ./screenshots/ at the project
 * root.
 *
 * Usage:
 *   node web/scripts/screenshots.mjs [--persist]
 *
 * Flags:
 *   --persist  Copy the 8 PNGs into ``docs/screenshots/`` at the
 *              repo root (the directory the README's "Screenshots"
 *              table reads from). Opt-in; without it, only the
 *              transient ``/screenshots/`` dir is populated
 *              (gitignored so casual runs don't clobber the
 *              committed README artifacts).
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
import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

// Anchor OUT_DIR to the repo root (the script's parent
// directory's parent). Invariant across CWD so neither
// ``node web/scripts/screenshots.mjs`` from the repo
// root nor ``cd web && pnpm screenshots`` accidentally
// lands in the legacy ``web/screenshots/`` dir that the
// round-148 chore commit told everyone to stop writing to.
// Requires Node 20.11+ for ``import.meta.dirname``
// (Next.js 16 mandates Node 20+, so we're safe).
const OUT_DIR = resolve(import.meta.dirname, "..", "..", "screenshots");

// ``--persist`` (read once at startup): mirror each PNG from the
// gitignored transient dir into the tracked ``docs/screenshots/``
// after the per-page loop, so the README's "Screenshots" section
// reads from a tracked directory. Default behavior stays
// unchanged -- transient ``/screenshots/`` only.
const PERSIST = process.argv.includes("--persist");
const DOCS_DIR = resolve(import.meta.dirname, "..", "..", "docs", "screenshots");
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
    // Wait for the page to be at its final, fully-hydrated height
    // before screenshotting. Without this, the screenshot may capture
    // a partially-rendered page (e.g. AG Grid still expanding after
    // the SSR data fetch settles) which would diff against the spec's
    // fully-hydrated capture (which only waits for ``networkidle``)
    // as a near-100% mismatch in the visual-regression spec.
    //
    // The wait has TWO requirements (both must be met):
    //   1. The page must have expanded beyond the viewport
    //      (``scrollHeight > 900``). Without this guard, the
    //      wait would happily return on a 900px-stable page
    //      that hasn't started its AG Grid / SVG chart
    //      expansion yet -- a 900px baseline that diffs as
    //      100% against the spec's 3196px capture.
    //   2. The height must be stable for 500ms (2 polls at
    //      250ms). The window-level closure variables +
    //      ``Date.now()`` handle the polling; the function
    //      is re-evaluated every 250ms.
    //
    // Each ``page.goto`` above is a full navigation so the
    // window object is reset between pages; the closure
    // variables do NOT persist across pages.
    //
    // The 30s timeout is the worst-case budget for an
    // aggressively-rendering dynamic page (e.g. the per-fight
    // timeline on /fights/[id] which inflates after the
    // squads + skills fetchers resolve).
    await page.waitForFunction(
      () => {
        const currentHeight = document.documentElement.scrollHeight;
        // Requirement 1: page must have expanded beyond the
        // 900px viewport. If the page is still at the
        // viewport height, the AG Grid / SVG charts have
        // not yet finished expanding; the wait returns
        // false (and resets the stability timer on the
        // next expansion tick).
        if (currentHeight <= 900) {
          window.__lastStableHeight = currentHeight;
          window.__lastStableTime = Date.now();
          return false;
        }
        // Requirement 2: height must be stable for 500ms.
        if (typeof window.__lastStableHeight === "undefined") {
          window.__lastStableHeight = currentHeight;
          window.__lastStableTime = Date.now();
          return false;
        }
        if (currentHeight !== window.__lastStableHeight) {
          window.__lastStableHeight = currentHeight;
          window.__lastStableTime = Date.now();
          return false;
        }
        return Date.now() - window.__lastStableTime >= 500;
      },
      null,
      { timeout: 30000, polling: 250 },
    ).catch(() => {
      // Best-effort. Pages with live-updating content (e.g. the
      // SVG timelines, which may re-render on viewport changes)
      // would time out here; the existing ``waitForLoadState`` +
      // selector wait + extra delay have already done what they
      // can, and the screenshot is the same as before this commit
      // (a possibly-partially-hydrated capture) -- so we proceed.
    });
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

// Persist pass: copy each PNG into docs/screenshots/ (idempotent).
if (PERSIST) {
  await mkdir(DOCS_DIR, { recursive: true });
  for (const [label] of PAGES) {
    const src = resolve(OUT_DIR, `${label}.png`);
    await copyFile(src, resolve(DOCS_DIR, `${label}.png`));
  }
  console.log(`\nScreenshots written to ${OUT_DIR}`);
  console.log(`+ copied (--persist) into ${DOCS_DIR}`);
} else {
  console.log(`\nScreenshots written to ${OUT_DIR}`);
  console.log(
    `(hint: pass --persist to also copy into docs/screenshots/ ` +
    `for README consumption)`,
  );
}
