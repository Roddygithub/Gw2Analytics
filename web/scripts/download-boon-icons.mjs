#!/usr/bin/env node
/**
 * One-shot acquisition of Guild Wars 2 Tango Medium boon icons.
 *
 * Source: https://wiki.guildwars2.com/wiki/Special:FilePath/<NAME>_tango_icon_48px.png
 *
 * Strategy identical to download-tango-icons.mjs (profession icons).
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const URL_BASE = "https://wiki.guildwars2.com/wiki/Special:FilePath";

/**
 * Boons displayed in the combat readout boons table.
 * Key = English wiki page title (used in Special:FilePath URL),
 * Value = French display label (for tooltip fallback).
 */
const BOONS = {
  Stability: "Stabilité",
  Alacrity: "Célérité",
  Resistance: "Résistance",
  Aegis: "Égide",
  Superspeed: "Superspeed",
  Stealth: "Stealth",
  // Additional boons that can appear in "Other boons"
  Might: "Might",
  Fury: "Fureur",
  Protection: "Protection",
  Quickness: "Quickness",
  Regeneration: "Régénération",
  Swiftness: "Célérité",
  Vigor: "Vigueur",
  Resolution: "Résolution",
};

const ICON_DIR = path.join(__dirname, "..", "public", "icons", "boons");

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

const USER_AGENT =
  "Gw2AnalyticsFetcher/0.16.3 (+https://github.com/example/gw2analytics; admin@example.com)";

async function ensureDir(d) {
  await fs.mkdir(d, { recursive: true });
}

async function fetchIcon(name, outPath) {
  // Boon icons on the GW2 wiki use plain .png, not the tango_icon suffix.
  const url = `${URL_BASE}/${encodeURIComponent(name)}.png`;
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": USER_AGENT },
      redirect: "follow",
    });
    if (!res.ok) {
      console.warn(`  ⚠ ${name.padEnd(20)} HTTP ${res.status}`);
      return { ok: false, reason: `http-${res.status}` };
    }
    const ab = await res.arrayBuffer();
    const buf = Buffer.from(ab);
    if (buf.length < 8 || !buf.slice(0, 8).equals(PNG_MAGIC)) {
      console.warn(
        `  ⚠ ${name.padEnd(20)} not a PNG (${buf.length} bytes, start=${buf.slice(0, 4).toString("hex")})`,
      );
      return { ok: false, reason: "not-png" };
    }
    await fs.writeFile(outPath, buf);
    console.log(`  ✓ ${name.padEnd(20)} ${buf.length} bytes`);
    return { ok: true, size: buf.length };
  } catch (err) {
    console.warn(`  ⚠ ${name.padEnd(20)} ${err?.message ?? err}`);
    return { ok: false, reason: "exception" };
  }
}

async function main() {
  console.log("Boon Tango icon acquisition");
  console.log(`Output: ${ICON_DIR}`);
  console.log("");

  await ensureDir(ICON_DIR);

  let totalOk = 0;
  let totalFail = 0;

  console.log("Boons:");
  for (const [name, label] of Object.entries(BOONS)) {
    const r = await fetchIcon(name, path.join(ICON_DIR, `${name}_tango.png`));
    r.ok ? totalOk++ : totalFail++;
  }

  console.log("");
  const total = Object.keys(BOONS).length;
  console.log(`Done: ${totalOk}/${total} icons OK (${totalFail} skipped)`);
  process.exit(0);
}

await main();
