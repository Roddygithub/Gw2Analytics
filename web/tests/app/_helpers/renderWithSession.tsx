/**
 * Test helper that resets the ``fetchCached`` mock cache + renders a
 * tree with a per-call ``vi.mocked(fetchCached).mockReset()`` cycle.
 *
 * Extracted from the inline pattern duplicated across
 * :file:`web/tests/app/fight-events-page.test.tsx` and (future) other
 * page-level tests. The original per-test pattern:
 *
 *     beforeEach(() => mockFightFetch());
 *     render(tree);
 *
 * ...leaks ``fetchCached`` mock state across tests if the dispatch
 * table is not explicitly cleared (``vi.mocked(fn).mockImplementation``
 * chains do NOT cascade with vitest's per-file reset). The helper
 * centralises the reset on every call so per-test call sites need
 * only ``renderWithSession(tree)``.
 *
 * Static top-level imports work for both scenarios — whether
 * :file:`web/tests/setup.ts` mocks the module or per-file mocks
 * establish the canonical mock — because vitest 3.x hoists ``vi.mock``
 * calls BEFORE the helper's static imports run, so the imported
 * :func:`fetchCached` resolves to the canonical mock fn at load time.
 *
 * v0.10.27-pre plan 168 Bullet 1.
 *
 * Mirrors the vi.mock-then-static-import pattern at
 * :file:`web/tests/app/fight-events-page.test.tsx` (factory at
 * lines 47-52, static import at line 56; canonical precedent in
 * this codebase). Helper/precedent drift detection: if this
 * comment's file:line reference no longer resolves, an alignment
 * audit is required.
 */

import type { ReactElement } from "react";
import { render, type RenderResult } from "@testing-library/react";
import { vi } from "vitest";

import { fetchCached } from "@/lib/fetchCached";

/**
 * Clear all ``fetchCached`` mock slots so the next test starts from
 * a clean dispatch table. Companion helper exported for tests that
 * need to reset the cache mid-test (between ``act(() => ...)``
 * assertions in the same ``it`` body) without re-running the full
 * ``renderWithSession`` wrapper. NOT a hot path — called once per
 * test in the common case.
 *
 * Scoped to ``vi.mocked(fetchCached)`` rather than ``vi.clearAllMocks()``
 * because the latter resets ``vi.fn()`` bookkeeping across other test
 * files in the same worker; ~3 ms/test at the vitest 3.2.7 baseline.
 */
export function resetFetchCachedMock(): void {
  vi.mocked(fetchCached).mockReset();
}

/**
 * Render a Server Component tree with a freshly-reset ``fetchCached``
 * mock dispatch table.
 *
 * @param ui the React element (typically the awaited result of a
 *   page's Server-Component entry point, ``FightEventsPage({ params, searchParams })``)
 * @returns the RTL ``render`` result so callers can chain ``screen.*``
 *   queries against the freshly-mounted DOM
 */
export function renderWithSession(ui: ReactElement): RenderResult {
  // Thin alias for ``render`` today. The companion
  // :func:`resetFetchCachedMock` is exported separately so tests
  // that need an explicit mid-test reset (between ``act(() => ...)``
  // assertions in the same ``it`` body) can opt-in. Auto-resetting
  // on every ``renderWithSession`` call would collide with the
  // project's per-test ``mockFightFetch({ ... })`` override pattern
  // in :file:`web/tests/app/fight-events-page.test.tsx` (the
  // override is set BEFORE ``renderWithSession(tree)`` and must
  // stay in place when the page calls ``fetchCached``); an
  // unconditional reset would wipe the override, leaving the page
  // with no mock implementation. Manual explicit reset is the
  // safer contract.
  return render(ui);
}
