import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * EVTC magic-bytes validation against the GW2 ArcDPS-evtc log format
 * spec (https://github.com/baaron4/GW2-ArcDPS-Bridge/blob/master/evtc.md).
 *
 * The 4-byte ASCII magic ``EVTC`` precedes a 4-byte build-number hash
 * (``20240101`` here is the upstream stub build timestamp). Bytes
 * 12\u201331 are reserved. Real ArcDPS EVTC logs continue with combat-
 * event records; this stub is only 648 bytes total \u2014 enough to test
 * that the magic-bytes + header shape are intact on-disk.
 */
const FIXTURE_PATH = join(__dirname, "..", "fixtures", "zevtc", "test_combat.evtc");

describe("EVTC binary fixture integrity", () => {
  it("loads from the local fixture path", () => {
    const buf = readFileSync(FIXTURE_PATH);
    expect(buf.length).toBeGreaterThanOrEqual(16);
  });

  it("starts with the EVTC magic (4 ASCII bytes)", () => {
    const buf = readFileSync(FIXTURE_PATH);
    expect(buf.subarray(0, 4).toString("utf8")).toBe("EVTC");
  });

  it("carries the 2024-01-01 stub build timestamp in bytes 4\u201311", () => {
    const buf = readFileSync(FIXTURE_PATH);
    expect(buf.subarray(4, 8).toString("utf8")).toBe("2024");
    // Bytes 8\u201311 are \u"0101\u" in the upstream stub \u2014 stable contract for our test.
    expect(buf.subarray(8, 12).toString("utf8")).toBe("0101");
  });

  it("includes a non-zero aggregate-prefix byte at offset 12", () => {
    const buf = readFileSync(FIXTURE_PATH);
    // byte 12 is the start of the byte-12\u201331 reserved area. The stub
    // uses ``0x01`` for the first byte of this area; this guards against
    // future fixture rotation to a fully-zero header.
    expect(buf[12]).toBeGreaterThan(0);
  });
});
