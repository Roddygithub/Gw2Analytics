import { describe, expect, it } from "vitest";
import {
  formatSubgroup,
  formatRoles,
  formatCommanderIcon,
} from "@/components/PlayerReadoutBase";

describe("PlayerReadoutBase formatters", () => {
  describe("formatSubgroup", () => {
    it("returns '(no squad)' for null or undefined", () => {
      expect(formatSubgroup(null)).toBe("(no squad)");
      expect(formatSubgroup(undefined)).toBe("(no squad)");
    });

    it("formats positive integers as 'Sub N'", () => {
      expect(formatSubgroup(1)).toBe("Sub 1");
      expect(formatSubgroup(42)).toBe("Sub 42");
    });

    it("returns '(no squad)' for zero", () => {
      expect(formatSubgroup(0)).toBe("(no squad)");
    });

    it("returns the string value for non-empty strings", () => {
      expect(formatSubgroup("Alpha")).toBe("Alpha");
    });

    it("returns '(no squad)' for empty strings", () => {
      expect(formatSubgroup("")).toBe("(no squad)");
    });
  });

  describe("formatRoles", () => {
    it("returns an empty string for null, undefined, or empty arrays", () => {
      expect(formatRoles(null)).toBe("");
      expect(formatRoles(undefined)).toBe("");
      expect(formatRoles([])).toBe("");
    });

    it("joins roles with a slash", () => {
      expect(formatRoles(["DPS", "STRIP"])).toBe("DPS/STRIP");
      expect(formatRoles(["HEAL", "Boon", "Support"])).toBe("HEAL/Boon/Support");
    });
  });

  describe("formatCommanderIcon", () => {
    it("returns the crown glyph for true", () => {
      expect(formatCommanderIcon(true)).toBe("★");
    });

    it("returns an empty string for any non-true value", () => {
      expect(formatCommanderIcon(false)).toBe("");
      expect(formatCommanderIcon(null)).toBe("");
      expect(formatCommanderIcon(undefined)).toBe("");
      expect(formatCommanderIcon("yes")).toBe("");
    });
  });
});
