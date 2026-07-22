import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";

ModuleRegistry.registerModules([AllCommunityModule]);

export const appGridTheme = themeQuartz.withParams({
  backgroundColor: "#050914",
  foregroundColor: "#ffffff",
  accentColor: "#ff8c2a",
  chromeBackgroundColor: "#161b22",
  borderColor: "#1f2733",
});
