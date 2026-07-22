import { describe, it, expect } from "vitest";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import {
  detectEvtcFormat,
  parseEvtcFileReal,
  parseEvtcBufferReal,
  EvtcParseError,
} from "@/lib/evtc-parser";

/**
 * Vitest module for the real-ArcDPS EVTC parser path.
 *
 * Exercises the parallel ``parseEvtcBufferReal`` / ``parseEvtcFileReal``
 * exports against the smallest authentic ArcDPS log on the host:
 *   tests/fixtures/zevtc/real_small.evtc  (28,976 bytes)
 * which is the uncompressed EVTC copy of the smallest ``.zevtc`` found on
 * the user's SSD (UUID=1E18-2168 at /run/media/roddy/Raspberry-P/WvW/.../20251116-224830.zevtc).
 *
 * The assertion set covers:
 *  - ``detectEvtcFormat`` returns ``"real"`` on the authentic log + ``"stub"`` on the existing
 *    stub fixture (so the two paths stay non-overlapping);
 *  - the 32-byte real-format header is parsed into typed fields (magic,
 *    ASCII year, ASCII day stamp, plus the 5 uint32 metadata fields);
 *  - at least one agent record is extracted with ``name + ": <account>"``
 *    structure (the ArcDPS char/account signature);
 *  - the parser errors out on a buffer with a non-EVTC magic.
 */
const REAL_FIXTURE_PATH = join(
  __dirname,
  "..",
  "fixtures",
  "zevtc",
  "real_small.evtc",
);
const STUB_FIXTURE_PATH = join(
  __dirname,
  "..",
  "fixtures",
  "zevtc",
  "test_combat.evtc",
);

describe("evtc-parser (REAL ArcDPS format)", () => {
  describe("detectEvtcFormat", () => {
    it("returns 'real' for an authentic ArcDPS binary", () => {
      const buf = readFileSync(REAL_FIXTURE_PATH);
      expect(buf.length).toBeGreaterThan(1024);
      expect(detectEvtcFormat(buf)).toBe("real");
    });

    it("returns 'stub' for the upstream stub fixture", () => {
      const buf = readFileSync(STUB_FIXTURE_PATH);
      expect(detectEvtcFormat(buf)).toBe("stub");
    });

    it("returns 'stub' for buffers shorter than 32 bytes", () => {
      const tiny = new Uint8Array(16);
      tiny[0] = 0x45;
      tiny[1] = 0x56;
      tiny[2] = 0x54;
      tiny[3] = 0x43;
      expect(detectEvtcFormat(tiny)).toBe("stub");
    });
  });

  describe("parseEvtcFileReal (header field extraction)", () => {
    it("extracts the EVTC magic verbatim from the real fixture", () => {
      const result = parseEvtcFileReal(REAL_FIXTURE_PATH);
      expect(result.header.magic).toBe("EVTC");
    });

    it("extracts the digit-shape buildYear + dayMark from the real fixture", () => {
      const result = parseEvtcFileReal(REAL_FIXTURE_PATH);
      expect(result.header.buildYear).toMatch(/^[0-9]{4}$/);
      expect(result.header.dayMark).toMatch(/^[0-9]{4}$/);
    });

    it("extracts the uint32 metadata fields from the real fixture", () => {
      const result = parseEvtcFileReal(REAL_FIXTURE_PATH);
      expect(result.header.revision).toBeGreaterThan(0);
      expect(result.header.agentCount).toBeGreaterThan(0);
      expect(result.header.agentCount).toBeLessThan(10_000);
      expect(result.header.gameType).toBeGreaterThan(0);
      expect(result.header.skillCount).toBeGreaterThan(0);
    });
  });

  describe("parseEvtcFileReal (per-agent extraction)", () => {
    it("finds at least one authentic agent in the smallest real ArcDPS log", () => {
      const result = parseEvtcFileReal(REAL_FIXTURE_PATH);
      expect(result.agents.length).toBeGreaterThan(0);

      // The first agent in this specific real log is the party owner
      // ("Ess Kape" / "esskape.5047").
      const first = result.agents[0];
      expect(first.name).toBe("Ess Kape");
      expect(first.account).toBe("esskape.5047");
      expect(first.offset).toBeGreaterThanOrEqual(32);
      // Lock the ``truncated`` happy-path contract: real-log parse either
      // completed (agents.length >= agentCount → truncated=false) or
      // stopped early (truncated=true). The test never pins the actual
      // value -- it asserts the *invariant* so callers can rely on it.
      expect(result.truncated).toBe(
        result.agents.length < result.header.agentCount,
      );
    });

    it("extracts multiple agents with mixed-case names in the authentic log", () => {
      const result = parseEvtcFileReal(REAL_FIXTURE_PATH);
      // Verified: the smallest real ArcDPS log contains at least 6 distinct
      // agents (Ess Kape, Lullu Crown, Charrush Piedbouche,
      // Guiritoui Le Tapeur, Harley Van Dyne, Rascalize, ...).
      expect(result.agents.length).toBeGreaterThanOrEqual(3);

      const byName = new Map<string, string>();
      for (const a of result.agents) byName.set(a.name, a.account);

      // Spot-check that at least the first two verified agents parse correctly.
      expect(byName.get("Ess Kape")).toBe("esskape.5047");
      expect(byName.get("Lullu Crown")).toBe("Lullupa.5768");
    });

    it("records the absolute buffer offset for each agent", () => {
      const result = parseEvtcFileReal(REAL_FIXTURE_PATH);
      const offsets = result.agents.map((a) => a.offset);
      // Offsets must be >= 32 (past header) AND strictly ascending OR identical
      // (the latter only if the same agent is referenced twice, which is
      // not normal ArcDPS behavior). Check monotonic increase for the first 3.
      for (let i = 1; i < Math.min(offsets.length, 3); i++) {
        expect(offsets[i]).toBeGreaterThanOrEqual(offsets[i - 1]);
      }
    });
  });

  describe("parseEvtcBufferReal (error paths)", () => {
    it("throws EvtcParseError on a buffer with a non-EVTC magic", () => {
      const buf = new Uint8Array(64);
      buf[0] = 0x58; // 'X'
      buf[1] = 0x4d; // 'M'
      buf[2] = 0x4c; // 'L'
      buf[3] = 0x44; // 'D' -- gibberish
      expect(() => parseEvtcBufferReal(buf)).toThrow(EvtcParseError);
    });

    it("throws EvtcParseError on a too-short buffer", () => {
      const buf = new Uint8Array(16);
      buf[0] = 0x45; // 'E'
      buf[1] = 0x56; // 'V'
      buf[2] = 0x54; // 'T'
      buf[3] = 0x43; // 'C'
      expect(() => parseEvtcBufferReal(buf)).toThrow(EvtcParseError);
    });
  });
});
