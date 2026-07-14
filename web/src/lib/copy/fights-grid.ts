/**
 * AG Grid column headers for the FightsGrid component
 * (the read-only fights-list table on `/fights`).
 *
 * v0.10.22-night-mode deliverable: extracted from
 * `@/lib/copy/error-messages.ts` when the kitchen-sink module approached
 * 257 LoC + 44 exports across 4 unrelated concerns. Each FightsGrid.tsx
 * import now points at THIS module -- the type system enforces that any
 * future AG Grid column is declared here AND imported here, NOT the
 * kitchen-sink catch-all module.
 *
 * Sibling to the 3 other `@/lib/copy/*` sub-modules:
 *
 *   - @/lib/copy/error-messages        (error / loading / affordance)
 *   - @/lib/copy/fights-grid           (THIS file -- AG Grid column headers)
 *   - @/lib/copy/skill-usage-table     (SkillUsageTable headers + empty state)
 *   - @/lib/copy/player-timeline       (PlayerTimelineSection controls)
 */

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
