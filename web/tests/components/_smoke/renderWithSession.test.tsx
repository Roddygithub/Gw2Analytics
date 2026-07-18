/**
 * Pilot test for the :func:`renderWithSession` helper (plan 168
 * Bullet 1).
 *
 * Smoke-tests:
 *   1. Helper renders a trivial React element without throwing.
 *   2. :func:`resetFetchCachedMock` clears the prior test's mock
 *      state (verified by stamping ``mockImplementation`` on
 *      ``fetchCached`` in test A, then checking the cleared
 *      ref returns to ``undefined`` in test B after the reset).
 *
 * NOT a replacement for the page-level test contract -- the
 * fight-events-page migration story is in plan 168 Bullets 2-4.
 * This file exists so a future maintainer can detect an early
 * regression in the helper without triggering the full migration
 * diff.
 */

import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";

import { fetchCached } from "@/lib/fetchCached";
import {
  renderWithSession,
  resetFetchCachedMock,
} from "../../app/_helpers/renderWithSession";

/**
 * :file:`web/tests/setup.ts` mocks ONLY React components
 * (FightsGrid, EventWindowsTable, etc). It does NOT mock
 * ``@/lib/fetchCached`` -- that module is the runtime HTTP substrate
 * and per-test mocks are owned by the test files that import it
 * directly (see the canonical ``vi.mock("@/lib/fetchCached", ...)``
 * block in :file:`web/tests/app/fight-events-page.test.tsx` lines
 * 47-52, which mirrors this exact pattern). So this per-file
 * ``vi.mock`` IS the canonical mock for ``fetchCached`` in this
 * file's helper imports. ``importActual`` passthrough preserves the
 * module's rest surface (``__resetCacheForTests``,
 * ``__cacheSizeForTests``) so a future added export is not lost.
 */
vi.mock("@/lib/fetchCached", async () => {
  const actual = await vi.importActual<typeof import("@/lib/fetchCached")>(
    "@/lib/fetchCached",
  );
  return { ...actual, fetchCached: vi.fn() };
});

describe("renderWithSession pilot", () => {
  it("renders a trivial element without throwing", () => {
    // ``createElement`` instead of JSX + ``<div>`` to avoid the JSX
    // transformer needing an ``import React from "react"`` line +
    // to keep this smoke test free of unrelated imports. The
    // helper's :func:`render` is RTL's standard ``render``; it
    // accepts a valid ReactElement (which createElement returns).
    const tree = createElement("div", { "data-testid": "smoke" }, "OK");
    expect(() => renderWithSession(tree)).not.toThrow();
  });

  it("resetFetchCachedMock clears the prior test's mock state", () => {
    // Stamp a mock impl so the assertion below has something to
    // detect. The shape is intentionally minimal (a single field)
    // to avoid coupling this smoke to the real ``fetchCached``
    // return type -- the assertion is about lifecycle, not
    // payload fidelity. ``mockResolvedValue`` (vs
    // ``mockImplementation``) is the canonical vi.fn() setup
    // for promise-returning mocks.
    vi.mocked(fetchCached).mockResolvedValue({ ok: true } as never);
    expect(vi.mocked(fetchCached).getMockImplementation()).toBeDefined();
    resetFetchCachedMock();
    expect(vi.mocked(fetchCached).getMockImplementation()).toBeUndefined();
  });
});
