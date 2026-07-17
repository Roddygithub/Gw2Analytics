import { describe, expect, it } from "vitest";
import { formatSecondsLabel } from "@/lib/format";

describe("formatSecondsLabel", () => {
  it("formats zero milliseconds as 0:00", () => {
    expect(formatSecondsLabel(0)).toBe("0:00");
  });

  it("formats seconds with zero-padding", () => {
    expect(formatSecondsLabel(5_000)).toBe("0:05");
  });

  it("formats minutes and seconds", () => {
    expect(formatSecondsLabel(65_000)).toBe("1:05");
  });

  it("rounds down fractional seconds", () => {
    expect(formatSecondsLabel(5_999)).toBe("0:05");
  });

  it("formats an exact minute boundary", () => {
    expect(formatSecondsLabel(60_000)).toBe("1:00");
  });

  it("formats durations longer than one hour", () => {
    expect(formatSecondsLabel(3_600_000)).toBe("60:00");
  });
});
