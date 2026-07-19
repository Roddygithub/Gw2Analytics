import { describe, expect, test } from "vitest";

import { safeFileLabel } from "./string";

describe("safeFileLabel", () => {
  test("returns the basename of a normal path", () => {
    expect(safeFileLabel("/home/user/fight.zevtc")).toBe("fight.zevtc");
  });

  test("replaces spaces and special characters with underscores", () => {
    expect(safeFileLabel("/tmp/my fight @home.zevtc")).toBe("my_fight_home.zevtc");
  });

  test("collapses multiple consecutive special characters", () => {
    expect(safeFileLabel("/tmp/fight!!!@@@home.zevtc")).toBe("fight_home.zevtc");
  });

  test("falls back to 'file' when the sanitized result is empty", () => {
    expect(safeFileLabel("!!!")).toBe("file");
    expect(safeFileLabel("")).toBe("file");
  });

  test("truncates very long filenames", () => {
    const longName = "a".repeat(200);
    expect(safeFileLabel(longName)).toHaveLength(80);
  });
});
