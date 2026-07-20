/**
 * Real user journey test - runs against the live backend (no mock server).
 * Tests the full flow: landing -> upload -> fight detail -> fights list -> players -> player profile -> account -> compare
 */
import { chromium } from "playwright";
import { join } from "node:path";
import { mkdirSync } from "node:fs";

const BASE = "http://localhost:3000";
const SCREENSHOT_DIR = join(process.cwd(), "tests/e2e/screenshots/real-journey");
const ZEVTC_PATH = "/home/roddy/Projects/Gw2Analytics/real_fight.zevtc";

mkdirSync(SCREENSHOT_DIR, { recursive: true });

async function screenshot(page, name) {
  const path = join(SCREENSHOT_DIR, `${name}.png`);
  await page.screenshot({ path, fullPage: true });
  console.log(`  📸 Screenshot: ${name}.png`);
}

async function checkErrors(page, label, errors) {
  if (errors.length > 0) {
    console.log(`  ❌ ${label} - ${errors.length} error(s):`);
    errors.forEach((e) => console.log(`    - ${e}`));
  } else {
    console.log(`  ✅ ${label} - No errors`);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  const pageErrors = [];
  const consoleErrors = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  try {
    // ==========================================
    // 1. LANDING PAGE
    // ==========================================
    console.log("\n🏠 1. Landing page");
    const landingPageErrors = [];
    const landingConsoleErrors = [];
    page.on("pageerror", (err) => landingPageErrors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") landingConsoleErrors.push(msg.text());
    });

    await page.goto(`${BASE}/`);
    await page.waitForLoadState("networkidle");
    await screenshot(page, "01-landing");

    // Check main heading
    const heading = await page.locator("h1").first().textContent();
    console.log(`  Heading: "${heading}"`);

    // Check navigation links
    const links = await page.locator("a").allTextContents();
    console.log(`  Links found: ${links.filter((l) => l.trim()).join(", ")}`);

    await checkErrors(page, "Landing page", landingPageErrors);
    page.removeListener("pageerror", (err) => landingPageErrors.push(err.message));

    // ==========================================
    // 2. UPLOAD PAGE - Pick file
    // ==========================================
    console.log("\n📤 2. Upload page - Pick file");
    await page.goto(`${BASE}/upload`);
    await page.waitForLoadState("networkidle");
    await screenshot(page, "02-upload-pick");

    // Check heading
    const uploadHeading = await page.locator("h1").first().textContent();
    console.log(`  Heading: "${uploadHeading}"`);

    // Check file input exists
    const fileInput = page.getByTestId("file-input");
    const fileInputExists = await fileInput.count();
    console.log(`  File input found: ${fileInputExists > 0}`);

    // Select the real zevtc file
    console.log(`  Uploading: ${ZEVTC_PATH}`);
    await fileInput.setInputFiles(ZEVTC_PATH);
    await page.waitForTimeout(500);
    await screenshot(page, "03-upload-file-selected");

    // Check next button state
    const nextButton = page.getByTestId("next");
    const nextEnabled = await nextButton.isEnabled();
    console.log(`  Next button enabled: ${nextEnabled}`);

    // ==========================================
    // 3. UPLOAD - Submit & Parse
    // ==========================================
    console.log("\n📤 3. Upload - Submit & Parse");
    await nextButton.click();
    await screenshot(page, "04-upload-uploading");

    // Wait for the upload step
    const uploadStep = page.getByTestId("step-upload");
    const parseStep = page.getByTestId("step-parse");
    const doneStep = page.getByTestId("step-done");

    // Wait for parse step or done step
    try {
      await parseStep.waitFor({ state: "visible", timeout: 15000 });
      console.log("  Parse step visible - waiting for completion...");
      await screenshot(page, "05-upload-parsing");
    } catch {
      console.log("  Parse step not found, checking for done step...");
    }

    // Wait for done step (longer timeout for real parsing)
    try {
      await doneStep.waitFor({ state: "visible", timeout: 60000 });
      console.log("  ✅ Upload complete!");
      await screenshot(page, "06-upload-done");

      // Check for fight link
      const fightLinks = await page.locator('a[href*="/fights/"]').all();
      console.log(`  Fight links found: ${fightLinks.length}`);
      for (const link of fightLinks) {
        const text = await link.textContent();
        const href = await link.getAttribute("href");
        console.log(`    - ${text} -> ${href}`);
      }
    } catch (err) {
      console.log(`  ⚠️  Done step not reached: ${err.message}`);
      // Check if there's an error displayed
      const errorEl = page.getByTestId("error");
      const pollError = page.getByTestId("poll-error");
      const pollTimeout = page.getByTestId("poll-timeout");

      if (await errorEl.count()) {
        const errorText = await errorEl.textContent();
        console.log(`  ❌ Error: ${errorText}`);
      }
      if (await pollError.count()) {
        const errorText = await pollError.textContent();
        console.log(`  ❌ Poll error: ${errorText}`);
      }
      if (await pollTimeout.count()) {
        const errorText = await pollTimeout.textContent();
        console.log(`  ❌ Poll timeout: ${errorText}`);
      }

      await screenshot(page, "06-upload-error");
    }

    // Collect errors from upload section
    const allPageErrors = [...pageErrors];
    const allConsoleErrors = [...consoleErrors];
    await checkErrors(page, "Upload flow", allPageErrors);

    // ==========================================
    // 4. FIGHTS LIST
    // ==========================================
    console.log("\n⚔️  4. Fights list");
    await page.goto(`${BASE}/fights`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await screenshot(page, "07-fights-list");

    const fightsHeading = await page.locator("h1").first().textContent();
    console.log(`  Heading: "${fightsHeading}"`);

    // Check for fight links in the grid
    const fightLinks = await page.locator('a[href*="/fights/"]').all();
    console.log(`  Fight links: ${fightLinks.length}`);
    for (const link of fightLinks.slice(0, 5)) {
      const text = await link.textContent();
      const href = await link.getAttribute("href");
      console.log(`    - ${text?.trim()} -> ${href}`);
    }

    // Check page content
    const pageContent = await page.locator("body").textContent();
    console.log(`  Page content length: ${pageContent?.length || 0} chars`);
    if (pageContent?.includes("error") || pageContent?.includes("Error")) {
      console.log(`  ⚠️  Page may contain error text`);
    }

    // ==========================================
    // 5. FIGHT DETAIL (if fights exist)
    // ==========================================
    let fightId = null;
    if (fightLinks.length > 0) {
      const firstFightHref = await fightLinks[0].getAttribute("href");
      fightId = firstFightHref?.split("/").pop();
      console.log(`\n🔍 5. Fight detail: ${fightId}`);
      await fightLinks[0].click();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);
      await screenshot(page, "08-fight-detail");

      const detailHeading = await page.locator("h1").first().textContent();
      console.log(`  Heading: "${detailHeading}"`);

      // Check tabs
      const tabs = await page.locator('[role="tab"], [data-testid*="page-tab"]').allTextContents();
      console.log(`  Tabs: ${tabs.join(", ")}`);

      // Check for sections
      const headings = await page.locator("h2").allTextContents();
      console.log(`  H2 sections: ${headings.join(", ")}`);

      // Check for data tables/grids
      const grids = await page.locator('.ag-root, [role="grid"]').count();
      console.log(`  AG Grid elements: ${grids}`);

      // Check for charts
      const svgs = await page.locator("svg").count();
      console.log(`  SVG elements (charts): ${svgs}`);

      // Try Readout tab
      const readoutTab = page.getByTestId("page-tab-readout");
      if (await readoutTab.count()) {
        console.log("  Switching to Readout tab...");
        await readoutTab.click();
        await page.waitForTimeout(2000);
        await screenshot(page, "09-fight-readout");

        const readoutHeadings = await page.locator("h2").allTextContents();
        console.log(`  Readout sections: ${readoutHeadings.join(", ")}`);
      }
    } else {
      console.log("\n⏭️  5. No fights to drill into");
    }

    // ==========================================
    // 6. PLAYERS LIST
    // ==========================================
    console.log("\n👥 6. Players list");
    await page.goto(`${BASE}/players`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await screenshot(page, "10-players-list");

    const playersHeading = await page.locator("h1").first().textContent();
    console.log(`  Heading: "${playersHeading}"`);

    // Check for player links
    const playerLinks = await page.locator('a[href*="/players/"]').all();
    const filteredPlayerLinks = [];
    for (const link of playerLinks) {
      const href = await link.getAttribute("href");
      if (href && !href.includes("/players/compare")) {
        filteredPlayerLinks.push(link);
      }
    }
    console.log(`  Player links: ${filteredPlayerLinks.length}`);
    for (const link of filteredPlayerLinks.slice(0, 5)) {
      const text = await link.textContent();
      const href = await link.getAttribute("href");
      console.log(`    - ${text?.trim()} -> ${href}`);
    }

    // Check page content
    const playersContent = await page.locator("body").textContent();
    console.log(`  Page content length: ${playersContent?.length || 0} chars`);

    // ==========================================
    // 7. PLAYER PROFILE (if players exist)
    // ==========================================
    if (filteredPlayerLinks.length > 0) {
      console.log("\n👤 7. Player profile");
      await filteredPlayerLinks[0].click();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);
      await screenshot(page, "11-player-profile");

      const profileHeading = await page.locator("h1").first().textContent();
      console.log(`  Heading: "${profileHeading}"`);

      // Check for sections
      const profileSections = await page.locator("h2").allTextContents();
      console.log(`  Sections: ${profileSections.join(", ")}`);

      // Check for timeline chart
      const profileSvgs = await page.locator("svg").count();
      console.log(`  SVG elements: ${profileSvgs}`);

      // Check for fight links
      const playerFightLinks = await page.locator('a[href*="/fights/"]').count();
      console.log(`  Fight links: ${playerFightLinks}`);
    } else {
      console.log("\n⏭️  7. No players to view");
    }

    // ==========================================
    // 8. ACCOUNT / API KEY
    // ==========================================
    console.log("\n🔑 8. Account / API key");
    await page.goto(`${BASE}/account`);
    await page.waitForLoadState("networkidle");
    await screenshot(page, "12-account");

    const accountHeading = await page.locator("h1").first().textContent();
    console.log(`  Heading: "${accountHeading}"`);

    // Check for input and button
    const apiKeyInput = page.locator('input[type="password"], input[type="text"]').first();
    const resolveButton = page.getByRole("button", { name: /resolve/i });
    console.log(`  API key input found: ${(await apiKeyInput.count()) > 0}`);
    console.log(`  Resolve button found: ${(await resolveButton.count()) > 0}`);

    // Fill in a test API key
    if ((await apiKeyInput.count()) > 0 && (await resolveButton.count()) > 0) {
      await apiKeyInput.fill("test-api-key-12345");
      await screenshot(page, "13-account-filled");
      await resolveButton.click();
      await page.waitForTimeout(3000);
      await screenshot(page, "14-account-resolved");

      // Check result
      const accountContent = await page.locator("body").textContent();
      if (accountContent?.includes("Resolved") || accountContent?.includes("resolved")) {
        console.log("  ✅ API key resolved");
      } else if (accountContent?.includes("error") || accountContent?.includes("Error")) {
        console.log("  ⚠️  API key resolution may have errors");
      }
    }

    // ==========================================
    // 9. PLAYERS COMPARE
    // ==========================================
    console.log("\n📊 9. Players compare");
    await page.goto(`${BASE}/players/compare`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await screenshot(page, "15-players-compare");

    const compareHeading = await page.locator("h1").first().textContent();
    console.log(`  Heading: "${compareHeading}"`);

    // Check for account input fields
    const accountInputs = await page.locator('input').count();
    console.log(`  Input fields: ${accountInputs}`);

    // Check for add/compare buttons
    const buttons = await page.locator("button").allTextContents();
    console.log(`  Buttons: ${buttons.join(", ")}`);

    // Check page content
    const compareContent = await page.locator("body").textContent();
    console.log(`  Page content length: ${compareContent?.length || 0} chars`);

    // ==========================================
    // 10. WEBHOOKS
    // ==========================================
    console.log("\n🔔 10. Webhooks");
    await page.goto(`${BASE}/webhooks`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await screenshot(page, "16-webhooks");

    const webhooksHeading = await page.locator("h1").first().textContent();
    console.log(`  Heading: "${webhooksHeading}"`);

    const webhooksContent = await page.locator("body").textContent();
    console.log(`  Page content length: ${webhooksContent?.length || 0} chars`);

    // ==========================================
    // FINAL SUMMARY
    // ==========================================
    console.log("\n" + "=".repeat(60));
    console.log("📋 SUMMARY");
    console.log("=".repeat(60));
    console.log(`  Total page errors: ${pageErrors.length}`);
    console.log(`  Total console errors: ${consoleErrors.length}`);
    if (pageErrors.length > 0) {
      console.log("  Page errors:");
      pageErrors.forEach((e) => console.log(`    - ${e}`));
    }
    if (consoleErrors.length > 0) {
      console.log("  Console errors:");
      consoleErrors.forEach((e) => console.log(`    - ${e}`));
    }
    console.log(`\n  Screenshots saved to: ${SCREENSHOT_DIR}`);
  } catch (err) {
    console.error("\n💥 FATAL ERROR:", err.message);
    console.error(err.stack);
    await screenshot(page, "FATAL-error");
  } finally {
    await browser.close();
  }
})();
