#!/usr/bin/env node
/**
 * F17 W.1: one-shot acquisition of Guild Wars 2 Tango Medium
 * profession + elite specialization icons.
 *
 * Source: https://wiki.guildwars2.com/wiki/Special:FilePath/<NAME>_tango_icon_48px.png
 *
 * Strategy:
 * 1. Resolve the Special:FilePath redirect to the wiki CDN URL
 *    (Special:FilePath indirection handles future renames).
 * 2. Validate response is image/png and well-formed (PNG magic bytes).
 * 3. Persist under web/public/icons/{professions,specializations}/<NAME>_tango.png.
 *
 * Why bundled (not hotlinked):
 * - The CSP in web/next.config.ts is `img-src 'self' data:`; bundling
 *   avoids a layered security-header change in BOTH the Caddyfile
 *   (plan 008) and web/next.config.ts (plan 011) per the v0.10.x
 *   keep-these-two-files-synchronized rule.
 * - Offline rendering: analysts with intermittent connections can
 *   still browse historical fights.
 *
 * Why this is a runnable Node script (not a Python/CI snake):
 * - The repo's tooling mix is FastAPI/Python + Next.js/Node; using
 *   Node keeps the acquisition process with the web half of the repo
 *   and re-runnable from any developer laptop without a Python env.
 *
 * Re-run cadence: only when ArenaNet updates the icon set (every ~2
 * years per GW2 expansion). The script is idempotent (overwrites
 * the destination files in place; missing source = skipped, not
 * crash).
 *
 * Usage:
 *   node web/scripts/download-tango-icons.mjs
 *
 * Output:
 *   web/public/icons/professions/<NAME>_tango.png
 *   web/public/icons/specializations/<NAME>_tango.png
 *   web/public/icons/ATTRIBUTION.md (auto-emitted if missing)
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const URL_BASE = "https://wiki.guildwars2.com/wiki/Special:FilePath";

/**
 * The 9 base professions (canonical, locked at the GW2 Core enum).
 * Source: libs/gw2_core/src/gw2_core/models.py (Profession StrEnum).
 */
const PROFESSIONS = [
  "Guardian",
  "Warrior",
  "Engineer",
  "Ranger",
  "Thief",
  "Elementalist",
  "Mesmer",
  "Necromancer",
  "Revenant",
];

/**
 * 24 elite specializations (3 per profession * 8 professions
 * = 24 plus the latest per profession added over time). Listed
 * here in a flat array -- future expansions append to the end.
 *
 * Naming uses the Special:FilePath wiki page title (i.e. the
 * solo name without the profession prefix).
 */
const ELITES = [
  // Guardian (4)
  "Dragonhunter",
  "Firebrand",
  "Willbender",
  "Luminary",
  // Warrior (4)
  "Berserker",
  "Spellbreaker",
  "Bladesworn",
  "Paragon",
  // Engineer (4)
  "Holosmith",
  "Scrapper",
  "Mechanist",
  "Amalgam",
  // Ranger (4)
  "Druid",
  "Soulbeast",
  "Untamed",
  "Galeshot",
  // Thief (4)
  "Daredevil",
  "Deadeye",
  "Specter",
  "Antiquary",
  // Elementalist (4)
  "Tempest",
  "Weaver",
  "Catalyst",
  "Evoker",
  // Mesmer (4)
  "Chronomancer",
  "Mirage",
  "Virtuoso",
  "Troubadour",
  // Necromancer (4)
  "Reaper",
  "Scourge",
  "Harbinger",
  "Ritualist",
  // Revenant (4)
  "Herald",
  "Renegade",
  "Vindicator",
  "Conduit",
];

const ICON_DIR = path.join(__dirname, "..", "public", "icons");
const PROF_DIR = path.join(ICON_DIR, "professions");
const SPEC_DIR = path.join(ICON_DIR, "specializations");

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

