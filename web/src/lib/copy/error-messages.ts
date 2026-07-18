/**
 * Cross-cutting user-facing error + loading + UI affordance constants
 * for the web frontend.
 *
 * v0.10.22-night-mode deliverable: this file used to be a kitchen-sink
 * 257-LoC + 44-export module covering 4 unrelated concerns. The split
 * landed 3 NEW sibling sub-modules so each module owns a single concern:
 *
 *   - @/lib/copy/error-messages        (THIS file -- error / loading / affordance)
 *   - @/lib/copy/fights-grid           (AG Grid column headers)
 *   - @/lib/copy/skill-usage-table     (SkillUsageTable headers + empty state)
 *   - @/lib/copy/player-timeline       (PlayerTimelineSection controls)
 *
 * Why direct imports (no barrel re-export)
 * ========================================
 * The split decision was: each importer (FightsGrid.tsx,
 * SkillUsageTable.tsx, PlayerTimelineSection.tsx) points directly at
 * its sub-module instead of a barrel re-exporting all 4. Rationale:
 *
 *   - A barrel recreates the kitchen-sink problem at the barrel layer
 *     (a single `import * from "@/lib/copy"` re-introduces the same
 *     blur, defeating the type-system enforcement of single-concern
 *     imports).
 *   - Direct imports force type-system-level evidence that each
 *     component depends on the SPECIFIC sub-module it needs (a
 *     FightsGrid.tsx that imports from `@/lib/copy/player-timeline`
 *     is a typecheck error -- the wrong-scope import is loud).
 *   - Direct imports are tree-shake friendly (each sub-module is a
 *     separate file the bundler can drop if no importer uses it).
 *
 * Trade-off: 3 components each need a one-line import-path update
 * (`@/lib/copy/error-messages` -> `@/lib/copy/<their-sub-module>`).
 * This is a tangible but bounded cost that's mechanical to execute +
 * mechanical to review.
 *
 * v0.10.18 origin: the per-player section chips used to inline the
 * "Failed to load X:" prefix strings directly in
 * `src/app/fights/[id]/page.tsx`. The cascade regression test then
 * asserted those prefixes by string-literal regex, coupling the test
 * to the English copy. A future i18n refactor (English -> French /
 * German / etc.) would silently break the assertions without breaking
 * the cascade behavior.
 *
 * This module centralises the error/loading affordances so a single
 * edit propagates to both the page render AND the test assertion
 * regex. Project-wide i18n is OUT OF SCOPE for v0.10.x -- THIS and
 * the 3 sibling sub-modules exist to make the eventual i18n a
 * 4-file edit instead of a kitchen-sink refactor.
 *
 * Why NO trailing space in each prefix
 * =====================================
 * The page.tsx renders each prefix as a standalone JSX segment
 * followed by the upstream ``{error}`` interpolation with a single
 * space between them (e.g., ``<p>{PREFIX} {error}</p>``). Stripping
 * the trailing space from the constant means:
 *   - the prefix string matches the test's ``new RegExp(constant)``
 *     pattern exactly (no regex metacharacter in the constant makes
 *     the pattern safe);
 *   - HTML output is identical to the inlined baseline
 *     (``"<prefix>: <error>"`` -- the literal space character is a
 *     single U+0020, not a tab or non-breaking space).
 *
 * Trade-off: a future maintainer who changes the prefix to
 * ``"Failed to load"`` (without the trailing colon) would
 * inadvertently drop the colon from the rendered text. The JSDoc on
 * each export below makes the contract explicit so a code-search
 * ``FAILED_TO_LOAD_PER_PLAYER_SKILLS`` is enough to recover the
 * intent.
 */

/**
 * Prefix string for the ``player-skill-agents-section-error`` chip --
 * surfaced when the bare ``/fights/:id`` (agents-list) fetch
 * throws ApiError(4xx/5xx). The chip reads
 * "``Failed to load player list: <formatApiError>``".
 */
export const FAILED_TO_LOAD_PLAYER_LIST = "Failed to load player list:";

/**
 * Prefix string for the ``player-skill-section-error`` chip --
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
 * `"Upstream error: <status>: <message>"`. Trailing space IS
 * intentional (separates prefix from `err.status`); do NOT drop
 * without updating the JSX interpolation site. Backs 2 vitest
 * assertions (`fight-events-page.test.tsx` + `fights-page.test.tsx`).
 */
export const UPSTREAM_ERROR_PREFIX = "Upstream error: ";

/**
 * Title for the empty-state panel shown on the fight detail page
 * when the fight exists but has no combat event blob (e.g. a
 * synthetic / empty log). Renders as the heading of the panel.
 */
export const NO_EVENT_DATA_TITLE = "No event data";

/**
 * Body text for the empty-state panel shown on the fight detail
 * page when the fight exists but has no combat event blob. Explains
 * that the fight was parsed successfully but no combat events were
 * recorded, so roll-ups and event windows cannot be computed.
 */
export const NO_EVENT_DATA_BODY =
  "This fight was parsed successfully, but no combat events were recorded in the log. The fight summary and agent list are still available above; roll-ups and event windows cannot be computed without event data.";

/** Retry button text. Used in BOTH `web/src/app/error.tsx`
 *  (root global error boundary) AND `web/src/app/fights/[id]/error.tsx`
 *  (per-fight error boundary). The two surfaces share the same affordance
 *  copy; centralising here keeps the retry-action text in lockstep. */
export const TRY_AGAIN_BUTTON_LABEL = "Try again";
