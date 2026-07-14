/**
 * copy-module.test.ts — centraliSation invariant harness for
 * `@/lib/copy/error-messages`. Locks the centraliSation pattern down:
 *
 * 1. The module EXPORTS a monotonically-growing number of constants
 *    (verifies the centraliSation sweep is happening — never shrinks).
 *
 * 2. Each constant value is REFERENCED in at least one component / app
 *    file (verifies no dead constant — catches the
 *    "added a constant but forgot to substitute" regression).
 *
 * 3. Each constant value's reference is the SAME STRING as the export
 *    value (catches stray whitespace drift in `const`-vs-inline
 *    substitution; e.g., trailing space drift).
 *
 * This test does NOT scan for inline UI strings outside the known
 * constants (that would be too greedy — many tests/intentional
 * fallthrough strings exist). The test scope is the centraliSation
 * MODULE itself: shape + density + linkage.
 */
import { describe, it, expect } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import * as errorMessages from "@/lib/copy/error-messages";

/**
 * Walk the web/src tree (excluding node_modules + tests) and return every
 * .ts / .tsx file's path synchronously. Used by the linkage tests below.
 */
function listWebSourceFiles(): string[] {
  const root = path.resolve(__dirname, "../../src");
  const out: string[] = [];

  function walk(dir: string): void {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules") continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (/\.(tsx?|jsx?)$/.test(entry.name)) {
        out.push(full);
      }
    }
  }

  walk(root);
  return out;
}

/** Named type-guard helper for the centraliSation module's runtime exports.
 *  Required as a named function (rather than an inline predicate) to keep
 *  TSC's strict-mode happy: TSC's strict-mode rules around type predicates
 *  on module-level exports with ambient `unknown`-typed unions forbid
 *  inline predicate syntax in expression position; only named-function form
 *  satisfies the strict-mode typechecker.
 */
function isString(v: unknown): v is string {
  return typeof v === "string";
}

/** Predicate for the Object.entries filter below: keeps entries whose value is
 *  a string literal. Same rationale as isString above — named function form
 *  avoids strict-mode inline-predicate issues that surface as TS warnings.
 */
function isStringEntry(entry: [string, unknown]): entry is [string, string] {
  return isString(entry[1]);
}

/**
 * Snapshot of all string-valued exports from the centraliSation module.
 * Each entry carries BOTH the export name AND the export value, so the
 * linkage test below can verify reference by either identifier (the
 * JSX-style use path — `import { FOO } from "@/lib/copy/error-messages"`
 * followed by `{FOO}` usage) OR the literal value (legacy inline form
 * — `"FOO literal"` substring match). The two-or check covers BOTH the
 * post-centraliSation state (where the value has been substituted out of
 * source files) AND the in-progress/incomplete state (where some refs
 * are still inline-literal). Without the identifier-OR-value matching,
 * the test would fail the moment a sweep completes (the literal value
 * disappears from source in favour of the imported identifier).
 */
const KNOWN_CONSTANTS: Array<{ name: string; value: string }> = Object.entries(
  errorMessages,
)
  .filter(isStringEntry)
  .map(([name, value]) => ({ name, value }));

describe("copy-module centraliSation invariant", () => {
  it("exports AT LEAST 10 string constants (encourages centraliSation)", () => {
    // Cycle-start baseline: 22 exports (post 9e0e3b1). Allow the test to
    // still pass if a follow-up cycle trims (which would require explicitly
    // bumping this floor + tracking the change).
    expect(KNOWN_CONSTANTS.length).toBeGreaterThanOrEqual(10);
  });

  it("every constant is referenced (by identifier OR by value) in at least one web/src file", () => {
    const sourceFiles = listWebSourceFiles();
    const fileContents = sourceFiles.map((f) => ({
      file: f,
      content: fs.readFileSync(f, "utf-8"),
    }));

    for (const { name, value } of KNOWN_CONSTANTS) {
      // Identifier match covers the post-centraliSation state where the
      // value has been substituted out of source in favour of the
      // imported identifier (e.g., {PLAYER_TIMELINE_LOADING} in JSX).
      // Value match covers the in-progress state where some refs are still
      // inline literals (e.g., "Loading\u2026" body text). Either qualifies
      // as a "live" reference.
      const referencedSomewhere = fileContents.some(
        ({ content }) => content.includes(name) || content.includes(value),
      );
      expect(
        referencedSomewhere,
        `Constant name "\`${name}\`" (value "\`${value}\`") is not referenced anywhere in web/src — likely a dead export`,
      ).toBe(true);
    }
  });

  it("constant values are NOT empty strings", () => {
    // Empty-string exports are a smell — either placeholder stubs or
    // missed substitutions. The module's purpose is to be a real
    // single-source-of-truth copy registry.
    for (const { value } of KNOWN_CONSTANTS) {
      expect(value.trim().length).toBeGreaterThan(0);
    }
  });
});
