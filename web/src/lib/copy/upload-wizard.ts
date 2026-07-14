/**
 * Upload wizard -- 5 aria-labels for the step-by-step file upload flow
 * (`web/src/app/upload/page.tsx`).
 *
 * v0.10.22-night-mode-2 deliverable: extracted from inline `aria-label="..."`
 * literals in the upload page when the surface-scanner scope-drop surfaced
 * them as non-allowlisted residues. Each upload page import now points
 * at THIS module -- the type system enforces that any future wizard step
 * label is declared here AND imported here, NOT inlined.
 *
 * Sibling to the 5 other `@/lib/copy/*` sub-modules:
 *
 *   - @/lib/copy/error-messages        (error / loading / affordance)
 *   - @/lib/copy/fights-grid           (FightsGrid AG Grid column headers)
 *   - @/lib/copy/skill-usage-table     (SkillUsageTable headers + empty state)
 *   - @/lib/copy/player-timeline       (PlayerTimelineSection controls)
 *   - @/lib/copy/cross-account-timeline (CrossAccountCompareSection + chart)
 *   - @/lib/copy/upload-wizard         (THIS file -- upload wizard aria-labels)
 *
 * Each step is a sibling constant -- the wizard flow is "Step 1 -> Step 2
 * -> Step 3 -> complete" and each step's affordance has its own centraliSed
 * string for analyst-facing readability AND for screen-reader accuracy
 * (the wizard uses the literal "Step 1: choose a file" form rather than
 * a generic "Step N" to disambiguate the action per step).
 */

/** Wizard progress region ``aria-label`` -- the entire stepper's wrapper. */
export const UPLOAD_WIZARD_PROGRESS_ARIA_LABEL = "Upload wizard progress";

/** Step 1 ``aria-label`` -- the file picker step. */
export const UPLOAD_WIZARD_STEP_1_ARIA_LABEL = "Step 1: choose a file";

/** Step 2 ``aria-label`` -- the upload-in-progress step. */
export const UPLOAD_WIZARD_STEP_2_ARIA_LABEL = "Step 2: upload in progress";

/** Step 3 ``aria-label`` -- the parsing-in-progress step. */
export const UPLOAD_WIZARD_STEP_3_ARIA_LABEL = "Step 3: parsing in progress";

/** Wizard complete ``aria-label`` -- the success terminal state. */
export const UPLOAD_WIZARD_COMPLETE_ARIA_LABEL = "Upload complete";
