import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);

// v0.10.30 UI harmonization: the theme mirrors the app tokens in
// ``web/src/app/globals.css`` (--background / --foreground /
// --accent / --border / --surface) so the grids read as part of
// the same surface as the surrounding pages, not as a detached
// component. The values live here as literals because AG Grid
// themes can't read CSS custom properties at theme-build time.
export const appGridTheme = themeQuartz.withParams({
  backgroundColor: "#050914",
  foregroundColor: "#ffffff",
  accentColor: "#ff8c2a",
  chromeBackgroundColor: "#070b14",
  headerBackgroundColor: "#0b1120",
  headerTextColor: "#ffffff",
  borderColor: "#1f2733",
  rowHoverColor: "#ffffff08",
  selectedRowBackgroundColor: "#1f2733",
});

// v0.10.30 UI harmonization: restore the browser's native text
// selection + copy inside the grids. AG Grid replaces the default
// browser behaviour with its own cell-selection model, so dragging
// across a grid's text and Ctrl+C (or copy-pasting along with the
// rest of the page) silently does nothing. ``enableCellTextSelection``
// switches back to plain DOM text selection and ``ensureDomOrder`` is
// the documented pairing (keeps the DOM row order in sync with the
// displayed order so selection + accessibility stay correct).
export const appGridOptions = {
  enableCellTextSelection: true,
  ensureDomOrder: true,
};
