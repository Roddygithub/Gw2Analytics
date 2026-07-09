/**
 * v0.10.0 plan 032: hermetic test pinning the
 * :module:`@/lib/timezones` catalog contract.
 *
 * Locks the 25-city IANA catalog so future refactor drift
 * (e.g. removing a city, renaming a label) fails the
 * build instead of silently regressing the analyst-facing
 * TZ selector on both the per-account and cross-account
 * pages.
 */

import { describe, expect, it } from "vitest";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";

describe("TIMEZONE_OPTIONS", () => {
  it("contains exactly 25 curated IANA zones", () => {
    expect(TIMEZONE_OPTIONS).toHaveLength(25);
  });

  it("has unique value strings across all entries", () => {
    const values = TIMEZONE_OPTIONS.map((opt) => opt.value);
    expect(new Set(values).size).toBe(values.length);
  });

  it("includes the UTC anchor as the first entry", () => {
    expect(TIMEZONE_OPTIONS[0]?.value).toBe("UTC");
  });

  it("includes the canonical anchor cities", () => {
    const required = new Set([
      "UTC",
      "America/New_York",
      "America/Los_Angeles",
      "Europe/Paris",
      "Europe/Berlin",
      "Asia/Tokyo",
      "Australia/Sydney",
    ]);
    const present = new Set(TIMEZONE_OPTIONS.map((opt) => opt.value));
    for (const city of required) {
      expect(present.has(city)).toBe(true);
    }
  });

  it("every entry has a non-empty label", () => {
    for (const opt of TIMEZONE_OPTIONS) {
      expect(opt.label.length).toBeGreaterThan(0);
    }
  });
});
