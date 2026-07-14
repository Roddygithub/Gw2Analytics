/**
 * SkillUsageTable column headers + empty-state fallback. Renders the
 * per-skill roll-up table on the `/fights/[id]` page (the CSV column
 * spec is the same set of strings).
 *
 * v0.10.22-night-mode deliverable: extracted from
 * `@/lib/copy/error-messages.ts` when the kitchen-sink expanded to
 * 257 LoC + 44 exports across 4 unrelated concerns. Each
 * SkillUsageTable.tsx import now points at THIS module -- the type
 * system enforces that any future column header is declared here AND
 * imported here, NOT the kitchen-sink catch-all module.
 *
 * Sibling to the 3 other `@/lib/copy/*` sub-modules:
 *
 *   - @/lib/copy/error-messages        (error / loading / affordance)
 *   - @/lib/copy/fights-grid           (FightsGrid AG Grid column headers)
 *   - @/lib/copy/skill-usage-table     (THIS file -- SkillUsageTable headers + empty state)
 *   - @/lib/copy/player-timeline       (PlayerTimelineSection controls)
 */

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
