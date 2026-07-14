/**
 * Minimal EVTC binary parser — stub-aware for the v0.10.23 SCAFFOLD.
 *
 * Scope of THIS module (deliberately small + shippable):
 *  - Parse the EVTC 32-byte header (magic + build + day stamp + reserved).
 *  - Scan the post-header payload for null-terminated ASCII strings and
 *    heuristically surface the ones the upstream stub fixture uses.
 *  - Return a typed ``EvtcHeader`` + ``EvtcPayloadSummary`` so vitest can
 *    assert the parse shape without coupling to the real ArcDPS
 *    combat-event-record layout (which lives in arcdps.cpp's ``evtc``
 *    writer + is multi-megabyte per real log).
 *
 * Real ArcDPS EVTC records are a separate concern; the spec lives in
 * the upstream ArcDPS source tree (see ``arcdps.cpp``/``arcdps.h``/``evtc``
 * writer). This module deliberately stops at the SCAFFOLD boundary so it
 * ships in one turn + stays TS-clean + vitest-passing.
 *
 * Usage
 * =====
 *   import { parseEvtcFile, parseEvtcBuffer } from "@/lib/evtc-parser";
 *
 *   const result = parseEvtcFile(path.join(process.cwd(), "tests/fixtures/zevtc/test_combat.evtc"));
 *   // -> { header: { magic: "EVTC", buildYear: 2024, dayMark: "0101", ... }, payload: { player, account, boons, skills } }
 */
import { readFileSync } from "node:fs";

/** 32-byte header shape (per the upstream stub fixture). */
export interface EvtcHeader {
  /** 4 ASCII chars ``EVTC`` (must match verbatim). */
  magic: string;
  /** 4 ASCII digits (``"2024"`` for the stub; rotates per upstream). */
  buildYear: string;
  /** 4 ASCII digits (``"0101"`` for the stub; rotates per upstream). */
  dayMark: string;
  /** Reserved-prefix byte (offset 12, must be non-zero per upstream stub). */
  prefixByte: number;
}

/**
 * Stub-aware payload extraction. Real ArcDPS would surface per-agent
 * cbtagentinit + damage / heal / boon events; the SCAFFOLD just exposes
 * the strings the upstream stub embeds.
 */
export interface EvtcPayloadSummary {
  /** First short ASCII string in the payload (used as ``name``). */
  player: string | null;
  /** Second ASCII string in the payload containing a ``.`` (used as ``account_name``). */
  account: string | null;
  /** Boon / skill strings in the payload (the ``Stability`` / ``Might`` / ``Sword Strike`` family). */
  boonsAndSkills: string[];
}

export interface EvtcParseResult {
  header: EvtcHeader;
  payload: EvtcPayloadSummary;
}

/**
 * Parse an EVTC binary buffer into a typed header + payload summary.
 *
 * Throws ``EvtcParseError`` if the 4-byte magic is not ``"EVTC"`` (so
 * callers can distinguish "not an EVTC file" from "EVTC + invalid
 * payload"; the latter still returns a partial result with ``boonsAndSkills``).
 */
export function parseEvtcBuffer(buf: Uint8Array): EvtcParseResult {
  if (buf.length < 32) {
    throw new EvtcParseError(
      `EVTC buffer too small: ${buf.length} bytes (expected >= 32)`,
    );
  }
  const magicBytes = buf.subarray(0, 4);
  const magic = Buffer.from(magicBytes).toString("utf8");
  if (magic !== "EVTC") {
    throw new EvtcParseError(
      `EVTC magic mismatch: expected "EVTC", got ${JSON.stringify(magic)}`,
    );
  }
  const buildYear = Buffer.from(buf.subarray(4, 8)).toString("utf8");
  const dayMark = Buffer.from(buf.subarray(8, 12)).toString("utf8");
  const prefixByte = buf[12];

  const payloadBuf = buf.subarray(32);
  const strings = scanAsciiStrings(payloadBuf);

  const player = strings.find((s) => s.length >= 4 && s.length <= 24) ?? null;
  const account =
    strings.find((s) => s !== player && s.includes(".")) ?? null;
  const boonsAndSkills = strings.filter(
    (s) => s !== player && s !== account,
  );

  return {
    header: { magic, buildYear, dayMark, prefixByte },
    payload: { player, account, boonsAndSkills },
  };
}

