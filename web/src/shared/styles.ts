/**
 * Shared React.CSSProperties constants used across the web UI.
 *
 * Centralising these patterns reduces duplication between
 * components (grids wrappers, section headers, filters, etc.)
 * and makes visual tweaks single-point-of-change. Each constant
 * is a plain object so it can be spread/extended at the call
 * site when a component needs a small override.
 */

/** Empty-state panel (e.g. "No rows.") */
export const EMPTY_STYLE: React.CSSProperties = {
  padding: "12px 16px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  color: "var(--foreground)",
  opacity: 0.7,
  fontSize: 14,
};

/** Vertical flex stack that spans its container. */
export const FLEX_COLUMN_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  width: "100%",
};

/** Horizontal flex row aligned to the end. */
export const FLEX_END_STYLE: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
};

/** AG Grid / table wrapper. Height is parameterised because
 *  each grid has a different desired height. */
export const gridContainerStyle = (height: number): React.CSSProperties => ({
  height,
  width: "100%",
});

/** Inline link using the theme accent colour. */
export const LINK_STYLE: React.CSSProperties = {
  color: "var(--accent)",
};

/** Section wrapper used by timeline / compare sections. */
export const SECTION_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

/** Header row with heading on the left and controls on the right. */
export const HEADER_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  flexWrap: "wrap",
};

/** Section heading (h2). */
export const HEADING_STYLE: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 600,
};

/** Horizontal row of controls (buttons, selects, captions). */
export const CONTROLS_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  flexWrap: "wrap",
};

/** Tight inline group of radio/toggle buttons. */
export const RADIO_GROUP_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 4,
};

/** Accent-themed dropdown used by timeline / compare controls. */
export const SELECT_STYLE: React.CSSProperties = {
  padding: "4px 8px",
  fontSize: 12,
  border: "1px solid var(--accent)",
  borderRadius: 4,
  background: "transparent",
  color: "var(--accent)",
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
  cursor: "pointer",
};

/** Caption text below headings or inside controls. */
export const CAPTION_STYLE: React.CSSProperties = {
  fontSize: 12,
  opacity: 0.7,
  fontFamily: "var(--font-geist-sans), Arial, Helvetica, sans-serif",
};

/** Row containing the "Load more" button and optional error. */
export const LOAD_MORE_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
};

/** Inline-flex label used by filter dropdowns. */
export const LABEL_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  fontSize: 14,
  color: "var(--foreground)",
  opacity: 0.85,
};

/** Search / form row. */
export const FORM_STYLE: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
};

/** Text input used by the player search bar. */
export const INPUT_STYLE: React.CSSProperties = {
  padding: "4px 8px",
  fontSize: 13,
  fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
  background: "var(--background)",
  color: "var(--foreground)",
  border: "1px solid var(--border)",
  borderRadius: 4,
  minWidth: 200,
};

/** Accent-filled button used by the player search bar. */
export const BUTTON_STYLE: React.CSSProperties = {
  padding: "4px 12px",
  fontSize: 13,
  background: "var(--accent)",
  color: "var(--background)",
  border: "none",
  borderRadius: 4,
};
