/**
 * Playwright E2E for the v0.7.1 /fights/[id] page.
 *
 * The page calls 4 fetchers via ``Promise.allSettled``:
 *   1. ``fetchFightEvents(id, { windowS })`` -- the per-target
 *      trio + per-bucket event windows.
 *   2. ``fetchFightSquads(id)`` -- per-subgroup roll-up.
 *   3. ``fetchFightSkills(id)`` -- per-skill roll-up.
 *   4. ``fetchFightTimeline(id, { windowS })`` (v0.8.9 plan/002)
 *      -- per-fight timeline section.
 *
 * The mock server returns fixture JSON for all 4 endpoints when
 * the fight id is ``fixture-fight-001`` or ``fixture-fight-002``.
 *
 * Why a single smoke test (vs 6 + 1 for each section)
 * ==================================================
 * The 6 roll-up sections (per-target damage + healing +
 * buff-removal + per-subgroup + per-skill + per-fight timeline)
 * all share the same SSR fetch path; the section-level
 * rendering is fully covered by the unit tests in
 * tests/app/fight-events-page.test.tsx. The E2E only needs to
 * prove that the SSR pipeline returns a fully-rendered tree for
 * a real fight id (so a regression in the fetchers, the
 * routing, or the page contract is caught).
 */
import { test, expect } from "@playwright/test";

test.describe("/fights/[id] (v0.7.1)", () => {
  test("renders the 5 roll-up sections + event windows for a known fight", async ({ page }) => {
    await page.goto("/fights/fixture-fight-001");

    // Header strip
    await expect(
      page.getByRole("heading", { name: "Fight fixture-fight-001" }),
    ).toBeVisible();
    // The duration is rendered with 2-decimal fixed formatting
    // via ``toFixed(2)``; the JSON-stringified HTML splits the
    // children (the parser renders ``Duration: 12.50 s`` as
    // ``["Duration: ", "12.50", " s"]`` -- the .toBeVisible
    // check tolerates that).
    await expect(page.getByText(/Duration: 12\.50\s+s/)).toBeVisible();

    // The 5 roll-up section headings
    await expect(
      page.getByRole("heading", { name: "Per-target damage" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-target healing" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-target buff removal" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-subgroup (squad)" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Per-skill" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Event windows" }),
    ).toBeVisible();
    // v0.8.9 of web (plan/002): the per-fight timeline is the
    // 7th section, mounted below the per-bucket event windows.
    // The mock server's per-fight timeline handler returns 3
    // 5-second buckets for ``fixture-fight-001`` (15.0s
    // duration); the section heading + the chart's ``<svg>``
    // element are the only round-trip assertions we need.
    await expect(
      page.getByRole("heading", { name: "Per-fight timeline" }),
    ).toBeVisible();
  });

  test("renders the upstream-error card for an unknown fight id", async ({ page }) => {
    // ``unknown-fight-999`` is not in the mock server's
    // KNOWN_FIGHTS set, so the /events fetch returns 404, the
    // page catches the ``ApiError``, and renders the
    // upstream-error card.
    await page.goto("/fights/unknown-fight-999");

    await expect(
      page.getByRole("heading", { name: "Fight unknown-fight-999" }),
    ).toBeVisible();
    await expect(
      page.getByText(/Upstream error: 404: .*fight not found/),
    ).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Tour 4 v0.10.13 plan 044 Playwright coverage: the per-player
  // skill attribution section on ``/fights/[id]``. The mock-server
  // exposes 2 NEW inline stub endpoints (see ``tests/e2e/mock-server.mjs``
  // for the Tour 4 additions).
  // -------------------------------------------------------------------------

  test("renders the per-player section heading + the 'Pick a player' prompt on first load (no ?account= URL filter)", async ({
    page,
  }) => {
    await page.goto("/fights/fixture-fight-001");
    // The per-player section heading is the 8th <h2> in the
    // OVERVIEW render and has a stable name. The mock-server
    // returns the canonical 2-player FightOut stub so the
    // dropdown is pre-rendered with the 2 selectable options.
    await expect(
      page.getByRole("heading", {
        name: /Per-player \(SkillUsage attribution\)/,
      }),
    ).toBeVisible();
    // The ``player-skill-prompt`` testid pins the empty-state
    // prompt (the "Pick a player" hint) for screenshot
    // scripting.
    await expect(
      page.locator('[data-testid="player-skill-prompt"]'),
    ).toBeVisible();
    await expect(page.getByText(/Pick a player/i)).toBeVisible();
    // The player-skill-filter dropdown is pre-rendered (the
    // mock-server's FightOut stub has 2 player agents).
    await expect(
      page.locator('[data-testid="player-skill-filter"]'),
    ).toBeVisible();
  });

  test("selecting a player from the dropdown appends ?account=NEW_VALUE to the URL + reveals the loadout bar", async ({
    page,
  }) => {
    await page.goto("/fights/fixture-fight-001");
    // The dropdown is pre-rendered with the 2 mock-server
    // inline-stub players. Click the dropdown open + select
    // ``TestAccount.1234`` (the known player in the inline
    // playerSkillsMatch stub).
    await page
      .locator('[data-testid="player-skill-filter"]')
      .selectOption("TestAccount.1234");
    // The URL gains the ``?account=`` query param with the
    // selected value. The fight-id is appended for
    // shareability (analyst can bookmark the per-player view
    // for a specific account).
    await expect(page).toHaveURL(
      /\/fights\/fixture-fight-001[?&]account=TestAccount\.1234/,
    );
    // The loadout bar testid ``player-skill-loadout`` becomes
    // visible once the per-player skill fetch resolves.
    await expect(
      page.locator('[data-testid="player-skill-loadout"]'),
    ).toBeVisible();
    // The skill table testid becomes visible (the mock-server
    // returns 1 skill row for the per-player stub).
    await expect(
      page.locator('[data-testid="player-skill-table"]'),
    ).toBeVisible();
    // The "Whirlwind" skill row text is present (1 skill row
    // from the inline stub). The skill-usage table is now
    // visible to the analyst.
    await expect(page.getByText("Whirlwind")).toBeVisible();
  });

  test("direct navigation to a ?account=UNKNOWN_VALUE surfaces the section-level 'Player ... not found in this fight' diagnostic", async ({
    page,
  }) => {
    // Navigating directly to ``?account=UnknownAccount.0000``
    // (a value NOT in the mock-server's agent list, NOT in
    // the playerSkillsMatch handle) exercises the lenient
    // contract: the page surfaces a SECTION-level diagnostic
    // chimp (``player-skill-error``), not a page-level 404.
    // The agents fetch resolves (mock-server inline stub
    // returns the canonical 2-agent FightOut), but the
    // agent.matched-the-account-name check fails.
    await page.goto(
      "/fights/fixture-fight-001?account=UnknownAccount.0000",
    );
    await expect(
      page.locator('[data-testid="player-skill-error"]'),
    ).toBeVisible();
    await expect(page.getByText(/not found in this fight/i)).toBeVisible();
    // The prompt placeholder is NOT shown when an account is
    // set (per the canonical 3-state body contract).
    await expect(
      page.locator('[data-testid="player-skill-prompt"]'),
    ).toHaveCount(0);
  });
});
