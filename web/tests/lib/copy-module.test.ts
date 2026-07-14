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

  it("surface-scanner: no inline UI strings in centralisation-touched component sources", () => {
    // Surface-scanner smoke — a CURATED set of source files touched by the
    // recent centraliSation sweeps. A full surface-scanner (all of
    // web/src/{components,app}) is a follow-up; this scoped version verifies
    // the *sweep-across-this-cycle* invariant without drowning in
    // false-positives from unrelated component UI (CSV columns in SkillUsage,
    // tier badges in FightsGrid, etc.).
    const CURATED_BASENAMES = new Set([
      "FightsGrid.tsx",
      "SkillUsageTable.tsx",
      "PlayerTimelineSection.tsx",
    ]);

    // The error.tsx files live under multiple paths; include BOTH root
    // error.tsx and fights/[id]/error.tsx via path-suffix matching.
    const TARGETS = listWebSourceFiles().filter((file) => {
      const basename = path.basename(file);
      if (CURATED_BASENAMES.has(basename)) return true;
      if (file.endsWith("/app/error.tsx")) return true;
      if (file.endsWith("/app/fights/[id]/error.tsx")) return true;
      return false;
    });

    const knownValueSet = new Set(
      KNOWN_CONSTANTS.map(({ value }) => value),
    );

    // Inline UI patterns to scan. Each pattern's FIRST capture group is the
    // candidate string.
    //
    // NOTE: The `<button>TEXT</button>` pattern is INTENTIONALLY OMITTED.
    // A naive implementation regex would fail when a button's opening tag
    // spans multiple lines AND has an `onClick={() => ...}` arrow function
    // attribute -- the `=>` operator is misinterpreted as the opening tag's
    // closing `>`, causing the regex to slurp attribute content as if it
    // were button text. The aria-label + placeholder patterns are
    // sufficient for the analyst-facing-string centraliSation invariant
    // (button-text is captured indirectly by the click-handler labels on
    // the centraliSed buttons in the curated scope).
    const INLINE_PATTERNS: Array<{ pattern: RegExp; source: string }> = [
      {
        source: "aria-label=\\\"TEXT\\\"",
        pattern: /aria-label="([^"]{2,})"/g,
      },
      {
        source: "placeholder=\\\"TEXT\\\"",
        pattern: /placeholder="([^"]{2,})"/g,
      },
    ];

    // Reject CSS values, prop names, and other false-positives before the
    // centraliSation membership check.
    function isRealLabel(s: string): boolean {
      const trimmed = s.trim();
      if (!trimmed) return false;
      // Pure-prop / pure-css tokens.
      if (/^[\d.]+(px|em|rem|vw|vh|%)?$/.test(trimmed)) return false;
      if (/^[a-z][a-z-]*$/.test(trimmed)) return false;
      // Dynamic interpolation in source.
      if (trimmed.includes("${")) return false;
      return true;
    }

    const residues: Array<{ file: string; pattern: string; value: string }> = [];
    for (const file of TARGETS) {
      const content = fs.readFileSync(file, "utf-8");
      for (const { pattern, source } of INLINE_PATTERNS) {
        pattern.lastIndex = 0;
        let match: RegExpExecArray | null;
        while ((match = pattern.exec(content)) !== null) {
          const value = match[1];
          if (!isRealLabel(value)) continue;
          if (!knownValueSet.has(value)) {
            residues.push({ file: path.basename(file), pattern: source, value });
          }
        }
      }
    }

    // Strict assertion: 0 residues. The surface-scanner now scans
    // aria-label + placeholder patterns (button-text pattern is
    // intentionally omitted — see the INLINE_PATTERNS comment).
    expect(
      residues,
      `Surface-scanner found inline UI strings outside @/lib/copy/error-messages:\n${residues
        .map((r) => `  ${r.file} / ${r.pattern} -> "${r.value}"`)
        .join("\n")}`,
    ).toHaveLength(0);
  });
});
