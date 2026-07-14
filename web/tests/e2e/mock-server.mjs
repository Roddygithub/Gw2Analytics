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
// POST /api/v1/account (v0.2.0-api)
//   -> stub { world_id, world_name, world_population } (no
//      fixture file; the stub is hard-coded because the
//      /account page's E2E only renders the form -- it does
//      not exercise the POST flow, since a real GW2 v2 API key
//      would 401 against the gateway's auth chain). The stub
//      shape mirrors the ``AccountEnrichedOut`` schema in
//      apps/api/src/gw2analytics_api/schemas.py.
// POST /api/v1/uploads (v0.3.0-web)
//   -> stub { id, sha256, status: "pending" } (no fixture
//      file; same rationale as /account -- the /upload page's
//      E2E only renders the form, since a real .zevtc blob
//      would take 5-30s to parse and surface a useless error).
//      The stub shape mirrors the ``UploadCreatedResponse``
//      schema (the lean envelope; the full ``UploadOut`` is
//      fetched later via ``GET /api/v1/uploads/{id}`` -- which
//      is not exercised by the v0.8.8 e2e suite and therefore
//      not stubbed here).
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

  // GET or POST /api/v1/account (v0.2.0-api + v0.10.13 BFF) --
  // Bearer-protected world enrichment. Stub shape mirrors the
  // ``AccountEnrichedOut`` schema. The BFF proxy (plan 013) calls
  // GET; the original client-side page called POST. Both return
  // the same stub.
  if ((method === "GET" || method === "POST") && path === "/api/v1/account") {
    return jsonResponse(
      res,
      200,
      JSON.stringify({
        world_id: 1001,
        world_name: "Fixture World",
        world_population: "Medium",
      }),
    );
  }

  // POST /api/v1/uploads (v0.3.0-web) -- multipart form-data
  // envelope. Stub shape mirrors the ``UploadCreatedResponse``
  // schema (the lean envelope; the full ``UploadOut`` is fetched
  // later via ``GET /api/v1/uploads/{id}`` -- which is not
  // exercised by the v0.8.8 e2e suite and therefore not stubbed
  // here). Status 201 because the real route returns 201 on a
  // successful envelope create.
  if (method === "POST" && path === "/api/v1/uploads") {
    return jsonResponse(
      res,
      201,
      JSON.stringify({
        id: "00000000-0000-0000-0000-000000000001",
        sha256:
          "0000000000000000000000000000000000000000000000000000000000000000",
        status: "pending",
      }),
    );
  }

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

    // /api/v1/fights/:id/timeline?window_s=N  (v0.8.9 plan/002).
    // Stub payload: 3 buckets of 5s each, total 15s of fight.
    // The hard-coded inline stub mirrors the canonical
    // ``PerFightTimelineOut`` shape: ``fight_id`` +
    // ``window_s`` + ``duration_s`` + ``points`` array of
    // ``{window_start_ms, window_end_ms, total_damage,
    // total_healing, total_buff_removal}``. We intentionally
    // do NOT load a fixture file (the schema is small + the
    // page-level E2E only asserts the section heading's
    // presence; the per-bucket content is covered by the
    // vitest unit tests).
    const fightTimelineMatch = path.match(/^\/api\/v1\/fights\/([^/]+)\/timeline$/);
    if (fightTimelineMatch) {
      const fightId = decodeURIComponent(fightTimelineMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "fight not found" }));
      }
      return jsonResponse(
        res,
        200,
        JSON.stringify({
          fight_id: fightId,
          window_s: 5,
          duration_s: 15.0,
          points: [
            {
              window_start_ms: 0,
              window_end_ms: 5_000,
              total_damage: 1_000,
              total_healing: 200,
              total_buff_removal: 50,
            },
            {
              window_start_ms: 5_000,
              window_end_ms: 10_000,
              total_damage: 3_000,
              total_healing: 100,
              total_buff_removal: 75,
            },
            {
              window_start_ms: 10_000,
              window_end_ms: 15_000,
              total_damage: 2_000,
              total_healing: 300,
              total_buff_removal: 25,
            },
          ],
        }),
      );
    }

    // Tour 4 v0.10.13 plan 044: per-player skill roll-up +
    // loadout attribution on ``/fights/[id]?account=...``. Two
    // NEW endpoints:
    //
    // - ``GET /api/v1/fights/:id/players/:account/skills``
    //   returns the ``PlayerSkills`` payload (per-player per-skill
    //   attribution + loadout header). A 1-row pixel-fits-everything
    //   stub for ``TestAccount.1234`` so the Playwright spec
    //   can exercise the happy-path dropdown selection. Unknown
    //   accounts 404 per the backend's canonical contract.
    //
    // - ``GET /api/v1/fights/:id`` (bare, after all the
    //   sub-path handlers ABOVE this block) returns a minimal
    //   ``FightOut`` with the agents list. The agents list is
    //   the ONLY field the per-player dropdown consults from
    //   this endpoint -- the dropdown filters for ``is_player
    //   === true && account_name !== null`` and renders a
    //   label ``"{name} ({account_name})"`` for each. One
    //   NPC + two player agents so the dropdown has multiple
    //   options on the Playwright spec.
    //
    // Declaration order: the bare ``:id`` catch-all MUST be
    // the LAST ``/api/v1/fights/`` route in this function so
    // it doesn't consume the more-specific ``:id/events`` +
    // ``:id/squads`` + ``:id/skills`` + ``:id/timeline`` +
    // ``:id/players/:account/skills`` handlers above.
    const playerSkillsMatch = path.match(
      /^\/api\/v1\/fights\/([^/]+)\/players\/([^/]+)\/skills$/,
    );
    if (playerSkillsMatch) {
      const fightId = decodeURIComponent(playerSkillsMatch[1]);
      const accountName = decodeURIComponent(playerSkillsMatch[2]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "fight not found" }));
      }
      if (accountName !== "TestAccount.1234") {
        return jsonResponse(
          res,
          404,
          JSON.stringify({ error: "player not found in fight" }),
        );
      }
      return jsonResponse(
        res,
        200,
        JSON.stringify({
          fight_id: fightId,
          account_name: accountName,
          agent_id: 1234,
          loadout: {
            profession: "Warrior",
            elite_spec: "Berserker",
            equipped_skill_ids: [],
          },
          skills: [
            {
              skill_id: 100,
              skill_name: "Whirlwind",
              hit_count: 2,
              total_damage: 3000,
              total_healing: 0,
              total_buff_removal: 0,
            },
          ],
        }),
      );
    }

    if (path === "/api/v1/players") {
      const body = await loadFixture("players-list.json");
      return jsonResponse(res, 200, body);
    }

    // v0.10.0 plan 032: ``GET /api/v1/players/compare/timeline``
    // with a repeatable ``?accounts=`` query param. The
    // handler MUST be declared BEFORE the
    // ``/api/v1/players/:name`` catch-all so the
    // ``/compare/timeline`` path segment is not consumed
    // as an ``account_name`` value. The fixture serves the
    // canonical 2-account payload (``TestAccount.1234`` +
    // ``TestAccount.5678``); an ``?accounts=`` value that
    // does not match a known fixture account falls through
    // to the catch-all (404) per the canonical "unknown
    // account" contract.
    const compareMatch = path.match(
      /^\/api\/v1\/players\/compare\/timeline$/,
    );
    if (compareMatch) {
      const requestedAccounts = url.searchParams.getAll("accounts");
      const validAccounts = new Set([
        "TestAccount.1234",
        "TestAccount.5678",
      ]);
      const allValid = requestedAccounts.every((a) => validAccounts.has(a));
      if (!allValid) {
        return jsonResponse(
          res,
          422,
          JSON.stringify({ error: "unknown account in compare request" }),
        );
      }
      const body = await loadFixture("cross-account-timeline.json");
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

    // Tour 4: ``GET /api/v1/fights/:id`` bare-identifier fetch
    // for the per-player dropdown. Declared AFTER every other
    // ``/api/v1/fights/`` sub-path handler ABOVE so the regex
    // collapses into the catch-all freely without consuming
    // the more-specific routes. The agents stub has 1 NPC
    // (``is_player: false``) + 2 player agents
    // (``TestAccount.1234`` + ``TestAccount.5678``) so the
    // dropdown's pre-filter (``is_player === true &&
    // account_name !== null``) leaves 2 options on the
    // Playwright spec.
    const fightBareMatch = path.match(/^\/api\/v1\/fights\/([^/]+)$/);
    if (fightBareMatch) {
      const fightId = decodeURIComponent(fightBareMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "fight not found" }));
      }
      return jsonResponse(
        res,
        200,
        JSON.stringify({
          id: fightId,
          build_version: "20250714-123456",
          encounter_id: 1,
          agent_count: 3,
          started_at: "2026-07-14T12:00:00Z",
          game_type: 4,
          agents: [
            {
              agent_id: 9001,
              name: "World Boss",
              profession: "None",
              elite_spec: "None",
              is_player: false,
              account_name: null,
              subgroup: null,
            },
            {
              agent_id: 1234,
              name: "Fighty McFight",
              profession: "Warrior",
              elite_spec: "Berserker",
              is_player: true,
              account_name: "TestAccount.1234",
              subgroup: "1",
            },
            {
              agent_id: 5678,
              name: "Heal Bot",
              profession: "Guardian",
              elite_spec: "Firebrand",
              is_player: true,
              account_name: "TestAccount.5678",
              subgroup: "2",
            },
          ],
          skills: [],
        }),
      );
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
