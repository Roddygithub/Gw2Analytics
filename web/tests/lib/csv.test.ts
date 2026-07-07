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
