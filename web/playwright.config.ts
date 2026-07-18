import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the Next.js 16 frontend.
 *
 * Why two ``webServer`` entries
 * =============================
 * Phase 9 (v0.7.1 web) adds 3 Server Component pages
 * (``/players``, ``/players/[account_name]``,
 * ``/fights/[id]``) that call the v0.7.0-api gateway
 * endpoints at request time. Playwright's ``page.route()``
 * only intercepts browser-side ``fetch`` calls; Server
 * Component data fetching happens in Next.js's Node.js
 * process during SSR, so route interception cannot reach
 * it. The cleanest solution is a local mock HTTP server
 * (``tests/e2e/mock-server.mjs``) bound to port 8080 that
 * serves the same JSON shapes the real gateway returns, and
 * to point ``API_BASE_URL`` at it via the Next.js dev
 * server's environment. This isolates the E2E turn from
 * the real backend (no Postgres, no MinIO, no FastAPI
 * process) while still exercising the full HTTP + RSC
 * pipeline.
 *
 * CI vs local
 * ===========
 * ``reuseExistingServer: !process.env.CI`` lets a local dev
 * re-use a manually-started ``pnpm dev`` and ``node
 * tests/e2e/mock-server.mjs`` for fast iteration; in CI both
 * are spawned fresh per test run.
 *
 * Why a single chromium project
 * =============================
 * The mock server is process-wide state; running against
 * firefox / webkit in parallel would just multiply the
 * load without surfacing new bugs (the only browser quirks
 * that matter for our app are the AG Grid + the inline SVG
 * chart, both of which chromium exercises).
 */
const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 2 : undefined,
  // Use the HTML reporter in CI so the post-mortem is
  // available as a downloadable artifact (see
  // ``Upload Playwright report on failure`` in
  // ``.github/workflows/ci.yml``). The local loop keeps the
  // ``list`` reporter for fast iteration. The HTML report is
  // written to ``playwright-report/`` (relative to the
  // playwright project root, i.e. ``web/``) by default.
  reporter: isCI ? "html" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      // Exclude the visual-regression spec from the default
      // project; it has its own dedicated project below and is
      // only run in PRs. Without this exclusion, the chromium
      // project would also execute visual-regression.spec.ts
      // because the project-level grep only filters *within* the
      // visual-regression project, not across projects.
      grepInvert: /visual regression/,
      use: { ...devices["Desktop Chrome"] },
    },
    // v0.8.9 plan/003: a second project that ONLY runs the
    // visual-regression spec (filtered by the ``grep: /visual
    // regression/`` regex on the describe-block title). The
    // default ``pnpm exec playwright test`` invocation (without
    // ``--project=visual-regression``) skips the visual
    // regression suite so the fast local loop (and the existing
    // PR's "Playwright E2E tests" CI step) stays under the
    // ~30 s budget. CI runs the visual-regression suite
    // explicitly via a separate step gated on
    // ``github.event_name == 'pull_request'`` (PRs only) so
    // pushes to ``main`` don't pay the extra ~2-4 s of browser
    // time for the 8 full-page screenshots.
    {
      name: "visual-regression",
      grep: /visual regression/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "node tests/e2e/mock-server.mjs",
      port: 8080,
      reuseExistingServer: !isCI,
      timeout: 30_000,
    },
    {
      // In CI, build a production bundle and start it
      // (deterministic, no hot-reload races, no AG Grid
      // hydration flakiness from the dev-mode warning
      // suppressions). In local dev, fall back to
      // ``pnpm run dev`` for the fast-iteration loop
      // (HMR + source maps + TS error overlay).
      command: isCI
        ? "pnpm run build && PORT=3000 node .next/standalone/server.js"
        : "pnpm run dev",
      port: 3000,
      reuseExistingServer: !isCI,
      timeout: 180_000,
      env: {
        // Tell the Next.js server to fetch from the mock
        // server on the loopback. ``.replace(/\\/+$/, "")`` in
        // ``src/lib/env.ts`` is a no-op here (no trailing
        // slash) but the convention is to keep the env var
        // canonical. Client-side ``/api/v1/*`` requests are
        // rewritten to this same gateway URL via
        // ``next.config.ts`` rewrites.
        API_BASE_URL: "http://127.0.0.1:8080",
      },
    },
  ],
});