const ATTRIBUTION_INITIAL = `# GW2 Tango Medium Icon Attribution

The profession + specialization icons in this directory are Tango Medium icons sourced from the official Guild Wars 2 Wiki (\`Special:FilePath/<NAME>_tango_icon_48px.png\`).

## Acquisition

Run \`node web/scripts/download-tango-icons.mjs\` to refresh. Re-run only when ArenaNet updates the icon set (typically on a new expansion).

## License

Guild Wars 2 © ArenaNet LLC. All rights reserved. NCSOFT, the interlocking NC logo, ArenaNet, Guild Wars, Guild Wars 2, and all associated logos and designs are trademarks or registered trademarks of NCSOFT Corporation.

These icons are bundled in Gw2Analytics for offline rendering of a personal, non-commercial combat-log analyser per ArenaNet's permissive Content Terms of Use for fan / community projects.
`;

async function ensureDir(d) {
  await fs.mkdir(d, { recursive: true });
}

// v0.10.25 fix: the wiki.guildwars2.com CDN enforces a
// User-Agent header (MediaWiki API policy + hotlink protection).
// Node's default ``fetch`` (undici-based) sends a non-conforming
// ``User-Agent: node`` that the wiki returns 403 for (verified
// reproducibly in CI). This header is a polite project identifier
// + a contact URL; the wiki responds 200 OK.
const USER_AGENT =
  "Gw2AnalyticsFetcher/0.10.25 (+https://github.com/example/gw2analytics; admin@example.com)";

async function fetchIcon(name, outPath) {
  const url = `${URL_BASE}/${encodeURIComponent(name)}_tango_icon_48px.png`;
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": USER_AGENT },
      redirect: "follow",
    });
    if (!res.ok) {
      console.warn(`  ⚠ ${name.padEnd(18)} HTTP ${res.status}`);
      return { ok: false, reason: `http-${res.status}` };
    }
    const ab = await res.arrayBuffer();
    const buf = Buffer.from(ab);
    if (buf.length < 8 || !buf.slice(0, 8).equals(PNG_MAGIC)) {
      console.warn(
        `  ⚠ ${name.padEnd(18)} not a PNG (${buf.length} bytes, start=${buf.slice(0, 4).toString("hex")})`,
      );
      return { ok: false, reason: "not-png" };
    }
    await fs.writeFile(outPath, buf);
    console.log(`  ✓ ${name.padEnd(18)} ${buf.length} bytes`);
    return { ok: true, size: buf.length };
  } catch (err) {
    console.warn(`  ⚠ ${name.padEnd(18)} ${err?.message ?? err}`);
    return { ok: false, reason: "exception" };
  }
}

async function main() {
  console.log(`F17 W.1 — Tango Medium icon acquisition`);
  console.log(`Output: ${ICON_DIR}`);
  console.log("");

  await ensureDir(PROF_DIR);
  await ensureDir(SPEC_DIR);
  // Emission of ATTRIBUTION.md is idempotent: skip if present.
  const attrPath = path.join(ICON_DIR, "ATTRIBUTION.md");
  try {
    await fs.access(attrPath);
  } catch {
    await fs.writeFile(attrPath, ATTRIBUTION_INITIAL);
    console.log(`  + ATTRIBUTION.md (initial)`);
  }

  let totalOk = 0;
  let totalFail = 0;

  console.log("Professions:");
  for (const p of PROFESSIONS) {
    const r = await fetchIcon(p, path.join(PROF_DIR, `${p}_tango.png`));
    r.ok ? totalOk++ : totalFail++;
  }

  console.log("");
  console.log("Elite specifications:");
  for (const s of ELITES) {
    const r = await fetchIcon(s, path.join(SPEC_DIR, `${s}_tango.png`));
    r.ok ? totalOk++ : totalFail++;
  }

  console.log("");
  const total = PROFESSIONS.length + ELITES.length;
  console.log(`Done: ${totalOk}/${total} icons OK (${totalFail} skipped)`);
  // Always exit 0: partial coverage is acceptable (the icon
  // library's empty-fallback spans render cleanly for un-bundled
  // entities; the script's purpose is "best-effort perpetual
  // refreshing", not "fail-the-build on missing wiki entries").
  process.exit(0);
}

await main();
