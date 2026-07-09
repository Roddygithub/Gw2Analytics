// One-shot capture against the LIVE seeded DB (not the Playwright
// mock-server). Fetches the first real account_name + fight_id
// from /api/v1/fights + /api/v1/players, then drives:
//   - /fights                                   (3-row AG Grid)
//   - /players                                  (6-row AG Grid)
//   - /players/<first-account_name>             (profile + timeline + TZ-selector)
//   - /fights/<first-fight-id>                  (drilldown with all rollups)
// NOT committed.
import { chromium } from "@playwright/test";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const consoleErrors = [];
page.on("pageerror", (err) => consoleErrors.push("PAGEERROR: " + err.message));
page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push("CONSOLE: " + msg.text()); });

try {
  const fightsResp = await page.request.get("http://127.0.0.1:8000/api/v1/fights");
  const fights = await fightsResp.json();
  const fightId = fights[0]?.id;
  const playersResp = await page.request.get("http://127.0.0.1:8000/api/v1/players");
  const players = await playersResp.json();
  const accountName = players[0]?.account_name;
  console.log("REAL_FIGHT_ID", fightId);
  console.log("REAL_ACCOUNT_NAME", accountName);

  // /fights list
  await page.goto("http://127.0.0.1:3000/fights", { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.body.scrollHeight > 900, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: "/tmp/real_fights.png", fullPage: true });

  // /players list
  await page.goto("http://127.0.0.1:3000/players", { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.body.scrollHeight > 900, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: "/tmp/real_players.png", fullPage: true });

  // /players/<account> (with TZ-selector visible)
  await page.goto(`http://127.0.0.1:3000/players/${encodeURIComponent(accountName)}`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.body.scrollHeight > 900, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(800);
  const tzSelector = await page.$('[data-testid="timezone-selector"]');
  console.log("TZ_SELECTOR_FOUND", tzSelector ? "YES" : "NO");
  if (tzSelector) {
    const opts = await tzSelector.$$("option");
    console.log("TZ_OPTION_COUNT", opts.length);
    const values = await Promise.all(opts.slice(0, 5).map(o => o.evaluate(el => el.value)));
    console.log("TZ_FIRST_5_VALUES", JSON.stringify(values));
  }
  await page.screenshot({ path: "/tmp/real_player_profile.png", fullPage: true });

  // /fights/<fight-id> drilldown
  await page.goto(`http://127.0.0.1:3000/fights/${encodeURIComponent(fightId)}`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => document.body.scrollHeight > 900, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(800);
  await page.screenshot({ path: "/tmp/real_fight_drilldown.png", fullPage: true });

  console.log("CONSOLE_ERRORS", JSON.stringify(consoleErrors));
} catch (err) {
  console.log("FAILED", err.message);
} finally {
  await browser.close();
}
