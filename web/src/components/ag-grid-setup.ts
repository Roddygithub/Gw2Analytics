/**
 * AG Grid Community 33+ ships in tree-shaken mode and requires an
 * explicit module registration. Each grid component in this app
 * imports this file -- the side effect runs once at module load
 * (TypeScript/Next.js guarantees a single evaluation of the module
 * graph), so ``ModuleRegistry.registerModules`` fires exactly once
 * no matter which grid component the user lands on first.
 *
 * Without this, a user who navigates directly to a fight-detail
 * page (and never visits ``/fights``) would see an unstyled grid
 * with broken sorting + filter because the AllCommunityModule
 * wouldn't have been registered. Centralising the registration
 * here removes that ordering hazard.
 *
 * NOTE: this file registers AG Grid modules as a side effect AND
 * exports the centralized ``appGridTheme`` used by every grid
 * component. Consumers should import ``appGridTheme`` from here so
 * the theme object is evaluated once and reused across the module
 * graph.
 */
import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);

/**
 * Centralised AG Grid 34+ theme using the new Theming API.
 *
 * The legacy ``ag-theme-quartz-dark`` CSS class + the
 * ``ag-grid-community/styles/ag-theme-quartz.css`` import are
 * replaced by a single ``themeQuartz.withParams`` object passed
 * to each ``<AgGridReact>`` via the ``theme`` prop. This removes
 * the console warning about mixing legacy CSS with the Theming
 * API and keeps the grid's colour tokens in sync with the rest of
 * the application.
 */
export const appGridTheme = themeQuartz.withParams({
  backgroundColor: "#050914",
  foregroundColor: "#ffffff",
  accentColor: "#ff8c2a",
  chromeBackgroundColor: "#161b22",
  borderColor: "#1f2733",
});
