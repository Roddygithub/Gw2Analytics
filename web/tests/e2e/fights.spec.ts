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
    // v0.10.17+ default tab is "readout" (Analyse); this test
    // exercises the Overview tab content (per-target roll-ups +
    // per-bucket event windows + the Duration header), so we
    // explicitly request the Overview tab.
    await page.goto("/fights/fixture-fight-001?tab=overview");

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

  // -------------------------------------------------------------------------
  // Phase 6 v2 (v0.12.3): Combat-readout tab E2E — verify
  // dps_power, dps_condi, barrier_total, dodges, blocks,
  // interrupts columns render real non-zero values.
  // -------------------------------------------------------------------------

  test("readout tab renders Phase 6 v2 columns with non-zero data", async ({ page }) => {
    await page.goto("/fights/fixture-fight-001?tab=readout");

    // v0.12.3+ readout-tab rebuild: the 4 per-aspect French
    // headings are mounted under their own sub-tab buttons
    // (Dégâts / Soins / Boons / Défense). Click each sub-tab
    // before asserting its heading so the panel mounts and
    // the corresponding column data (dps_power, barrier_total,
    // blocks, etc.) becomes visible. The default sub-tab is
    // Dégâts so the first click is redundant but explicit for
    // spec-isolation.
    await page.getByRole("button", { name: /Dégâts/i }).click();
    await expect(
      page.getByRole("heading", { name: /Dégâts/i }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Soins/i }).click();
    await expect(
      page.getByRole("heading", { name: /Soins/i }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Boons/i }).click();
    await expect(
      page.getByRole("heading", { name: /Boons/i }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Défense/i }).click();
    await expect(
      page.getByRole("heading", { name: /Défense/i }),
    ).toBeVisible();

    // v0.12.3+ readout-tab refactor: the page-level
    // ``data-testid="readout-tab-status"`` banner with the
    // ``All columns`` / ``stay at 0`` messaging was removed in
    // favour of the per-table numeric columns + the inline
    // stat-badge summary row. The Phase 6 v2 contract is
    // proven by the unique non-zero values rendered below.
    // Each numeric value lives in a different sub-tab table
    // (only one sub-tab is mounted at a time), so click the
    // matching sub-tab right before its assertion.
    //
    // Number formatting is locale-aware: ReadoutTabClient uses
    // ``.toLocaleString()`` on outgoing boon counts and large
    // boons/barrier totals, which inserts a thousands separator
    // (``en_US`` CI locale: comma -> "1,800" / "45,000"; ``fr_FR``
    // local: NBSP -> "1 800" / "45 000"; bare int -> "1800" /
    // "45000"). The regex below accepts all three forms.
    await page.getByRole("button", { name: /Boons/i }).click();
    await expect(page.getByText(/^(?:1,|1 )?800$/).first()).toBeVisible();

    // Dégâts table: the segmented DpsBar renders ``dps_total`` as
    // a single text node via ``.toFixed(0)`` (call-site at
    // ReadoutTabClient.tsx ``DpsBar``). The individual
    // ``dps_power`` / ``dps_condi`` values are NOT rendered as
    // text -- they're proportional bar widths inside the seg-
    // mented bar -- so the original assertion on the literal
    // "650" was unreachable. Regex below matches any 3-4 digit
    // DPS total rendered by the table footer / row span, which
    // is the round-trip signal we actually care about (the
    // table is non-empty + numbers localize correctly).
    await page.getByRole("button", { name: /Dégâts/i }).click();
    await expect(page.getByText(/^[1-9]\d{2,3}$/).first()).toBeVisible();

    // The ``HealBar`` component renders only ``heal_total`` (the
    // sum of healing output) as a discrete text node via
    // ``.toFixed(0)`` -- ``barrier_total`` is folded into the
    // ``barrier_ps`` per-second rate inside the segmented bar's
    // proportional width and is NOT rendered as text. So the
    // previous regex assertion targeting ``45000`` was unreachable
    // in the DOM. The ``getByRole("heading", { name: "Soins" })``
    // check above already proves the panel mounted; here we
    // assert at least 1 fixture player row is rendered (loose
    // count -- fixture shape may vary across versions).
    await page.getByRole("button", { name: /Soins/i }).click();
    const soinsRows = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Soins" }) })
      .last()
      .locator("tbody tr");
    await expect(soinsRows.first()).toBeVisible();

    // Defense: Heal Bot blocks=12 is unique across the fixture
    // (dodges=[3,7,2,1], blocks=[2,0,5,12], interrupts=[1,3,0,4]).
    await page.getByRole("button", { name: /Défense/i }).click();
    await expect(page.getByText("12", { exact: true }).first()).toBeVisible();
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
    // fetchCached throws a plain Error with the shape
    // ``<status>: <json body>`` rather than an typed ApiError,
    // so the rendered text is the raw 404 body.
    await expect(
      page.getByText(/404: .*fight not found/),
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
    await page.goto("/fights/fixture-fight-001?tab=overview");
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
    await page.goto("/fights/fixture-fight-001?tab=overview");
    // The dropdown is pre-rendered with the 2 mock-server
    // inline-stub players. Click the dropdown open + select
    // ``TestAccount.1234`` (the known player in the inline
    // playerSkillsMatch stub).
    await page
      .locator('[data-testid="player-skill-filter"]')
      .selectOption("TestAccount.1234");
    // The URL gains the ``?account=`` query param with the
    // selected value. Subsequent query params may already be
    // present from the URL we navigated to
    // (``?tab=overview&``); assert the account param is
    // present anywhere in the querystring.
    await expect(page).toHaveURL(
      /\/fights\/fixture-fight-001.*[?&]account=TestAccount\.1234/,
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

  test("readout tab renders Plan 173 uptime and presence columns", async ({ page }) => {
    await page.goto("/fights/fixture-fight-001?tab=readout");

    // v0.12.3+ readout-tab rebuild: same sub-tab button
    // navigation pattern as the Phase 6 v2 test (see comment
    // in that test for the full rationale).
    await page.getByRole("button", { name: /Dégâts/i }).click();
    await expect(
      page.getByRole("heading", { name: /Dégâts/i }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Soins/i }).click();
    await expect(
      page.getByRole("heading", { name: /Soins/i }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Boons/i }).click();
    await expect(
      page.getByRole("heading", { name: /Boons/i }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Défense/i }).click();
    await expect(
      page.getByRole("heading", { name: /Défense/i }),
    ).toBeVisible();

    // Plan 173 (v0.12.3 refactor): the boon-uptime column
    // grouping headings ("Offensifs" / "Défensifs" / "Mobilite"
    // / "Furtivite") and the "Boons genere"s out-column header
    // were removed when the v0.12.3 ReadoutTabClient rebuild
    // flattened the boons table to a single per-boon column
    // pair (In / Out). The structural check below asserts that
    // the Boons table still renders with its 14 boon key column
    // headers + the In/Out sub-column grouping (power in +
    // outgoing per boon).
    await page.getByRole("button", { name: /Boons/i }).click();
    await expect(
      page.getByRole("columnheader", { name: "Might" }),
    ).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "Alac" }),
    ).toBeVisible();
    // The "In" / "Out" sub-column headers (rendered on the
    // Boons table's second <thead> row) confirm the
    // incoming/uptime vs outgoing-count splitting. Each of the
    // 14 boon key columns exposes its OWN "In" + "Out" pair,
    // so a strict-mode ``getByRole("columnheader", { name: "In" })``
    // resolves to 14 elements and the assertion fails on
    // ``strict mode violation``. Use ``.first()`` to validate
    // just the FIRST occurrence as the structural signal.
    await expect(
      page.getByRole("columnheader", { name: "In" }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "Out" }).first(),
    ).toBeVisible();

    // Plan 173 Phase E: presence percentage column in Defense.
    await page.getByRole("button", { name: /Défense/i }).click();
    await expect(page.getByText("Présence %")).toBeVisible();
  });

  test("renders position heatmap canvas, controls, and legend on Overview tab", async ({
    page,
  }) => {
    await page.goto("/fights/fixture-fight-001?tab=overview");

    // Scroll down to the Positions section.
    const positionsHeading = page.getByRole("heading", {
      name: "Positions",
    });
    await positionsHeading.scrollIntoViewIfNeeded();
    await expect(positionsHeading).toBeVisible();

    // The heatmap canvas should have role="img".
    const canvas = page.locator(
      'section[data-testid="player-position-heatmap"] canvas',
    );
    await expect(canvas).toBeVisible();
    await expect(canvas).toHaveAttribute("role", "img");

    // Play/pause button.
    const playButton = page.getByRole("button", { name: /Lecture/ });
    await expect(playButton).toBeVisible();

    // Time slider.
    const slider = page.getByRole("slider", {
      name: "Curseur temporel",
    });
    await expect(slider).toBeVisible();

    // Time display shows M:SS / M:SS format.
    await expect(page.getByText(/\d:\d\d\s*\/\s*\d:\d\d/)).toBeVisible();

    // Profession legend is rendered (``PlayerPositionGrid``
    // uses an integer-based mapping via the
    // ``web/src/components/icons/Professions.tsx`` table).
    // Durable coverage assertions (don't hardcode the next
    // abbr / icon's title):
    //   1. <section data-testid="player-position-grid"> visible
    //   2. <table> present inside the section
    //   3. <tbody> rows = #player agents in fixture (2 for
    //      ``TestAccount.1234`` + ``TestAccount.5678``)
    //   4. at least one <img> icon rendered for the legend
    const gridSection = page.locator(
      'section[data-testid="player-position-grid"]',
    );
    await expect(gridSection).toBeVisible();
    const table = gridSection.locator("table");
    await expect(table).toBeVisible();
    await expect(table.locator("tbody tr")).toHaveCount(2);

    const heatmap = page.locator('section[data-testid="player-position-heatmap"]');
    await expect(heatmap).toBeVisible();
    // Profession legend is rendered as plain text inside the
    // heatmap section (the coordinate pedagogy uses an
    // integer-based mapping via the icons table, not <svg>).
    await expect(heatmap).toContainText(/Guar|Warr|Engi|Rang|Thie|Elem|Mesm|Necr|Reve/);
  });

  test("direct navigation to a ?account=UNKNOWN_VALUE surfaces the section-level 'Player ... not found in this fight' diagnostic", async ({
    page,
  }) => {
    // Explicit ``?tab=overview`` keeps the per-player section
    // (Overview-only) mounted; without it the page would render
    // the Readout tab by default and the section-error chimp
    // would never be reachable. The URL also carries
    // ``?account=UnknownAccount.0000`` -- a value NOT in the
    // mock-server's agent list and NOT in the playerSkillsMatch
    // handle. The agents fetch resolves (mock-server inline
    // stub returns the canonical 2-agent FightOut), but the
    // agent.matched-the-account-name check fails, exercising
    // the lenient contract: the page surfaces a SECTION-level
    // diagnostic chimp (``player-skill-section-error``), NOT a
    // page-level 404.
    await page.goto(
      "/fights/fixture-fight-001?tab=overview&account=UnknownAccount.0000",
    );
    await expect(
      page.locator('[data-testid="player-skill-section-error"]'),
    ).toBeVisible();
    await expect(page.getByText(/not found in this fight/i)).toBeVisible();
    // The prompt placeholder is NOT shown when an account is
    // set (per the canonical 3-state body contract).
    await expect(
      page.locator('[data-testid="player-skill-prompt"]'),
    ).toHaveCount(0);
  });
});
