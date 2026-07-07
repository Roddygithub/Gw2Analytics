#!/usr/bin/env node
// Mock HTTP server for Playwright E2E. Serves the v0.7.0-api
// JSON shapes from static fixtures so the Next.js 16 Server
// Components can fetch from a real HTTP endpoint (without the
// real FastAPI backend + Postgres + MinIO stack).
//
// Why a dedicated mock server (vs page.route() interception)
// ==========================================================
// Phase 9 web pages are Server Components that fetch at request
// time, BEFORE the browser receives the HTML. Playwright's
// page.route() runs in the browser context and cannot reach
// those SSR fetches. A small Node.js HTTP server is the
// minimal viable substitute: it gives the fetcher a real
// network round-trip (full URL parse, status code, response
// body) without bringing up the full backend stack.
//
// Endpoints
// =========
// GET /api/v1/fights
//   -> tests/e2e/fixtures/fights-list.json
// GET /api/v1/fights/:id/events?window_s=N
//   -> tests/e2e/fixtures/fight-events.json
// GET /api/v1/fights/:id/squads
//   -> tests/e2e/fixtures/fight-squads.json
// GET /api/v1/fights/:id/skills
//   -> tests/e2e/fixtures/fight-skills.json
// GET /api/v1/players?limit=N&offset=N
//   -> tests/e2e/fixtures/players-list.json
// GET /api/v1/players/:name
//   -> tests/e2e/fixtures/player-profile.json (when name is
//      "TestAccount.1234") or 404 (when name is "missing.9999")
// GET /api/v1/players/:name/timeline?limit=N&offset=M
//   -> tests/e2e/fixtures/player-timeline.json (when name is
//      in KNOWN_TIMELINE_PLAYERS -- currently just
//      "TestAccount.1234") or 404 (for any other known player,
//      including "empty-history.5678" whose profile returns
//      200 but whose timeline is hard-coded to 404 so the
//      page exercises the synthetic-empty rendering path)
// GET /api/v1/players/:name/special/404
//   -> always 404 (used by the profile-page error test)
//
// Lifecycle
// =========
// Spawned by Playwright's ``webServer`` block. Prints a single
// line on listen so the test runner can confirm the process is
// up. Cleanly closes on SIGTERM / SIGINT for fast re-runs.

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const FIXTURES = join(__dirname, "fixtures");

const PORT = Number.parseInt(process.env.MOCK_PORT ?? "8080", 10);

async function loadFixture(name) {
  return readFile(join(FIXTURES, name), "utf8");
}

const KNOWN_FIGHTS = new Set(["fixture-fight-001", "fixture-fight-002"]);
const KNOWN_PLAYERS = new Set([
  "TestAccount.1234",
  "TestAccount.5678",
  "TestAccount.9999",
  // ``empty-history.5678`` is a synthetic player used by the
  // v0.8.0 timeline-empty E2E: the profile endpoint returns
  // 200 (the alt fixture) so the page renders the normal
  // chrome, but the timeline endpoint returns 404 (see
  // ``KNOWN_TIMELINE_PLAYERS`` below) so the page exercises
  // the synthetic-empty rendering path ("Showing 0 of 0
  // fights" + the chart's empty-state panel).
  "empty-history.5678",
]);
// Subset of KNOWN_PLAYERS that have a non-empty timeline
// fixture. The v0.8.0 timeline endpoint returns 200 for
// players in this set, 404 for everyone else (including
// ``empty-history.5678`` -- the profile endpoint returns 200
// but the timeline endpoint returns 404 so the page exercises
// the synthetic-empty rendering path). Keeping this separate
// from KNOWN_PLAYERS avoids mixing the "is this player
// known?" and "does this player have a timeline?" concerns.
const KNOWN_TIMELINE_PLAYERS = new Set(["TestAccount.1234"]);

function jsonResponse(res, status, body) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(body);
}

