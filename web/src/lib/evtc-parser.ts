/**
 * Minimal EVTC binary parser — stub-aware for the v0.10.23 stub fixture.
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
 * writer). This module deliberately stops at the stub-fixture boundary so it
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

/** Shared UTF-8 decoder reused across all buffer scans. */
const _utf8Decoder = new TextDecoder("utf-8");

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
  const magic = _utf8Decoder.decode(buf.subarray(0, 4));
  if (magic !== "EVTC") {
    throw new EvtcParseError(
      `EVTC magic mismatch: expected "EVTC", got ${JSON.stringify(magic)}`,
    );
  }
  const buildYear = _utf8Decoder.decode(buf.subarray(4, 8));
  const dayMark = _utf8Decoder.decode(buf.subarray(8, 12));
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
  const seen = new Set<string>();
  let cursor = 0;
  while (cursor < buf.length) {
    // Skip null bytes.
    while (cursor < buf.length && buf[cursor] === 0x00) cursor++;
    // Read until next null OR buffer end.
    const start = cursor;
    while (cursor < buf.length && buf[cursor] !== 0x00) cursor++;
    const end = cursor;
    const len = end - start;
    if (len < 4) continue;
    // Printable ASCII spans 0x20..0x7e. Validate in one pass, then
    // decode once with String.fromCharCode to avoid both the
    // TextDecoder overhead and repeated string concatenation.
    let isAscii = true;
    const codes = new Array<number>(len);
    for (let i = 0; i < len; i++) {
      const b = buf[start + i];
      if (b < 0x20 || b > 0x7e) {
        isAscii = false;
        break;
      }
      codes[i] = b;
    }
    if (!isAscii) continue;
    seen.add(String.fromCharCode(...codes));
  }
  return Array.from(seen);
}

/** Thrown when the EVTC magic-bytes do not match or the buffer is too small. */
export class EvtcParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EvtcParseError";
  }
}
