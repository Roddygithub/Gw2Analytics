import { describe, it, expect } from "vitest";
import { join } from "node:path";
import {
  parseEvtcFile,
  parseEvtcBuffer,
  EvtcParseError,
} from "@/lib/evtc-parser";

/**
 * Vitest module for the EVTC parser stub fixture.
 *
 * The parser is exercised against the 648-byte stub fixture shipped
 * in ``tests/fixtures/zevtc/test_combat.evtc``. The assertion set
 * covers:
 *  - magic-bytes verbatim (``EVTC``)
 *  - digit-shape build + day stamp
 *  - non-zero prefix byte
 *  - payload string extraction (the upstream stub embeds
 *    ``Ranger1``, ``Ranger.1111``, ``Stability``, ``Might``,
 *    ``Sword Strike``)
 *  - error path on magic mismatch + short buffer
 *
 * Real ArcDPS combat-event decoding is out-of-scope for this stub fixture test.
 */
const FIXTURE_PATH = join(
  __dirname,
  "..",
  "fixtures",
  "zevtc",
  "test_combat.evtc",
);

describe("evtc-parser (stub fixture)", () => {
  describe("parseEvtcFile", () => {
    it("loads + parses the stub fixture", () => {
      const result = parseEvtcFile(FIXTURE_PATH);
      expect(result).toBeDefined();
      expect(result.header).toBeDefined();
      expect(result.payload).toBeDefined();
    });

    it("extracts the EVTC magic verbatim", () => {
      const result = parseEvtcFile(FIXTURE_PATH);
      expect(result.header.magic).toBe("EVTC");
    });

    it("extracts the digit-shape build + day stamp", () => {
      const result = parseEvtcFile(FIXTURE_PATH);
      expect(result.header.buildYear).toMatch(/^[0-9]{4}$/);
      expect(result.header.dayMark).toMatch(/^[0-9]{4}$/);
    });

    it("extracts the non-zero reserved-prefix byte", () => {
      const result = parseEvtcFile(FIXTURE_PATH);
      expect(result.header.prefixByte).toBeGreaterThan(0);
    });

    it("extracts the stub player name as the first ASCII string", () => {
      const result = parseEvtcFile(FIXTURE_PATH);
      expect(result.payload.player).toBe("Ranger1");
    });

    it("extracts the stub account name as the dotted ASCII string", () => {
      const result = parseEvtcFile(FIXTURE_PATH);
      expect(result.payload.account).toBe("Ranger.1111");
    });

    it("surfaces the boon + skill strings", () => {
      const result = parseEvtcFile(FIXTURE_PATH);
      expect(result.payload.boonsAndSkills).toContain("Stability");
      expect(result.payload.boonsAndSkills).toContain("Might");
      expect(result.payload.boonsAndSkills).toContain("Sword Strike");
    });
  });

  describe("parseEvtcBuffer", () => {
    it("parses a freshly-built minimal EVTC buffer", () => {
      const buf = new Uint8Array(64);
      const dv = new DataView(buf.buffer);
      // Magic
      buf[0] = 0x45;
      buf[1] = 0x56;
      buf[2] = 0x54;
      buf[3] = 0x43;
      // Build year ASCII
      buf[4] = 0x32;
      buf[5] = 0x30;
      buf[6] = 0x32;
      buf[7] = 0x35;
      // Day mark ASCII
      buf[8] = 0x30;
      buf[9] = 0x37;
      buf[10] = 0x30;
      buf[11] = 0x31;
      // Prefix byte
      buf[12] = 0x01;
      // Player name "Boromir" + null at offset 32
      const player = "Boromir";
      for (let i = 0; i < player.length; i++) buf[32 + i] = player.charCodeAt(i);
      buf[32 + player.length] = 0x00;
      // Account name "Boromir.2222" at offset 33+(name length).
      const acct = "Boromir.2222";
      const acctStart = 32 + player.length + 1;
      for (let i = 0; i < acct.length; i++)
        buf[acctStart + i] = acct.charCodeAt(i);
      buf[acctStart + acct.length] = 0x00;
      const result = parseEvtcBuffer(buf);
      expect(result.header.magic).toBe("EVTC");
      expect(result.header.buildYear).toBe("2025");
      expect(result.header.dayMark).toBe("0701");
      expect(result.payload.player).toBe("Boromir");
      expect(result.payload.account).toBe("Boromir.2222");
      // Reference dv so tsc-strict + node:fs happy.
      expect(dv.byteLength).toBe(64);
    });
  });

  describe("EvtcParseError", () => {
    it("throws on a non-EVTC magic", () => {
      const buf = new Uint8Array(64);
      buf[0] = 0x58;
      buf[1] = 0x4d;
      buf[2] = 0x4c;
      buf[3] = 0x44; // "XMLD" -- gibberish
      expect(() => parseEvtcBuffer(buf)).toThrow(EvtcParseError);
    });

    it("throws on a too-short buffer", () => {
      const buf = new Uint8Array(16);
      buf[0] = 0x45;
      buf[1] = 0x56;
      buf[2] = 0x54;
      buf[3] = 0x43;
      expect(() => parseEvtcBuffer(buf)).toThrow(EvtcParseError);
    });
  });
});
