import { defineConfig } from "vitest/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * vitest config for the Next.js 16 frontend.
 *
 * - environment: jsdom so Server / Client components can render the
 *   React tree the same way the dev server does.
 * - setupFiles: register global vi.mock shims for next/link,
 *   next/font/google and @/lib/env, plus extend expect via
 *   @testing-library/jest-dom/vitest.
 * - alias @/* -> src/* mirrors the root tsconfig compilerOptions.paths
 *   so test imports like `@/app/layout` resolve identically to the
 *   real build.
 * - css: false — Next.js owns stylable output; the unit tests don't
 *   need vitest's CSS pipeline.
 * - include: files under tests/** and e2e/helpers/** matching
 *   *.test.{ts,tsx}. The e2e/helpers tests are pure unit tests for
 *   the real-stack E2E helpers; Playwright specs under e2e/*.spec.ts
 *   are intentionally excluded so Vitest does not try to run them.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    css: false,
    include: ["tests/**/*.test.{ts,tsx}", "e2e/helpers/**/*.test.{ts,tsx}"],
    clearMocks: true,
    // ``globals: true`` makes ``describe`` / ``it`` / ``expect`` /
    // ``beforeEach`` / ``afterEach`` available without per-test
    // imports. The page / layout tests rely on these (the
    // jsdom-simulated React tree mounts via ``describe`` blocks).
    globals: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary"],
      // Exclude generated OpenAPI client code and test harness files
      // from coverage thresholds. The schema file is auto-generated
      // from the FastAPI spec; the API wrapper modules are thin
      // fetch() callers that are better covered by E2E tests.
      exclude: [
        "src/lib/api/**",
        "tests/**",
        "*.config.{js,ts}",
        ".next/**",
      ],
      thresholds: {
        // Baseline measured on 2026-07-15 with src/lib/api excluded.
        // Raise these incrementally as component coverage improves.
        lines: 65,
        branches: 80,
        functions: 70,
      },
    },
  },
});
