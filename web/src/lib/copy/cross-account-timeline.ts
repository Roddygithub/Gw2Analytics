/**
 * CrossAccountCompareSection + CrossAccountTimelineChart -- section-level
 * aria-label + heading + account-chips list + metric / scale / bucket / TZ
 * toggle group + chart legend + empty-state fallback.
 *
 * v0.10.22-night-mode-2 deliverable: extracted from the inline literals in
 * `web/src/components/CrossAccountCompareSection.tsx` + the chart-level
 * `METRIC_LABEL` mapping in `web/src/components/CrossAccountTimelineChart.tsx`
 * when the multi-account timeline added 26+ inline analyst-facing strings
 * (compounding the kitchen-sink). Each Cross-Account TSX import now points
 * at THIS module -- the type system enforces that any future multi-account
 * affordance is declared here AND imported here, NOT pollute another scope.
 *
 * Sibling to the 4 other `@/lib/copy/*` sub-modules:
 *
 *   - @/lib/copy/error-messages        (error / loading / affordance)
 *   - @/lib/copy/fights-grid           (FightsGrid AG Grid column headers)
 *   - @/lib/copy/skill-usage-table     (SkillUsageTable headers + empty state)
 *   - @/lib/copy/player-timeline       (PlayerTimelineSection controls)
 *   - @/lib/copy/cross-account-timeline (THIS file -- CrossAccountCompareSection + chart)
 *
 * String duplication contract vs PlayerTimelineSection
 * ====================================================
 * Some strings DUPLICATE the player-timeline prefix (e.g., "Per fight",
 * "Linear", "Day-bucket timezone (region/city)", "Timeline controls") --
 * but each scope has its OWN constant. Rationale:
 *
 *   - Single-concern parity: per-component copy module ownership.
 *   - Future divergence: if a per-account affordance gets reworded for
 *     a UX reason, the cross-account copy stays in lockstep from its
 *     own constant (NOT silently inherits from the other scope).
 *   - Type-system enforcement: a CrossAccountCompareSection that
 *     accidentally imports PLAYER_TIMELINE_PER_FIGHT from the wrong
 *     sub-module is a TYPECHECK error -- the linter catches the
 *     scope-cross before any UI rendering.
 */

/** Section-level aria-label for the <section aria-label> wrapper of
 *  ``CrossAccountCompareSection``. */
export const CROSS_ACCOUNT_TIMELINE_SECTION_ARIA_LABEL = "Cross-account comparison timeline";

/** Section-level <h2> heading text. Rendered at the top-left of the section. */
export const CROSS_ACCOUNT_TIMELINE_HEADING = "Comparison timeline";

/** Account-chips list ``role="list"`` aria-label -- the read-only account
 *  name chips rendered below the heading. */
export const CROSS_ACCOUNT_TIMELINE_CHIPS_ARIA_LABEL = "Accounts in comparison";

/** Toggle group ``role="group"`` aria-label for the controls row (metric +
 *  scale + bucket + TZ). */
export const CROSS_ACCOUNT_TIMELINE_CONTROLS_ARIA_LABEL = "Timeline controls";

/** Metric radiogroup ``role="radiogroup"`` aria-label -- the Damage / Healing /
 *  Strip radio buttons. */
export const CROSS_ACCOUNT_TIMELINE_METRIC_GROUP_ARIA_LABEL = "Comparison metric";

/** ``aria-label`` for the Damage metric radio button. Same lowercase form
 *  as the engine's ``"damage"`` metric value for parallelism. */
export const CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_ARIA_LABEL = "damage metric";

/** ``aria-label`` for the Healing metric radio button. */
export const CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_ARIA_LABEL = "healing metric";

/** ``aria-label`` for the Strip metric radio button. */
export const CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_ARIA_LABEL = "strip metric";

/** Damage metric radio button text. Display label. */
export const CROSS_ACCOUNT_TIMELINE_METRIC_DAMAGE_LABEL = "Damage";

/** Healing metric radio button text. Display label. */
export const CROSS_ACCOUNT_TIMELINE_METRIC_HEALING_LABEL = "Healing";

