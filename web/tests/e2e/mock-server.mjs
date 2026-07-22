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
    const apiKey = process.env.GW2_API_KEY;
    if (apiKey) {
      try {
        const accCtrl = new AbortController();
        const accTimeout = setTimeout(() => accCtrl.abort(), 5_000);
        const accRes = await fetch(
          `https://api.guildwars2.com/v2/account?access_token=${encodeURIComponent(apiKey)}`,
          { signal: accCtrl.signal },
        );
        clearTimeout(accTimeout);
        if (!accRes.ok) {
          throw new Error(`GW2 /account returned HTTP ${accRes.status}`);
        }
        const accData = await accRes.json();
        const worldCtrl = new AbortController();
        const worldTimeout = setTimeout(() => worldCtrl.abort(), 5_000);
        const worldRes = await fetch(
          `https://api.guildwars2.com/v2/worlds?id=${encodeURIComponent(String(accData.world))}`,
          { signal: worldCtrl.signal },
        );
        clearTimeout(worldTimeout);
        if (!worldRes.ok) {
          throw new Error(`GW2 /worlds returned HTTP ${worldRes.status}`);
        }
        const worldData = await worldRes.json();
        if (!worldData || typeof worldData.name !== "string") {
          throw new Error("GW2 /worlds returned unexpected payload shape");
        }
        return jsonResponse(
          res,
          200,
          JSON.stringify({
            world_id: accData.world,
            world_name: worldData.name,
            world_population: worldData.population,
          }),
        );
      } catch (err) {
        console.warn(
          `[mock-server] LIVE GW2 fetch failed -- falling back to stub: ${err && err.message ? err.message : err}`,
        );
        // Fall through to the deterministic stub below so the E2E suite
        // and the analyst's screen remain stable even when the GW2 v2
        // API is unreachable or the key is revoked.
      }
    }
    return jsonResponse(res, 200, await loadFixture("account-stub.json"));
  }

  // POST /api/v1/uploads (v0.3.0-web) -- multipart form-data
  // envelope. Stub shape mirrors the ``UploadCreatedResponse``
  // schema (the lean envelope; the full ``UploadOut`` is fetched
  // later via ``GET /api/v1/uploads/{id}`` -- which is not
  // exercised by the v0.8.8 e2e suite and therefore not stubbed
  // here). Status 201 because the real route returns 201 on a
  // successful envelope create.
  if (method === "POST" && path === "/api/v1/uploads") {
    // Artificial delay: the mock server responds so fast that the
    // wizard's "upload" step (a transient spinner) flashes by
    // before Playwright can observe it. A 300ms delay simulates
    // realistic network latency and makes the
    // ``data-testid="step-upload"`` assertion deterministic in the
    // user-journey E2E spec.
    await new Promise((r) => setTimeout(r, 300));
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

  // GET /api/v1/uploads/:id (v0.3.0-web) -- polling endpoint for
  // the upload wizard. Returns a completed status with a known
  // fight id so the user-journey E2E can exercise the full
  // Pick -> Upload -> Parse -> Done flow and drill down into
  // ``/fights/:fight_id``.
  const uploadMatch = path.match(/^\/api\/v1\/uploads\/([^/]+)$/);
  if (method === "GET" && uploadMatch) {
    const uploadId = decodeURIComponent(uploadMatch[1]);
    if (uploadId !== "00000000-0000-0000-0000-000000000001") {
      return jsonResponse(res, 404, JSON.stringify({ error: "upload not found" }));
    }
    return jsonResponse(
      res,
      200,
      JSON.stringify({
        id: uploadId,
        sha256:
          "0000000000000000000000000000000000000000000000000000000000000000",
        original_filename: "test.zevtc",
        size_bytes: 1024,
        uploaded_at: "2026-07-18T12:00:00Z",
        status: "completed",
        error_message: null,
        parser_version: "1.3.0",
        fight_id: "fixture-fight-001",
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

    // /api/v1/fights/:id/timeline/players?window_s=N (v0.10.28 plan 162).
    // Per-player timeline: N stacked line series, one per player.
    // MUST be matched BEFORE the catch-all /timeline handler below
    // so the regex doesn't consume ``/timeline/players`` as part of
    // the timeline path.
    const fightPlayerTimelineMatch = path.match(/^\/api\/v1\/fights\/([^/]+)\/timeline\/players$/);
    if (fightPlayerTimelineMatch) {
      const fightId = decodeURIComponent(fightPlayerTimelineMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(res, 404, JSON.stringify({ error: "fight not found" }));
      }
      const body = await loadFixture("fight-player-timeline.json");
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

    // /api/v1/fights/:id/positions (v0.11.0 Phase C + v0.14.3 heatmap).
    // Returns per-player position metrics + downsampled samples.
    // MUST be matched BEFORE the bare /:id catch-all.
    const positionsMatch = path.match(
      /^\/api\/v1\/fights\/([^/]+)\/positions$/,
    );
    if (positionsMatch) {
      const fightId = decodeURIComponent(positionsMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(
          res,
          404,
          JSON.stringify({ error: "fight not found" }),
        );
      }
      return jsonResponse(
        res,
        200,
        JSON.stringify({
          fight_id: fightId,
          players: [
            {
              account_name: "TestAccount.1234",
              name: "Fighty McFight",
              profession: "Warrior",
              elite_spec: "Berserker",
              stack_dist: 150.0,
              dist_to_com: 80.0,
              samples: [
                { x: 1000, y: 2000, z: 0 },
                { x: 1100, y: 2100, z: 0 },
                { x: 1200, y: 2050, z: 0 },
                { x: 1150, y: 1950, z: 0 },
              ],
            },
            {
              account_name: "TestAccount.5678",
              name: "Heal Bot",
              profession: "Guardian",
              elite_spec: "Firebrand",
              stack_dist: 200.0,
              dist_to_com: 120.0,
              samples: [
                { x: 3000, y: 4000, z: 0 },
                { x: 3100, y: 4100, z: 0 },
                { x: 3200, y: 4050, z: 0 },
              ],
            },
          ],
        }),
      );
    }

    // Combat readout (F17, per docs/v0.9.0-combat-readout-design.md
    // §5.1) -- the unified endpoint returns the bound payload for
    // all 4 per-player tables (Damage / Heal / Boons / Defense).
    // Phase 6 v2 (v0.12.x): all columns carry real non-zero values
    // so the E2E test can assert dps_power > 0, barrier_total > 0,
    // dodges > 0, blocks > 0, interrupts > 0. The 4 player rows
    // mirror the canonical roster used by the bare
    // ``/api/v1/fights/:id`` stub (top-of-fragment by squad) so a
    // tab-toggle between Overview + Readout shows a consistent
    // squad composition. The response matches the
    // :class:`FightReadoutOut` Pydantic shape verbatim.
    const readoutMatch = path.match(
      /^\/api\/v1\/fights\/([^/]+)\/readout$/,
    );
    if (readoutMatch) {
      const fightId = decodeURIComponent(readoutMatch[1]);
      if (!KNOWN_FIGHTS.has(fightId)) {
        return jsonResponse(
          res,
          404,
          JSON.stringify({ error: "fight not found" }),
        );
      }
      return jsonResponse(
        res,
        200,
        JSON.stringify({
          fight_id: fightId,
          duration_s: 125.5,
          players: [
            {
              agent_id: 1234,
              subgroup: 1,
              name: "Fighty McFight",
              account_name: "TestAccount.1234",
              profession: "Warrior",
              elite_spec: "Berserker",
              is_commander: true,
              roles: ["DPS", "STRIP"],
              damage: {
                dps_total: 2450,
                dps_power: 1800,
                dps_condi: 650,
                strips: 18,
                cc_applied: 312,
                down_contribution_dps: 850,
                kills: 2,
              },
              heal: {
                heal_total: 180_000,
                hps: 1440,
                barrier_total: 12000,
                barrier_ps: 95.6,
                cleanses: 4,
                stun_breaks: 1,
              },
              boons: {
                boons_out_rate: 0.6,
                boons_in_rate: 12.4,
                stability_out: 0,
                alacrity_out: 0,
                resistance_out: 8,
                aegis_out: 12,
                superspeed_out: 0,
                stealth_out: 0,
                other_boons_out: { might: 1240, fury: 84 },
                might_uptime: 85,
                fury_uptime: 92,
                quickness_uptime: 78,
                alacrity_uptime: 65,
                protection_uptime: 45,
                regeneration_uptime: 30,
                vigor_uptime: 60,
                aegis_uptime: 40,
                stability_uptime: 25,
                swiftness_uptime: 80,
                resistance_uptime: 15,
                resolution_uptime: 50,
                superspeed_uptime: 8,
                stealth_uptime: 3,
                outgoing_might: 5000,
                outgoing_fury: 3000,
                outgoing_quickness: 2000,
                outgoing_alacrity: 1000,
                outgoing_protection: 1500,
                outgoing_regeneration: 800,
                outgoing_vigor: 600,
                outgoing_aegis: 400,
                outgoing_stability: 200,
                outgoing_swiftness: 300,
                outgoing_resistance: 100,
                outgoing_resolution: 250,
                outgoing_superspeed: 50,
                outgoing_stealth: 10,
              },
              defense: {
                damage_taken: 58_300,
                cc_taken: 4,
                deaths: 0,
                time_downed_ms: 0,
                dodges: 3,
                blocks: 2,
                interrupts: 1,
                barrier_absorbed: 0,
                presence_pct: 98,
              },
            },
            {
              agent_id: 9999,
              subgroup: 1,
              name: "Slice McSlice",
              account_name: "TestAccount.9999",
              profession: "Thief",
              elite_spec: "Daredevil",
              is_commander: false,
              roles: ["DPS"],
              damage: {
                dps_total: 3120,
                dps_power: 2400,
                dps_condi: 720,
                strips: 22,
                cc_applied: 420,
                down_contribution_dps: 1100,
                kills: 4,
              },
              heal: {
                heal_total: 25_000,
                hps: 200,
                barrier_total: 3000,
                barrier_ps: 23.9,
                cleanses: 0,
                stun_breaks: 0,
              },
              boons: {
                boons_out_rate: 0.2,
                boons_in_rate: 14.1,
                stability_out: 0,
                alacrity_out: 0,
                resistance_out: 4,
                aegis_out: 2,
                superspeed_out: 220,
                stealth_out: 240,
                other_boons_out: { might: 950, fury: 60 },
                might_uptime: 70,
                fury_uptime: 80,
                quickness_uptime: 55,
                alacrity_uptime: 40,
                protection_uptime: 35,
                regeneration_uptime: 20,
                vigor_uptime: 50,
                aegis_uptime: 30,
                stability_uptime: 15,
                swiftness_uptime: 85,
                resistance_uptime: 10,
                resolution_uptime: 40,
                superspeed_uptime: 90,
                stealth_uptime: 95,
                outgoing_might: 4000,
                outgoing_fury: 2500,
                outgoing_quickness: 1500,
                outgoing_alacrity: 800,
                outgoing_protection: 1200,
                outgoing_regeneration: 600,
                outgoing_vigor: 400,
                outgoing_aegis: 300,
                outgoing_stability: 100,
                outgoing_swiftness: 200,
                outgoing_resistance: 50,
                outgoing_resolution: 200,
                outgoing_superspeed: 500,
                outgoing_stealth: 300,
              },
              defense: {
                damage_taken: 47_200,
                cc_taken: 6,
                deaths: 1,
                time_downed_ms: 0,
                dodges: 7,
                blocks: 0,
                interrupts: 3,
                barrier_absorbed: 0,
                presence_pct: 75,
              },
            },
            {
              agent_id: 4040,
              subgroup: 2,
              name: "Bloomy McBloom",
              account_name: "TestAccount.4040",
              profession: "Necromancer",
              elite_spec: "Reaper",
              is_commander: false,
              roles: ["DPS"],
              damage: {
                dps_total: 2210,
                dps_power: 600,
                dps_condi: 1610,
                strips: 12,
                cc_applied: 180,
                down_contribution_dps: 0,
                kills: 1,
              },
              heal: {
                heal_total: 60_000,
                hps: 480,
                barrier_total: 8000,
                barrier_ps: 63.7,
                cleanses: 0,
                stun_breaks: 0,
              },
              boons: {
                boons_out_rate: 1.4,
                boons_in_rate: 6.0,
                stability_out: 12,
                alacrity_out: 0,
                resistance_out: 6,
                aegis_out: 1,
                superspeed_out: 0,
                stealth_out: 0,
                other_boons_out: { might: 720, fury: 90, "soul reaper": 8 },
                might_uptime: 60,
                fury_uptime: 70,
                quickness_uptime: 45,
                alacrity_uptime: 35,
                protection_uptime: 50,
                regeneration_uptime: 25,
                vigor_uptime: 40,
                aegis_uptime: 20,
                stability_uptime: 30,
                swiftness_uptime: 60,
                resistance_uptime: 12,
                resolution_uptime: 45,
                superspeed_uptime: 5,
                stealth_uptime: 2,
                outgoing_might: 3500,
                outgoing_fury: 2000,
                outgoing_quickness: 1200,
                outgoing_alacrity: 600,
                outgoing_protection: 1000,
                outgoing_regeneration: 500,
                outgoing_vigor: 300,
                outgoing_aegis: 200,
                outgoing_stability: 400,
                outgoing_swiftness: 150,
                outgoing_resistance: 80,
                outgoing_resolution: 300,
                outgoing_superspeed: 30,
                outgoing_stealth: 10,
              },
              defense: {
                damage_taken: 38_500,
                cc_taken: 3,
                deaths: 0,
                time_downed_ms: 0,
                dodges: 2,
                blocks: 5,
                interrupts: 0,
                barrier_absorbed: 0,
                presence_pct: 88,
              },
            },
            {
              agent_id: 5678,
              subgroup: 2,
              name: "Heal Bot",
              account_name: "TestAccount.5678",
              profession: "Guardian",
              elite_spec: "Firebrand",
              is_commander: false,
              roles: ["HEAL", "SUPPORT", "STRIP"],
              damage: {
                dps_total: 850,
                dps_power: 200,
                dps_condi: 650,
                strips: 8,
                cc_applied: 205,
                down_contribution_dps: 120,
                kills: 0,
              },
              heal: {
                heal_total: 1_200_000,
                hps: 9600,
                barrier_total: 45000,
                barrier_ps: 358.6,
                cleanses: 125,
                stun_breaks: 8,
              },
              boons: {
                boons_out_rate: 4.2,
                boons_in_rate: 18.7,
                stability_out: 480,
                alacrity_out: 24,
                resistance_out: 18,
                aegis_out: 86,
                superspeed_out: 0,
                stealth_out: 0,
                other_boons_out: { might: 560, fury: 120, quickness: 200 },
                might_uptime: 95,
                fury_uptime: 88,
                quickness_uptime: 92,
                alacrity_uptime: 85,
                protection_uptime: 70,
                regeneration_uptime: 55,
                vigor_uptime: 75,
                aegis_uptime: 90,
                stability_uptime: 80,
                swiftness_uptime: 65,
                resistance_uptime: 60,
                resolution_uptime: 70,
                superspeed_uptime: 10,
                stealth_uptime: 5,
                outgoing_might: 8000,
                outgoing_fury: 6000,
                outgoing_quickness: 9000,
                outgoing_alacrity: 7000,
                outgoing_protection: 4000,
                outgoing_regeneration: 3000,
                outgoing_vigor: 2500,
                outgoing_aegis: 5000,
                outgoing_stability: 6000,
                outgoing_swiftness: 1500,
                outgoing_resistance: 2000,
                outgoing_resolution: 3000,
                outgoing_superspeed: 100,
                outgoing_stealth: 50,
              },
              defense: {
                damage_taken: 21_000,
                cc_taken: 2,
                deaths: 0,
                time_downed_ms: 0,
                dodges: 1,
                blocks: 12,
                interrupts: 4,
                barrier_absorbed: 0,
                presence_pct: 99,
              },
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