const server = createServer(async (req, res) => {
  // ``req.url`` carries the path + query; ``req.method`` is
  // uppercase. Normalize once at the top.
  const url = new URL(req.url ?? "/", "http://localhost");
  const path = url.pathname;
  const method = req.method ?? "GET";

  if (method !== "GET") {
    return jsonResponse(res, 405, JSON.stringify({ error: "method not allowed" }));
  }

  try {
    if (path === "/api/v1/fights") {
      const body = await loadFixture("fights-list.json");
      return jsonResponse(res, 200, body);
    }

    // /api/v1/fights/:id/events?window_s=N
    const eventsMatch = path.match(/^\/api\/v1\/fights\/([^/]+)\/events$/);
    if (eventsMatch) {
      const fightId = decodeURIComponent(eventsMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "fight not found" }));
      }
      const body = await loadFixture("fight-events.json");
      return jsonResponse(res, 200, body);
    }

    // /api/v1/fights/:id/squads
    const squadsMatch = path.match(/^\/api\/v1\/fights\/([^/]+)\/squads$/);
    if (squadsMatch) {
      const fightId = decodeURIComponent(squadsMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "fight not found" }));
      }
      const body = await loadFixture("fight-squads.json");
      return jsonResponse(res, 200, body);
    }

    // /api/v1/fights/:id/skills
    const skillsMatch = path.match(/^\/api\/v1\/fights\/([^/]+)\/skills$/);
    if (skillsMatch) {
      const fightId = decodeURIComponent(skillsMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "fight not found" }));
      }
      const body = await loadFixture("fight-skills.json");
      return jsonResponse(res, 200, body);
    }

    if (path === "/api/v1/players") {
      const body = await loadFixture("players-list.json");
      return jsonResponse(res, 200, body);
    }

    // /api/v1/players/:name/timeline  (v0.8.0). MUST be matched
    // BEFORE the catch-all /api/v1/players/:name handler --
    // otherwise the catch-all would consume
    // ``/api/v1/players/TestAccount.1234/timeline`` with
    // ``name="TestAccount.1234/timeline"`` and return 404. The
    // query string is ignored: the static fixture carries the
    // canonical "all 2 points" payload (the page tests only
    // assert the initial render; the Client Component's "Load
    // more" pagination is covered by the vitest unit tests).
    //
    // The handler uses ``KNOWN_TIMELINE_PLAYERS`` (a subset of
    // ``KNOWN_PLAYERS``) to decide 200 vs 404. This keeps the
    // "is this player known?" and "does this player have a
    // timeline?" concerns separate: ``empty-history.5678`` is
    // in KNOWN_PLAYERS (so the profile endpoint returns 200)
    // but NOT in KNOWN_TIMELINE_PLAYERS (so the timeline
    // endpoint returns 404, exercising the synthetic-empty
    // rendering path on the page).
    const timelineMatch = path.match(/^\/api\/v1\/players\/([^/]+)\/timeline$/);
    if (timelineMatch) {
      const name = decodeURIComponent(timelineMatch[1]);
      if (!KNOWN_TIMELINE_PLAYERS.has(name)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "player not found" }));
      }
      const body = await loadFixture("player-timeline.json");
      return jsonResponse(res, 200, body);
    }

    // /api/v1/players/:name  (:path converter lets the name
    // contain /, so we take everything after the prefix as the
    // canonical name).
    if (path.startsWith("/api/v1/players/")) {
      const rawName = path.slice("/api/v1/players/".length);
      const name = decodeURIComponent(rawName);
      if (!KNOWN_PLAYERS.has(name)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "player not found" }));
      }
      const fixtureName = name === "TestAccount.1234"
        ? "player-profile.json"
        : "player-profile-alt.json";
      const body = await loadFixture(fixtureName);
      return jsonResponse(res, 200, body);
    }

    return jsonResponse(res, 404, JSON.stringify({ error: "not found" }));
  } catch (err) {
    return jsonResponse(
      res,
      500,
      JSON.stringify({ error: "fixture load failed", detail: String(err) }),
    );
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[mock-server] listening on http://127.0.0.1:${PORT}`);
});

const shutdown = (sig) => {
  console.log(`[mock-server] received ${sig}, closing`);
  server.close(() => process.exit(0));
};
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
