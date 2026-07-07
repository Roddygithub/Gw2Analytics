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
  ["01-landing",                       "/",                                        null,     0],
  ["02-account",                       "/account",                                 null,     0],
  ["03-upload",                        "/upload",                                  null,     0],
  ["04-fights",                        "/fights",                                  null,     0],
  ["05-players",                       "/players",                                 null,     0],
  ["06-player-profile-with-timeline", "/players/TestAccount.1234",                null,     0],
  ["07-player-empty-timeline",         "/players/empty-history.5678",              null,     0],
  ["08-fight-drilldown",               "/fights/fixture-fight-001",                null,     0],
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
      // Match the visual-regression spec's wait strategy exactly:
      // ``waitUntil: "networkidle"`` + immediate ``page.screenshot()``.
      // The spec (``web/tests/e2e/visual-regression.spec.ts``) uses
      // this same pattern and captures the dynamic pages at ~3196px
      // (the AG Grid / SVG charts are mounted by the time
      // ``networkidle`` fires). The baselines therefore need to
      // match the spec's capture dimensions; any additional waits
      // (a separate ``waitForLoadState``, an ``extraDelay``, a
      // ``waitForFunction`` stability check) were causing the
      // script to capture a DIFFERENT state than the spec
      // (typically a 900px pre-hydration render) and producing
      // the 900px vs 3196px dimension mismatch the VR suite has
      // been flagging.
      const resp = await page.goto(url, {
        waitUntil: "networkidle",
        timeout: 30000,
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
