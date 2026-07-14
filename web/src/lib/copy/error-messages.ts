/**
 * User-facing error message constants for the ``/fights/[id]``
 * Server Component's diagnostic chips.
 *
 * v0.10.18 deliverable (part of the ``feat/integrate-zevtc-fixture``
 * branch's hard-close-out): the per-player section chips used to
 * inline the "Failed to load X:" prefix strings directly in
 * ``src/app/fights/[id]/page.tsx``. The cascade regression test
 * (https://github.com/Roddygithub/Gw2Analytics -- branch
 * ``feat/integrate-zevtc-fixture``, commit ``d20bdd4``) then
 * asserted those prefixes by string-literal regex, coupling the
 * test to the English copy. A future i18n refactor (English ->
 * French / German / etc.) would silently break the assertions
 * without breaking the cascade *behavior*.
 *
 * This module centralises the prefix strings so a single edit
 * propagates to both the page render AND the test assertion
 * regex. Project-wide i18n is *out of scope* for v0.10.x --
 * this module exists to make the eventual i18n a 1-file edit
 * rather than a 3-file edit.
 *
 * Why NO trailing space in each prefix
 * =====================================
 * The page.tsx renders each prefix as a standalone JSX segment
 * followed by the upstream ``{error}`` interpolation with a
 * single space between them (e.g.,
 * ``<p>{PREFIX} {error}</p>``). Stripping the trailing space
 * from the constant means:
 *   - the prefix string matches the test's
 *     ``new RegExp(constant)`` pattern exactly (no regex
 *     metacharacter in the constant makes the pattern safe);
 *   - HTML output is identical to the inlined baseline
 *     (``"<prefix>: <error>"`` -- the literal space character
 *     is a single U+0020, not a tab or non-breaking space).
 *
 * Trade-off: a future maintainer who changes the prefix to
 * ``"Failed to load"`` (without the trailing colon) would
 * inadvertently drop the colon from the rendered text. The
 * JSDoc on each export below makes the contract explicit so
 * a code-search ``FAILED_TO_LOAD_PER_PLAYER_SKILLS`` is
 * enough to recover the intent.
 */

/**
 * Prefix string for the ``player-skill-agents-error`` chip --
 * surfaced when the bare ``/fights/:id`` (agents-list) fetch
 * throws ApiError(4xx/5xx). The chip reads
 * "``Failed to load player list: <formatApiError>``".
 */
export const FAILED_TO_LOAD_PLAYER_LIST = "Failed to load player list:";

/**
 * Prefix string for the ``player-skill-error`` chip --
 * surfaced when the per-player skills fetch throws OR when
 * ``?account=`` points at an account not in the fight's
 * agents list. The chip reads
 * "``Failed to load per-player skills: <accountSkillsError>``".
 * The same upstream error cascades into both chips on an
 * agents-fetch failure (the contract pinned by the dual-banner
 * regression test).
 */
export const FAILED_TO_LOAD_PER_PLAYER_SKILLS =
  "Failed to load per-player skills:";

/**
 * Catch-all fallback when ``accountFilter !== null`` but the
 * agents fetch error is the root cause of the per-player
 * section's empty state. NOT a JSX prefix -- it stands alone
 * in the chip text. Reads
 * "``Failed to load fight details.``" (terminal period, no
 * upstream interpolation). Sibling to the two prefix strings
 * above so the test can import all three from one place.
 */
export const FAILED_TO_LOAD_FIGHT_DETAILS = "Failed to load fight details.";

/**
 * JSX prefix for the readout-tab-status error branch -- when
 * ``readoutError !== null`` (the ``GET /api/v1/fights/{id}/readout``
 * call throws). Reads "``Combat-readout fetch failed: <error>``".
 * NO trailing space (matches the 691a306 convention for the
 * error-prefix exports; the literal space is added at the
 * call site via JSX: ``<>{COMBAT_READOUT_FETCH_FAILED} {readoutError}</>``).
 */
export const COMBAT_READOUT_FETCH_FAILED = "Combat-readout fetch failed:";

/**
 * Standalone JSX text for the readout-tab-status loading branch --
 * when ``readoutData === null`` (the fetch is in-flight, no
 * upstream error). Terminal ellipsis (U+2026 horizontal ellipsis,
 * NOT three U+002E dots) to match the analyst-facing "loading"
 * convention. Read "``Loading combat readout…``".
 */