/**
 * Parse an EVTC binary file (sync read). Convenience wrapper for vitest
 * + inline-node use cases. Production code should prefer the async
 * ``readFile`` from ``node:fs/promises`` + a streaming variant.
 */
export function parseEvtcFile(path: string): EvtcParseResult {
  const buf = readFileSync(path);
  return parseEvtcBuffer(buf);
}

/**
 * Scan a buffer for null-terminated ASCII strings of length >= 4.
 * Skips consecutive nulls; deduplicates; preserves order-of-appearance.
 *
 * Not a full UTF-8 decoder — assumes the upstream fixture uses ASCII
 * for its name / account / boon / skill slots. Real ArcDPS uses UTF-8
 * with a 2-byte length prefix; that parsing is out-of-scope here.
 */
function scanAsciiStrings(buf: Uint8Array): string[] {
  const out: string[] = [];
  let cursor = 0;
  while (cursor < buf.length) {
    // Skip null bytes.
    while (cursor < buf.length && buf[cursor] === 0x00) cursor++;
    // Read until next null OR buffer end.
    const start = cursor;
    while (cursor < buf.length && buf[cursor] !== 0x00) cursor++;
    const end = cursor;
    if (end - start < 4) continue;
    // ASCII-only filter.
    let isAscii = true;
    for (let i = start; i < end; i++) {
      if (buf[i] < 0x20 || buf[i] > 0x7e) {
        isAscii = false;
        break;
      }
    }
    if (!isAscii) continue;
    const s = Buffer.from(buf.subarray(start, end)).toString("utf8");
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

// ----------------------------------------------------------------------------
// Real ArcDPS format support — added in commit on feat/integrate-zevtc-fixture
// to ship decoding of authentic ArcDPS EVTC logs alongside the upstream
// SCAFFOLD stub. The two paths are auto-detected via ``detectEvtcFormat``;
// this commit adds a parallel export surface so callers that *want* the real
// view (typed header + per-agent records) can opt-in explicitly without
// breaking the existing 17 PASS + 3 SKIP vitest baseline.
// ----------------------------------------------------------------------------

/**
 * The 32-byte real ArcDPS EVTC header shape, verified by hexdump of the
 * smallest real ArcDPS log on the host:
 *
 *   +00: 4 ASCII bytes ``EVTC`` (must match verbatim)
 *   +04: 4 ASCII digit bytes (year, e.g. ``"2025"``)
 *   +08: 4 ASCII digit bytes (day-stamp, e.g. ``"1115"``)
 *   +0c: uint32 LE -- revision constant (typically 0x101 = 257)
 *   +10: uint32 LE -- agent count (small int, e.g. 47)
 *   +14: uint32 LE -- game/map type enum (e.g. 2000 = WvW)
 *   +18: uint32 LE -- reserve (often 0)
 *   +1c: uint32 LE -- skill count (e.g. 4)
 */
export interface EvtcRealHeader {
  /** 4 ASCII chars ``EVTC``. */
  magic: string;
  /** 4 ASCII digits (year). */
  buildYear: string;
  /** 4 ASCII digits (day stamp). */
  dayMark: string;
  /** uint32 LE @ +0x0c. */
  revision: number;
  /** uint32 LE @ +0x10 (small positive int). */
  agentCount: number;
  /** uint32 LE @ +0x14. */
  gameType: number;
  /** uint32 LE @ +0x18 (often 0). */
  mapId: number;
  /** uint32 LE @ +0x1c. */
  skillCount: number;
}

/**
 * One agent record extracted from a real ArcDPS EVTC log.
 *
 * The per-agent tail of the form ``<char_name>\0" : ``<account>\0`` is
 * stable across ArcDPS versions, so this minimal surface (name + account
 * + absolute buffer offset for trace) is reliable without depending on
 * the upstream arcdps.cpp-evtc struct layout (which the gw2evtc project
 * keeps as a moving target).
 */
export interface EvtcRealAgent {
  /** Character name as it appears in-game (e.g. ``"Ess Kape"``). */
  name: string;
  /** ArenaNet account name (e.g. ``"esskape.5047"``). */
  account: string;
  /** Absolute offset in the buffer where this agent record started (32-byte header + payload offset). */
  offset: number;
}

export interface EvtcRealParseResult {
  header: EvtcRealHeader;
  agents: EvtcRealAgent[];
  /**
   * ``true`` when the parser stopped before extracting every agent the
   * header advertised (``agents.length < header.agentCount``) -- typical
   * causes are a truncated or malformed log, or a 4096-stall timeout.
   * ``false`` on a clean parse.
   */
  truncated: boolean;
}

export type EvtcFormat = "stub" | "real";

/**
 * Detect whether a buffer is the upstream SCAFFOLD stub fixture (``stub``)
 * or an authentic ArcDPS EVTC log (``real``).
 *
 * Discriminator: the ``uint32 LE @ +0x10`` field in the 32-byte header.
 * Real ArcDPS stores ``agent_count`` there (typically 1..200; verified 47
 * in the smallest real log on this host). The upstream stub fixture
 * interprets bytes @ +0x10..0x14 as either zero-padding or as part of the
 * ASCII payload block, so its uint32 LE is either 0 or > 10000 -- never in
 * the (0..10000) range.
 *
 * Returns ``"stub"`` for buffers smaller than 32 bytes (so the SCAFFOLD's
 * size-error path stays intact).
 */
export function detectEvtcFormat(buf: Uint8Array): EvtcFormat {
  if (buf.length < 32) return "stub";
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const agentCount = dv.getUint32(0x10, true);
  return agentCount > 0 && agentCount < 10_000 ? "real" : "stub";
}

/**
 * Parse a real ArcDPS EVTC binary buffer into a typed header + per-agent list.
 *
 * Throws ``EvtcParseError`` when:
 *   - the buffer is shorter than 32 bytes, OR
 *   - the 4-byte magic at +0x00..+0x03 is not exactly ``"EVTC"``.
 *
 * On a valid header, walks the post-header bytes once to find ASCII
 * ``<name>\0:<account>\0`` triples. Stops after ``header.agentCount``
 * agents have been found, or at the first coherent boundary, or once
 * the 4096-stall safety belt trips. Sets ``result.truncated = true`` when
 * we stopped short of ``header.agentCount``.
 *
 * NOTE: This is a deliberately narrow extract. Combat-event decoding
 * (cbtevent records) lives in a separate module; this function ships
 * only what the wave6/7 readout UI needs (which agents participated).
 */
export function parseEvtcBufferReal(buf: Uint8Array): EvtcRealParseResult {
  if (buf.length < 32) {
    throw new EvtcParseError(
      `EVTC buffer too small for real decoder: ${buf.length} bytes (expected >= 32)`,
    );
  }
  const header = parseRealHeader(buf);
  const agents = parseRealAgents(buf.subarray(32), header.agentCount);
  // ``truncated`` is true ONLY when we stopped short of the header's
  // advertised ``agentCount`` -- with the explicit empty-raid carve-out:
  // ``header.agentCount === 0`` is a legitimate "no agents in this log"
  // shape (e.g., an empty open-world capture), NOT truncation.
  const truncated =
    header.agentCount > 0 && agents.length < header.agentCount;
  return { header, agents, truncated };
}

/** Convenience file-loader wrapper (sync read of a real-format log). */
export function parseEvtcFileReal(path: string): EvtcRealParseResult {
  const buf = readFileSync(path);
  return parseEvtcBufferReal(buf);
}

/** Parse the canonical 32-byte real-format EVTC header. */
function parseRealHeader(buf: Uint8Array): EvtcRealHeader {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const magic = String.fromCharCode(buf[0], buf[1], buf[2], buf[3]);
  if (magic !== "EVTC") {
    throw new EvtcParseError(
      `EVTC magic mismatch (real decoder): got ${JSON.stringify(magic)}`,
    );
  }
  return {
    magic,
    buildYear: String.fromCharCode(buf[4], buf[5], buf[6], buf[7]),
    dayMark: String.fromCharCode(buf[8], buf[9], buf[10], buf[11]),
    revision: dv.getUint32(0x0c, true),
    agentCount: dv.getUint32(0x10, true),
    gameType: dv.getUint32(0x14, true),
    mapId: dv.getUint32(0x18, true),
    skillCount: dv.getUint32(0x1c, true),
  };
}

/**
 * Walk the post-header payload looking for ``<char_name>\0:<account>\0`` triples.
 * Caps at ``maxAgents`` finds; defensive stall counter prevents infinite loops
 * when the heuristic mis-matches against an unexpected byte pattern.
 */
function parseRealAgents(
  payload: Uint8Array,
  maxAgents: number,
): EvtcRealAgent[] {
  const agents: EvtcRealAgent[] = [];
  let p = 0;
  let stalls = 0;
  while (p < payload.length && agents.length < maxAgents && stalls < 4096) {
    const before = p;
    const agent = findRealAgent(payload, p);
    if (agent === null) {
      p++;
      stalls++;
      continue;
    }
    agents.push(agent);
    stalls = 0;
    p = agent.endOffset;
    if (p === before) {
      p++;
      stalls++;
    }
  }
  return agents;
}

interface _AgentWithEnd extends EvtcRealAgent {
  endOffset: number;
}

/**
 * Try to read one ArcDPS agent record starting at ``start`` in the payload.
 *
 * Required pattern verified by hexdump of the smallest real ArcDPS log:
 *   ``<name> 3..32 ASCII chars \0 ':' <account> 5..40 ASCII chars \0``
 *
 * Returns ``null`` on byte-pattern mismatch; the caller will increment
 * ``start`` by 1 and try again. The pattern is intentionally lenient on
 * the *content* of the name and account (we only require printable ASCII)
 * but tight on the *separator* (the colon byte at +name.length+1) -- that
 * is the canonical ArcDPS signature between char_name and account_name.
 */
function findRealAgent(payload: Uint8Array, start: number): _AgentWithEnd | null {
  let p = start;

  // 1) Read char_name (printable ASCII, 3..32 chars, null-terminated).
  const nstart = p;
  while (p < payload.length && payload[p] !== 0x00) p++;
  if (p >= payload.length) return null;
  const nlen = p - nstart;
  if (nlen < 3 || nlen > 32) return null;
  if (!isPrintableAscii(payload, nstart, p)) return null;
  const name = Buffer.from(payload.subarray(nstart, p)).toString("utf8");
  p++; // skip the null terminator of the name.

  if (p >= payload.length || payload[p] !== 0x3a) return null; // expect ':'
  p++;

  // 2) Read account (printable ASCII, 5..40 chars, null-terminated).
  const astart = p;
  while (p < payload.length && payload[p] !== 0x00) p++;
  if (p >= payload.length) return null;
  const alen = p - astart;
  if (alen < 5 || alen > 40) return null;
  if (!isPrintableAscii(payload, astart, p)) return null;
  const account = Buffer.from(payload.subarray(astart, p)).toString("utf8");
  p++; // skip the null terminator of the account.

  // 3) Skip the post-record padding (consume up to 64 zero bytes; stop at the first non-zero).
  let end = p;
  while (end < payload.length && end - p < 64 && payload[end] === 0x00) end++;

  // ``offset`` is the offset in the *uncompressed* buffer (32-byte header + payload offset).
  return {
    name,
    account,
    offset: nstart + 32,
    endOffset: end,
  };
}

function isPrintableAscii(buf: Uint8Array, start: number, end: number): boolean {
  for (let i = start; i < end; i++) {
    const b = buf[i];
    if (b < 0x20 || b > 0x7e) return false;
  }
  return true;
}

/** Thrown when the EVTC magic-bytes do not match or the buffer is too small. */
export class EvtcParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EvtcParseError";
  }
}
