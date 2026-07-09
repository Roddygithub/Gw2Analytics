// Throwaway verification helper for the v0.9.0 TZ-selector
// component. NOT committed; lives in scripts/ so Node can
// resolve the local ``playwright`` package (running from
// /tmp/ fails because ESM resolves modules relative to
// the script's directory, not cwd).
//
// Usage: ``node web/scripts/_verify_tz_selector.mjs``
// Spawns a headless Chromium, navigates to a player
// profile (the empty-DB /players/test_account 404 path is
// fine -- the page renders an empty-state timeline section
// that still mounts the <PlayerTimelineSection>), captures
// the TZ-selector element + console errors + a full-page
// screenshot to /tmp/tz_verify.png.
import { chromium } from "@playwright/test";

const URL = "http://127.0.0.1:3000/players/test_account";

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
});
const page = await ctx.newPage();

const consoleErrors = [];
page.on("pageerror", (err) =>
  consoleErrors.push("PAGEERROR: " + err.message),
);
page.on("console", (msg) => {
  if (msg.type() === "error") {
    consoleErrors.push("CONSOLE: " + msg.text());
  }
});

try {
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: "/tmp/tz_verify.png", fullPage: true });

  const tzSelector = await page.$('[data-testid="timezone-selector"]');
  console.log("TZ_SELECTOR_FOUND", tzSelector ? "YES" : "NO");

  if (tzSelector) {
    const opts = await tzSelector.$$("option");
    console.log("TZ_OPTION_COUNT", opts.length);
    const value = await tzSelector.evaluate((el) => el.value);
    console.log("TZ_CURRENT_VALUE", value);
    const sample = [];
    for (let i = 0; i < Math.min(opts.length, 5); i++) {
      sample.push(await opts[i].evaluate((el) => el.textContent?.trim()));
    }
    console.log("TZ_FIRST_5_OPTIONS", JSON.stringify(sample));
  } else {
    const html = await page.content();
    console.log("PAGE_TITLE", await page.title());
    console.log("HTML_SIZE", html.length);
    console.log(
      "HAS_TIMELINE_SECTION",
      html.includes("Timeline controls") ? "YES" : "NO",
    );
  }

  console.log("CONSOLE_ERRORS", JSON.stringify(consoleErrors));
} finally {
  await browser.close();
}
