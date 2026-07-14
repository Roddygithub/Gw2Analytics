import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

/**
 * EVTC magic-bytes validation against the GW2 ArcDPS-evtc log format
 * spec (the upstream ArcDPS evtc.h record format (see the GW2 community "gw2evtc" project for the canonical spec)).
 *
 * The 4-byte ASCII magic ``EVTC`` precedes a 4-byte build-number hash
 * plus a 4-byte day-number stamp. Bytes 12\u201331 are reserved; combat-event
 * records follow. We assert only the canonical contract:
 *  - the 4-byte magic is exactly ``EVTC`` (the only fixed invariant),
 *  - bytes 4\u201311 are ASCII digits (build + day markers; values rotate
 *    per upstream stub),
 *  - the reserved-prefix byte at offset 12 is non-zero (guards
 *    against a fully-zero header truncation).
 *
 * Real ArcDPS EVTC logs are megabytes; this stub stays small.
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

  /**
   * Bytes 4\u201311 are the build-timestamp + day-stamp markers. Per the EVTC
   * spec they are 8 reserved bytes; per the upstream stub they happen
   * to be ASCII digits ("2024" + "0101"). We assert the digit-shape
   * contract without locking to a specific value, so future fixture
   * rotations don't break this test.
   */
  it("uses ASCII-digit build + day markers in bytes 4\u201311", () => {
    const buf = readFileSync(FIXTURE_PATH);
    const field = buf.subarray(4, 12).toString("utf8");
    expect(field).toMatch(/^[0-9]{8}$/);
  });

  it("has a non-zero aggregate-prefix byte at offset 12", () => {
    const buf = readFileSync(FIXTURE_PATH);
    expect(buf[12]).toBeGreaterThan(0);
  });
});
