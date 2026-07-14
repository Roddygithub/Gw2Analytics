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