/** Strip metric radio button text. Display label (NOTE: distinct from the
 *  chart's "Buff removal" display name -- the radio button uses the
 *  short form, the chart uses the long-form for clarity in the
 *  trend-line caption). */
export const CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_LABEL = "Strip";

/** Strip metric chart-display label. The chart caption reads "Buff removal
 *  trend · shared log scale · max 50k"; the longer-form gives the analyst
 *  an unambiguous context compared to the radio button's terse "Strip". */
export const CROSS_ACCOUNT_TIMELINE_METRIC_STRIP_CHART_LABEL = "Buff removal";

/** Scale-toggle group ``role="group"`` aria-label -- the Linear / Log
 *  buttons. */
export const CROSS_ACCOUNT_TIMELINE_SCALE_GROUP_ARIA_LABEL = "Y-axis scale";

/** ``aria-label`` for the Linear scale-toggle button (full text describes
 *  the visual + behaviour). */
export const CROSS_ACCOUNT_TIMELINE_LINEAR_BUTTON_ARIA_LABEL = "Linear Y-axis scale";

/** ``aria-label`` for the Log scale-toggle button (full text). */
export const CROSS_ACCOUNT_TIMELINE_LOG_BUTTON_ARIA_LABEL = "Logarithmic Y-axis scale";

/** Linear scale-toggle button text. */
export const CROSS_ACCOUNT_TIMELINE_LINEAR = "Linear";

/** Log scale-toggle button text. */
export const CROSS_ACCOUNT_TIMELINE_LOG = "Log";

/** Bucket-toggle group ``role="group"`` aria-label -- the Per-fight /
 *  Per-day buttons. NOTE: distinct from PlayerTimelineSection's
 *  "Timeline bucketing" -- the cross-account uses the shorter-form
 *  "Bucketing" because the surrounding controls group is already
 *  labelled "Timeline controls". */
export const CROSS_ACCOUNT_TIMELINE_BUCKETING_GROUP_ARIA_LABEL = "Bucketing";

/** ``aria-label`` for the Per-fight bucket-toggle button. */
export const CROSS_ACCOUNT_TIMELINE_BUCKET_PER_FIGHT_ARIA_LABEL = "Per-fight bucketing";

/** ``aria-label`` for the Per-day bucket-toggle button. */
export const CROSS_ACCOUNT_TIMELINE_BUCKET_PER_DAY_ARIA_LABEL = "Per-day bucketing";

/** Per-fight bucket-toggle button text. */
export const CROSS_ACCOUNT_TIMELINE_BUCKET_PER_FIGHT = "Per fight";

/** Per-day bucket-toggle button text. */
export const CROSS_ACCOUNT_TIMELINE_BUCKET_PER_DAY = "Per day";

/** TZ-toggle group ``role="group"`` aria-label -- the timezone <select>.
 *  Distinct from PlayerTimelineSection's "Timeline timezone" -- the
 *  cross-account uses the explicit "(day-bucketing)" suffix so the
 *  analyst sees WHICH mode the TZ affects without needing to look
 *  at the bucket toggle state. */
export const CROSS_ACCOUNT_TIMELINE_TIMEZONE_GROUP_ARIA_LABEL = "Timezone (day-bucketing)";

/** TZ selector ``aria-label`` (Day-bucket region/city picker). Same value
 *  as PlayerTimelineSection's TZ selector aria-label so screen-readers
 *  read BOTH selectors identically -- but each scope has its OWN
 *  constant to preserve the per-component single-concern invariant. */
export const CROSS_ACCOUNT_TIMELINE_TZ_SELECTOR_ARIA_LABEL = "Day-bucket timezone (region/city)";

/** Account legend ``role="list"`` aria-label -- the categorical
 *  color-coded account name list rendered above the chart. */
export const CROSS_ACCOUNT_TIMELINE_LEGEND_ARIA_LABEL = "Account legend";

/** Empty-state fallback when the chart has zero timeline points (the
 *  ``series`` array is empty OR the timeline fetch returned no data
 *  for any of the selected accounts). */
export const CROSS_ACCOUNT_TIMELINE_EMPTY_STATE = "No timeline data available for comparison.";
