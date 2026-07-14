/**
 * PlayerTimelineSection -- section-level aria-label + heading +
 * bucket toggle (Per fight / Per day) + Load-more / All-loaded
 * terminal-state + Linear/Log scale toggle + TZ selector.
 *
 * v0.10.22-night-mode deliverable: extracted from
 * `@/lib/copy/error-messages.ts` when the kitchen-sink expanded to
 * 257 LoC + 44 exports across 4 unrelated concerns. Each
 * PlayerTimelineSection.tsx import now points at THIS module -- the
 * type system enforces that any future control affordance is declared
 * here AND imported here, NOT the kitchen-sink catch-all module.
 *
 * Sibling to the 3 other `@/lib/copy/*` sub-modules:
 *
 *   - @/lib/copy/error-messages        (error / loading / affordance)
 *   - @/lib/copy/fights-grid           (FightsGrid AG Grid column headers)
 *   - @/lib/copy/skill-usage-table     (SkillUsageTable headers + empty state)
 *   - @/lib/copy/player-timeline       (THIS file -- PlayerTimelineSection controls)
 */

/** Section-level aria-label for the <section aria-label> wrapper of
 *  ``PlayerTimelineSection``. The "Per-account" prefix signals the per-account
 *  horizontal scope single-player UX (vs CrossAccountTimelineSection which
 *  reuses the same name in its own wrapper). */
export const PLAYER_TIMELINE_SECTION_ARIA_LABEL = "Per-account historical timeline";

/** Section-level <h2> heading text. Rendered at the top-left of the section. */
export const PLAYER_TIMELINE_HEADING = "Historical timeline";

/** Bucket toggle button text (Per-fight bucketing). Maps the engine's
 *  ``"fight"`` state value to the analyst-facing display string. */
export const PLAYER_TIMELINE_BUCKET_PER_FIGHT = "Per fight";

/** Bucket toggle button text (Per-day bucketing). Maps the engine's
 *  ``"day"`` state value to the analyst-facing display string. */
export const PLAYER_TIMELINE_BUCKET_PER_DAY = "Per day";

/** Load-more button primary action text. Rendered when `hasMore=true`. */
export const PLAYER_TIMELINE_LOAD_MORE = "Load more";

/** Load-more button `aria-label` when `hasMore=true`. */
export const PLAYER_TIMELINE_LOAD_MORE_ARIA_LABEL = "Load more timeline points";

/** Load-more button `aria-label` when `hasMore=false` (terminal state). */
export const PLAYER_TIMELINE_NO_MORE_ARIA_LABEL = "No more timeline points";

/** Button text rendered mid-fetch (during the `isLoading` toggle). */
export const PLAYER_TIMELINE_LOADING = "Loading\u2026";

/** Terminal state text when `bucket="day"` and no more pages. */
export const PLAYER_TIMELINE_ALL_LOADED_DAYS = "All days loaded";

/** Terminal state text when `bucket="fight"` (the default) and no more pages. */
export const PLAYER_TIMELINE_ALL_LOADED_FIGHTS = "All fights loaded";

/** Bucket-toggle button `aria-label` (Per-fight). */
export const PLAYER_TIMELINE_BUCKET_PER_FIGHT_ARIA_LABEL = "Per-fight bucketing";

/** Bucket-toggle button `aria-label` (Per-day). */
export const PLAYER_TIMELINE_BUCKET_PER_DAY_ARIA_LABEL = "Per-day bucketing";

/** Toggle group `aria-label` for the controls row (bucket + scale + TZ). */
export const PLAYER_TIMELINE_CONTROLS_ARIA_LABEL = "Timeline controls";

/** Bucket-toggle group `aria-label` (parent of the Per-fight / Per-day buttons). */
export const PLAYER_TIMELINE_BUCKETING_ARIA_LABEL = "Timeline bucketing";

/** Scale-toggle group `aria-label` (parent of the Linear / Log buttons). */
export const PLAYER_TIMELINE_Y_AXIS_SCALE_ARIA_LABEL = "Timeline Y-axis scale";

/** Scale-toggle button text (Linear; per-series normalised 0-100%). */
export const PLAYER_TIMELINE_LINEAR = "Linear";

/** Scale-toggle button `aria-label` (Linear; full text describes the visual + behaviour). */
export const PLAYER_TIMELINE_LINEAR_BUTTON_ARIA_LABEL = "Linear Y-axis scale (per-series normalised)";

/** Scale-toggle button text (Log; shared log Y-axis across the 3 series). */
export const PLAYER_TIMELINE_LOG = "Log";

/** Scale-toggle button `aria-label` (Log; full text). */
export const PLAYER_TIMELINE_LOG_BUTTON_ARIA_LABEL = "Logarithmic Y-axis scale (shared across all 3 series)";

/** TZ-toggle group `aria-label` (parent of the timezone <select>). */
export const PLAYER_TIMELINE_TIMEZONE_ARIA_LABEL = "Timeline timezone";

/** TZ selector `aria-label` (Day-bucket region/city picker). */
export const PLAYER_TIMELINE_TZ_SELECTOR_ARIA_LABEL = "Day-bucket timezone (region/city)";
