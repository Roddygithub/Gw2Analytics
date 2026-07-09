// Throwaway verification: drive the 3-step upload wizard
// against the live dev stack and capture one screenshot per
// step + the terminal done panel. NOT committed; same
// convention as _verify_tz_selector.mjs.
import { chromium } from "@playwright/test";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const consoleErrors = [];
page.on("pageerror", (err) => consoleErrors.push("PAGEERROR: " + err.message));
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push("CONSOLE: " + msg.text()); });

try {
  await page.goto("http://127.0.0.1:3000/upload", { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);

  // Step 1: pick.
  const pickPanel = await page.$('[data-testid="step-pick"]');
  console.log("STEP_PICK_FOUND", pickPanel ? "YES" : "NO");
  await page.screenshot({ path: "/tmp/wizard_pick.png", fullPage: true });

  // Force a real file into the <input type="file">. We use the
  // seed_demo synthetic .zevtc bytes if present, otherwise we
  // ship an inline minimal payload.
  const filePath = "/tmp/seed_demo.zevtc";
  await page.setInputFiles('[data-testid="file-input"]', filePath);
  await page.waitForTimeout(400);
  await page.screenshot({ path: "/tmp/wizard_pick_filled.png", fullPage: true });

  // Advance to step 2 (upload-in-flight). The wizard dispatches
  // POST + transitions to upload -> parse -> done.
  await page.click('[data-testid="next"]');
  // The upload step is fast; capture immediately, then capture
  // the parse step ~500ms later.
  await page.waitForTimeout(150);
  try { await page.screenshot({ path: "/tmp/wizard_upload.png", fullPage: true }); } catch (_) {}
  await page.waitForTimeout(900);
  const parsePanel = await page.$('[data-testid="step-parse"]');
  console.log("STEP_PARSE_FOUND", parsePanel ? "YES" : "NO");
  await page.screenshot({ path: "/tmp/wizard_parse.png", fullPage: true });

  // Wait up to ~8s for the poll to resolve done (the seed_demo
  // parser typically completes in <2s once the BackgroundTask
  // is scheduled).
  let done = null;
  for (let i = 0; i < 8; i += 1) {
    done = await page.$('[data-testid="step-done"]');
    if (done !== null) break;
    await page.waitForTimeout(1000);
  }
  console.log("STEP_DONE_FOUND", done ? "YES" : "NO");
  if (done !== null) {
    await page.screenshot({ path: "/tmp/wizard_done.png", fullPage: true });
  }

  console.log("CONSOLE_ERRORS", JSON.stringify(consoleErrors));
} catch (err) {
  console.log("FAILED", err.message);
  await page.screenshot({ path: "/tmp/wizard_failure.png", fullPage: true });
} finally {
  await browser.close();
}
