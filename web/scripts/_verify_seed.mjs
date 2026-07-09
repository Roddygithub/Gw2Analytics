// Throwaway verification: take screenshots of /fights, /players,
// and a player profile page to prove the empty-DB blocker is
// unblocked. Same pattern as _verify_tz_selector.mjs.
import { chromium } from "@playwright/test";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const consoleErrors = [];
page.on("pageerror", (err) => consoleErrors.push("PAGEERROR: " + err.message));
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push("CONSOLE: " + msg.text()); });

try {
  // Fetch the first fight_id dynamically so the screenshot URL
  // is valid even if the seed IDs change.
  const fightsResp = await page.request.get("http://127.0.0.1:8000/api/v1/fights");
  const fightsBody = await fightsResp.json();
  const firstFightId = fightsBody.length > 0 ? fightsBody[0].id : "none";
  console.log("FIGHTS_COUNT", fightsBody.length);
  console.log("FIRST_FIGHT_ID", firstFightId);

  const playersResp = await page.request.get("http://127.0.0.1:8000/api/v1/players");
  const playersBody = await playersResp.json();
  console.log("PLAYERS_COUNT", playersBody.length);
  const firstAccount = playersBody.length > 0 ? playersBody[0].account_name : "none";
  console.log("FIRST_ACCOUNT", firstAccount);

  // Screenshot /fights
  await page.goto("http://127.0.0.1:3000/fights", { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: "/tmp/seed_fights.png", fullPage: true });
  const fightsTableRows = await page.$$("table tr, [role='grid'] [role='row']");
  console.log("FIGHTS_PAGE_ROWS", fightsTableRows.length);

  // Screenshot /players
  await page.goto("http://127.0.0.1:3000/players", { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: "/tmp/seed_players.png", fullPage: true });
  const playersTableRows = await page.$$("table tr, [role='grid'] [role='row']");
  console.log("PLAYERS_PAGE_ROWS", playersTableRows.length);

  // Screenshot a player profile (the TZ-selector blocker test too!)
  if (firstAccount !== "none") {
    const encoded = encodeURIComponent(firstAccount);
    await page.goto(`http://127.0.0.1:3000/players/${encoded}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: "/tmp/seed_player_profile.png", fullPage: true });
    const tzSelector = await page.$('[data-testid="timezone-selector"]');
    console.log("TZ_SELECTOR_FOUND", tzSelector ? "YES" : "NO");
    if (tzSelector) {
      const opts = await tzSelector.$$("option");
      console.log("TZ_OPTION_COUNT", opts.length);
    }
  }

  console.log("CONSOLE_ERRORS", JSON.stringify(consoleErrors));
} finally {
  await browser.close();
}