export const COMBAT_READOUT_LOADING = "Loading combat readout\u2026";

/**
 * Standalone JSX text for the per-player-section prompt placeholder
 * -- when ``accountFilter === null`` AND no account has been picked
 * from the dropdown. Reads
 * "``Pick a player from the dropdown to see per-player skill
 * attribution.``" (terminal period). Sits in a low-opacity
 * ``<p>`` to signal the empty-state to the analyst.
 */
export const PER_PLAYER_PROMPT_PLACEHOLDER =
  "Pick a player from the dropdown to see per-player skill attribution.";

/**
 * Text content of the `<Link>` rendered by the **root** error.tsx
 * (`web/src/app/error.tsx`). Lower-case ("the fights grid") — mid-sentence
 * flow: "...head back to the fights grid". No trailing space; the JSX
 * sibling `{" "}` adds the trailing separator. 691a306 convention.
 */
export const FIGHTS_GRID_LINK_ROOT = "the fights grid";

/**
 * Text content of the `<Link>` rendered by the **per-fight** error.tsx
 * (`web/src/app/fights/[id]/error.tsx`). Includes the `←` glyph and a
 * leading space; no trailing space — the JSX `<Link>` is the last child
 * node and a suffix " " (if any) lives in JSX. 691a306 convention.
 */
export const FIGHTS_GRID_BROWSE_FIGHT_PAGE = "← Browse fights grid";

/**
 * Format prefix that the API layer prepends to every `ApiError`'s
 * rendered copy. Used by `formatApiError` in
 * `web/src/lib/api/errors.ts` to build the user-facing string
 * `"Upstream error: <status>: <message>"`. Traling space IS intentional
 * (it separates prefix from `err.status`); do NOT drop without
 * updating the JSX interpolation site. Backs 2 vitest assertions
 * (`fight-events-page.test.tsx` + `fights-page.test.tsx`).
 */
export const UPSTREAM_ERROR_PREFIX = "Upstream error: ";

// ===========================================================================
// AG Grid column headers (FightsGrid — the read-only fights-list table)
// ===========================================================================

/** Column header for the AG Grid `#` column. */
export const FIGHTS_GRID_COLUMN_FIGHT_ID = "Fight ID";

/** Column header for the AG Grid `Encounter` column. */
export const FIGHTS_GRID_COLUMN_ENCOUNTER = "Encounter";

/** Column header for the AG Grid `Agents` column (count of players). */
export const FIGHTS_GRID_COLUMN_AGENTS = "Agents";

/** Column header for the AG Grid `Build` column (player build composition). */
export const FIGHTS_GRID_COLUMN_BUILD = "Build";

/** Column header for the AG Grid start-time column. The `(UTC)` suffix is
 *  intentional and shown verbatim in the rendered UI. */
export const FIGHTS_GRID_COLUMN_STARTED_UTC = "Started (UTC)";

/** Column header for the AG Grid `Game type` column (raid / fractal / strike / wvw). */
export const FIGHTS_GRID_COLUMN_GAME_TYPE = "Game type";

// ===========================================================================
// SkillUsageTable — column headers + empty-state fallback
// ===========================================================================

/** Column header for the `id` column (numeric GW2 skill id). */
export const SKILL_USAGE_TABLE_COLUMN_SKILL_ID = "Skill id";

/** Column header for the `name` column (resolved skill name from skills DB). */
export const SKILL_USAGE_TABLE_COLUMN_SKILL_NAME = "Skill name";

/** Column header for the `hits` column. */
export const SKILL_USAGE_TABLE_COLUMN_HIT_COUNT = "Hit count";

/** Column header for the `damage` column. */
export const SKILL_USAGE_TABLE_COLUMN_TOTAL_DAMAGE = "Total damage";

/** Column header for the `healing` column. */
export const SKILL_USAGE_TABLE_COLUMN_TOTAL_HEALING = "Total healing";

/** Column header for the `strip` column (boon-strip aggregates). */
export const SKILL_USAGE_TABLE_COLUMN_TOTAL_STRIP = "Total strip";

/** Empty-state row fallback when the per-fight skill roll-up stream is empty. */
export const SKILL_USAGE_TABLE_EMPTY_STATE = "No skill roll-up rows.";
