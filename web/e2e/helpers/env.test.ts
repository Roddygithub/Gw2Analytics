import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { beforeEach, describe, expect, test, vi } from "vitest";

import { parseLargeZevtcPaths } from "./env";

describe("parseLargeZevtcPaths", () => {
  let tempDir = "";

  beforeEach(() => {
    vi.unstubAllEnvs();
    tempDir = mkdtempSync(join(tmpdir(), "gw2a-e2e-"));
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    if (tempDir) {
      try {
        rmSync(tempDir, { recursive: true, force: true });
      } catch {
        /* best-effort cleanup */
      }
    }
  });

  test("returns an empty array when no env var is set", () => {
    vi.stubEnv("E2E_ZEVTC_LARGE_PATHS", undefined);
    vi.stubEnv("E2E_ZEVTC_LARGE_PATH", undefined);
    expect(parseLargeZevtcPaths()).toEqual([]);
  });

  test("splits a comma-separated list and filters non-existent files", () => {
    vi.stubEnv("E2E_ZEVTC_LARGE_PATHS", "/tmp/fake1.zevtc,/tmp/fake2.zevtc");
    expect(parseLargeZevtcPaths()).toEqual([]);
  });

  test("includes only existing files", () => {
    const realFile = join(tempDir, "real.zevtc");
    writeFileSync(realFile, "EVTC");
    vi.stubEnv("E2E_ZEVTC_LARGE_PATHS", `${realFile},/tmp/fake.zevtc`);
    expect(parseLargeZevtcPaths()).toEqual([realFile]);
  });

  test("falls back to E2E_ZEVTC_LARGE_PATH when PATHS is unset", () => {
    const realFile = join(tempDir, "legacy.zevtc");
    writeFileSync(realFile, "EVTC");
    vi.stubEnv("E2E_ZEVTC_LARGE_PATH", realFile);
    expect(parseLargeZevtcPaths()).toEqual([realFile]);
  });
});
