import { existsSync } from "node:fs";

/**
 * Parse the comma-separated list of large .zevtc files from the
 * environment.
 *
 * Supports both the new ``E2E_ZEVTC_LARGE_PATHS`` (comma-separated) and
 * the legacy ``E2E_ZEVTC_LARGE_PATH`` (single file). Non-existent paths
 * are filtered out so tests can skip cleanly.
 */
export function parseLargeZevtcPaths(): string[] {
  const raw = process.env.E2E_ZEVTC_LARGE_PATHS ?? process.env.E2E_ZEVTC_LARGE_PATH ?? "";
  return raw
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean)
    .filter((p) => existsSync(p));
}
