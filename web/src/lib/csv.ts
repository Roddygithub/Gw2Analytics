/**
 * Generic CSV (RFC 4180) serializer + browser download helper.
 *
 * Why a dedicated utility (vs a per-component hand-roll)
 * ======================================================
 * Four roll-up tables in the v0.7.1 web layer
 * (:class:`PlayersGrid`, :class:`TargetRollupsGrid` (3x),
 * :class:`SquadRollupsGrid`, :class:`SkillUsageTable`) all
 * need a one-click "Download CSV" affordance for analysts who
 * want to pull the data into Excel / Sheets / pandas. A
 * shared utility guarantees the same escaping rules across
 * all four surfaces, which is the canonical way to keep CSV
 * files interoperable with downstream tools.
 *
 * RFC 4180 escaping
 * =================
 * Fields containing ``,``, ``"``, ``\r``, or ``\n`` are
 * wrapped in double quotes; internal double quotes are
 * escaped by doubling (``"`` -> ``""``). Line terminator is
 * CRLF (the RFC 4180 default; also what Excel + Sheets +
 * pandas expect). A trailing CRLF is appended when the body
 * is non-empty so the file ends with a newline (matches
 * what most editors auto-insert).
 *
 * Browser download trigger
 * ========================
 * :func:`downloadCsv` wraps the CSV string in a ``Blob``,
 * creates a temporary ``URL.createObjectURL``, simulates a
 * click on a hidden ``<a download>``, and revokes the object
 * URL. The pattern works in all modern browsers without any
 * external dependency (no ``file-saver`` / ``streamsaver``
 * needed for this small payload size).
 */

export interface CsvColumn<TRow> {
  /** Pydantic field name on the row model (e.g. ``"total_damage"``). */
  field: keyof TRow & string;
  /** Column header text shown in the first CSV row. */
  headerName: string;
  /**
   * Optional fixed-decimal formatter for numeric columns. When
   * set, ``Number`` values are rendered as ``value.toFixed(decimals)``
   * (matches the on-screen ``decimals`` contract used by the
   * AG Grid column specs). When unset, the raw value is
   * stringified.
   */
  decimals?: number;
}

/**
 * Serialize ``rows`` as an RFC 4180 CSV string. The first row
 * is the header (built from ``columns[*].headerName``); each
 * subsequent row is one source row. Returns the empty string
 * when ``rows`` is empty (the caller can decide whether to
 * hide the download button in that case).
 */
export function toCsv<TRow>(
  rows: readonly TRow[],
  columns: readonly CsvColumn<TRow>[],
): string {
  if (columns.length === 0) return "";
  const header = columns.map((c) => csvEscape(c.headerName)).join(",");
  if (rows.length === 0) return header + "\r\n";
  const body = rows
    .map((row) =>
      columns
        .map((c) => {
          const raw = (row as Record<string, unknown>)[c.field];
          if (typeof raw === "number" && c.decimals !== undefined) {
            return raw.toFixed(c.decimals);
          }
          return csvEscape(raw);
        })
        .join(","),
    )
    .join("\r\n");
  return header + "\r\n" + body + "\r\n";
}

/**
 * Quote a single field per RFC 4180. ``null`` / ``undefined``
 * render as the empty string (so the column count stays
 * stable for sparse rows). Numbers and booleans are
 * stringified via ``String()``; everything else is coerced
 * to a string first.
 */
function csvEscape(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = typeof value === "string" ? value : String(value);
  if (/[",\r\n]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

/**
 * Browser-only: trigger a CSV file download. Creates a
 * temporary ``Blob``, ``URL.createObjectURL`` it, click a
 * hidden ``<a download>`` with the given filename, then
 * revoke the object URL. Safe to call in React event
 * handlers (the synthetic click is synchronous; the actual
 * download is async via the browser's download manager).
 */
export function downloadCsv(filename: string, csv: string): void {
  if (typeof document === "undefined" || typeof URL === "undefined") {
    // SSR safety net: a server-side render can never trigger
    // a browser download, so this branch is a defensive
    // no-op (callers gate the download button behind a
    // Client Component boundary anyway).
    return;
  }
  // The BOM (UTF-8 byte-order mark) tells Excel to treat the
  // file as UTF-8 instead of CP-1252; without it, non-ASCII
  // account / skill names (e.g. CJK characters) render as
  // mojibake. The cost is one BOM per file (~3 bytes) and
  // pandas / Sheets ignore it.
  const blob = new Blob(["\uFEFF", csv], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
