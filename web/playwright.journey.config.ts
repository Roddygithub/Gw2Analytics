import { defineConfig, devices } from "@playwright/test";

/**
 * Dedicated Playwright config for the REAL-backend E2E user journey
 * (web/e2e/user-journey.spec.ts). NOT part of the default test run.
 *
 * Unlike the default `playwright.config.ts` (which points Next.js at the
 * tests/e2e mock server), this runs against a LIVE stack: FastAPI +
 * Postgres + MinIO + a `next dev` pointed at the real API. It is OFF by
 * default — the spec self-skips unless the stack is reachable and a real
 * `.zevtc` is provided (see web/e2e/README.md).
 *
 * There is intentionally no `webServer` block: the stack is booted
 * out-of-band (a `webServer` with `reuseExistingServer` would *error*
 * rather than *skip* when the stack is down; the spec's reachability
 * probe skips cleanly instead).
 *
 * Run: `pnpm exec playwright test --config playwright.journey.config.ts`
 */
const STACK_URL = process.env.E2E_STACK_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  // Ignore Vitest unit tests that live alongside the Playwright specs
  // (e.g. e2e/helpers/*.test.ts). Playwright's default testMatch picks
  // up *.test.ts files, which would fail because they import vitest.
  testIgnore: ["e2e/helpers/**/*.test.ts"],
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: STACK_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
