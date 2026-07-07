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
 * - include: only files under tests/** matching *.test.{ts,tsx} so
 *   we ignore example.spec.ts-like accidents and the Next.js
 *   typecheck include path remains unaffected.
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
    include: ["tests/**/*.test.{ts,tsx}"],
    clearMocks: true,
  },
});
