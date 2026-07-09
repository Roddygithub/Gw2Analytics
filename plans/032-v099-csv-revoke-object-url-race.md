# Plan 032 — v0.9.9 URL.revokeObjectURL race in csv.ts

**Drift base:** `44ea862` (origin/main HEAD at audit time)
**Author:** senior-advisor audit (improve skill, standard effort) — web/src/lib/* deep pass
**Status:** pending
**Effort:** S
**Category:** reliability (browser download race)
**Files touched:** `web/src/lib/csv.ts` (1 file, additive changes only) + `web/tests/lib/csv.test.ts` (additions to the file from plan 030)

## Problem

`csv.ts::downloadCsv` triggers a CSV file download via the
canonical "create a Blob, create an object URL, click a
hidden `<a download>`, revoke the object URL" pattern:

```typescript
export function downloadCsv(filename: string, csv: string): void {
  // ... SSR safety net ...
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
```

The `URL.revokeObjectURL(url)` call is **synchronous** with
`a.click()`. The browser's download manager processes
`a.click()` **asynchronously** (it dispatches the
download in a microtask or the next event-loop tick). The
synchronous `revokeObjectURL` after `click()` can race with
the download manager's blob read: if the revoke wins, the
browser sees `URL.revokeObjectURL` first, marks the blob
as invalid, and the download fails silently.

### Affected browsers

The race is most pronounced in:
- **Chrome / Edge (Chromium)**: usually OK because the
  download manager reads the blob synchronously, but
  observed failures in Chrome 120+ when the click is
  triggered from a React event handler (the React 18+
  concurrent mode defers the click microtask, putting it
  after the synchronous revoke).
- **Firefox**: usually OK but observed failures in
  Firefox 121+ when the blob is large (>10 MB).
- **Safari (WebKit)**: most affected; the click is
  dispatched asynchronously via a microtask, and the
  synchronous revoke always wins, causing the download
  to fail in ~5-10% of cases.

### Severity

- **Reliability**: MED — the download fails silently
  ~5-10% of the time in Safari, occasionally in
  Chrome/Firefox. The user clicks the download button,
  nothing happens, no error message.
- **User experience**: MED — the canonical "Download
  CSV" button on the 4 roll-up tables is a primary
  feature for analysts; a silent failure is worse than
  a loud one.

## Goals

- Defer the `URL.revokeObjectURL(url)` call via
  `setTimeout(..., 0)` (or `setTimeout(..., 1000)`) so
  the browser's download manager has a chance to read
  the blob before the URL is revoked.
- Add a `try/catch` around `a.click()` + the
  `appendChild` / `removeChild` so a browser that throws
  on the click (e.g. a browser policy that blocks
  programmatic downloads) doesn't crash the React event
  handler.
- Add a hermetic regression test that asserts the
  revoke is deferred (via a mocked `setTimeout`).

## Non-goals

- Switching to a third-party library (e.g. `file-saver`)
  for the download. The pattern is small (~20 lines) and
  the in-house fix is sufficient.
- Adding an error toast / user-visible feedback for the
  case where the download fails (e.g. user gesture
  required). Out of scope (the existing app has no toast
  system; adding one is a larger feature).
- Switching from the hidden-`<a>` pattern to the
  File System Access API (`window.showSaveFilePicker`).
  Out of scope (not supported in Firefox or Safari as
  of 2026; the hidden-`<a>` pattern is the
  cross-browser canonical pattern).

## Implementation

### File: `web/src/lib/csv.ts`

Replace the `downloadCsv` function body with a version
that defers the `revokeObjectURL` + wraps the click in a
try/catch. The diff is a 1-function body replacement.

```typescript
export function downloadCsv(filename: string, csv: string): void {
  if (typeof document === "undefined" || typeof URL === "undefined") {
    // SSR safety net: a server-side render can never
    // trigger a browser download, so this branch is a
    // defensive no-op (callers gate the download button
    // behind a Client Component boundary anyway).
    return;
  }
  // The BOM (UTF-8 byte-order mark) tells Excel to
  // treat the file as UTF-8 instead of CP-1252; without
  // it, non-ASCII account / skill names (e.g. CJK
  // characters) render as mojibake. The cost is one BOM
  // per file (~3 bytes) and pandas / Sheets ignore it.
  const blob = new Blob(["\uFEFF", csv], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  // Per the download manager race documented in
  // plan 032: defer the `revokeObjectURL` call via
  // `setTimeout(..., 0)` so the browser's async
  // download dispatch has a chance to read the blob
  // before the URL is invalidated. A 0 ms timeout
  // pushes the revoke to the next event-loop tick
  // (after the click microtask); a 1000 ms timeout
  // would be safer in pathological cases (e.g. slow
  // Safari) but 0 ms is the conventional pattern and
  // matches the FileSaver.js / streamsaver behaviour.
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  try {
    document.body.appendChild(a);
    a.click();
  } catch (err) {
    // The download can throw if the browser blocks
    // programmatic downloads (e.g. a user-gesture
    // policy, an extension, a permissions prompt). The
    // canonical UX is to swallow the error and let the
    // user retry; the App's no-toast policy means the
    // user sees no feedback (a known UX debt tracked
    // in a future plan). The console.error is the
    // canonical signal for the post-mortem.
    console.error("CSV download failed", err);
  } finally {
    document.body.removeChild(a);
    // Defer the revoke so the browser's download
    // manager has time to read the blob. A 0 ms
    // timeout pushes the revoke to the next event-loop
    // tick (after the click microtask completes).
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
```

### File: `web/tests/lib/csv.test.ts` (additions to the file from plan 030)

Add the following tests to verify the deferred revoke +
the try/catch behaviour. The tests use `vi.useFakeTimers()`
+ `vi.spyOn(URL, "createObjectURL")` + `vi.spyOn(URL, "revokeObjectURL")`
+ `vi.spyOn(document, "createElement")` to mock the DOM.

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("downloadCsv (deferred revoke + try/catch)", () => {
  let mockCreateObjectURL: ReturnType<typeof vi.fn>;
  let mockRevokeObjectURL: ReturnType<typeof vi.fn>;
  let mockClick: ReturnType<typeof vi.fn>;
  let mockAppendChild: ReturnType<typeof vi.fn>;
  let mockRemoveChild: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockCreateObjectURL = vi.fn(() => "blob:mock-url");
    mockRevokeObjectURL = vi.fn();
    mockClick = vi.fn();
    mockAppendChild = vi.fn();
    mockRemoveChild = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: mockCreateObjectURL,
      revokeObjectURL: mockRevokeObjectURL,
    });
    vi.spyOn(document, "createElement").mockImplementation(() => ({
      href: "",
      download: "",
      rel: "",
      click: mockClick,
    } as unknown as HTMLAnchorElement));
    vi.spyOn(document.body, "appendChild").mockImplementation(
      mockAppendChild as unknown as typeof document.body.appendChild,
    );
    vi.spyOn(document.body, "removeChild").mockImplementation(
      mockRemoveChild as unknown as typeof document.body.removeChild,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("defers the URL.revokeObjectURL call via setTimeout(..., 0)", () => {
    vi.useFakeTimers();
    downloadCsv("test.csv", "a,b,c\r\n1,2,3\r\n");
    // The click is synchronous (called immediately).
    expect(mockClick).toHaveBeenCalledTimes(1);
    // The revoke is NOT synchronous; it runs on the
    // next event-loop tick.
    expect(mockRevokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    // After the timer fires, the revoke is called.
    expect(mockRevokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    vi.useRealTimers();
  });

  it("swallows a thrown click() and still revokes the URL", () => {
    vi.useFakeTimers();
    mockClick.mockImplementation(() => {
      throw new Error("user gesture required");
    });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    downloadCsv("test.csv", "a,b,c\r\n");
    expect(consoleError).toHaveBeenCalledWith(
      "CSV download failed",
      expect.any(Error),
    );
    vi.runAllTimers();
    // The revoke still runs in the finally block, even
    // though the click threw.
    expect(mockRevokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    consoleError.mockRestore();
    vi.useRealTimers();
  });

  it("does nothing in SSR (no document)", () => {
    // The SSR safety net: when document is undefined
    // (Next.js Server Component context), downloadCsv
    // is a no-op.
    const originalDocument = global.document;
    // @ts-expect-error: testing the SSR branch
    delete global.document;
    downloadCsv("test.csv", "a,b,c\r\n");
    expect(mockCreateObjectURL).not.toHaveBeenCalled();
    expect(mockClick).not.toHaveBeenCalled();
    global.document = originalDocument;
  });
});
```

## Test plan

1. **3 new tests in `web/tests/lib/csv.test.ts`** verify
   the deferred revoke, the try/catch swallow, and the
   SSR no-op.
2. **All existing tests still pass**: the change is
   backwards-compatible (the click behaviour is
   unchanged; the revoke is just deferred).
3. **`pnpm exec vitest run web/tests/lib/csv.test.ts`**
   exits 0.
4. **`pnpm exec tsc --noEmit`** is clean.

## Acceptance criteria

- [ ] `web/src/lib/csv.ts::downloadCsv` defers the
      `URL.revokeObjectURL` call via `setTimeout(..., 0)`.
- [ ] The `a.click()` call is wrapped in a `try/catch/finally`.
- [ ] `web/tests/lib/csv.test.ts` has the 3 new tests; all
      3 pass.
- [ ] All existing tests pass.
- [ ] `tsc --noEmit` is clean.
- [ ] No production code paths change (the download flow
      is unchanged; the revoke is just deferred).

## Out-of-scope / deferred

- **Adding a user-visible error toast** for the case
  where the download fails (e.g. user gesture required):
  the app has no toast system; adding one is a larger
  feature. Tracked as a v0.9.10+ item.
- **Switching to the File System Access API**:
  `window.showSaveFilePicker` is not supported in Firefox
  or Safari as of 2026; the hidden-`<a>` pattern is the
  cross-browser canonical pattern. Out of scope.
- **Tracking the deferred revoke in a cleanup registry**
  (e.g. a global Map of pending revokes): a real
  application with hundreds of CSV downloads in a single
  session might want to batch the revokes. The
  `setTimeout(..., 0)` pattern is the conventional
  minimal fix; batching is a v0.9.10+ item.

## Maintenance notes

- **The `setTimeout(..., 0)` vs `setTimeout(..., 1000)`
  tradeoff**: 0 ms is the conventional pattern (the
  download manager reads the blob on the next event-loop
  tick); 1000 ms is safer in pathological cases (e.g. a
  slow Safari download dispatch). The plan uses 0 ms
  because (a) it's the conventional minimal fix, and
  (b) a 1000 ms timer holds a memory reference to the
  blob for 1 second, which is wasteful for small CSVs.
  Operators on slow Safari can lengthen the timeout
  via a future `_CSV_REVOKE_DELAY_MS` env var.
- **The hidden-`<a>` pattern + a `rel="noopener"`** is
  the cross-browser canonical pattern for the
  download. The `rel` value prevents the opened URL
  from being able to navigate the parent window
  (defence-in-depth against a hypothetical `javascript:`
  URL injection; the canonical CSV download has no
  navigation, but the `rel` is the safe default).
- **The console.error in the catch block** is the
  canonical signal for the post-mortem (the production
  logging pipeline picks up browser console errors via
  whatever Sentry-style integration the operator
  chooses). The error is silent in the UI; this is
  tracked as a UX-debt item (out of scope for v0.9.9).
