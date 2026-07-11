/**
 * Phase 7 v2 of web: component-level vitest test for the
 * ``WindowSizeSelector`` Client Component.
 *
 * The page-level test (in :file:`web/tests/app/fight-events-page.test.tsx`)
 * mocks the selector to a no-op because the page-test focuses on
 * the page's own render contract + the URL -> fetchFightEvents
 * wiring. This dedicated test exercises the SELECTED dropdown
 * option + the ``onChange`` -> ``router.push`` interaction, which
 * is the selector's primary behaviour.
 *
 * What is exercised
 * =================
 * - **Renders all preset values**: the ``<select>`` exposes
 *   5 ``<option>`` children (1, 5, 30, 60, 300).
 * - **Marks the current value as selected**: the option matching
 *   the ``current`` prop carries the ``selected`` HTML attribute.
 * - **Emits a bare URL on the default (5)**: the analyst can pick
 *   5 (the gateway default) and the URL stays clean (no
 *   ``?window_s=5`` suffix).
 * - **Emits a query param on a non-default selection**: picking
 *   30 yields ``/fights/<id>?window_s=30``.
 *
 * What is NOT exercised
 * =====================
 * - The actual browser router behaviour (we mock ``useRouter``
 *   + ``usePathname``; the real router is part of the Next.js
 *   runtime, not the unit test).
 * - The visual styling (assertions are on semantics, not CSS).
 */

import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { vi } from "vitest";

// Override the global no-op mock from :file:`web/tests/setup.ts` so
// this test exercises the real selector. ``importOriginal`` is the
// canonical vitest pattern for "use the real module instead of the
// global stub"; if we left the global mock in place, every render
// would return ``() => null`` and the ``data-testid="window-s-selector"``
// query would fail.
vi.mock("@/components/WindowSizeSelector", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/WindowSizeSelector")>();
  return actual;
});

// Mock the next/navigation hooks the selector depends on.
const pushMock = vi.fn();

const searchParamsMock = vi.fn(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => "/fights/abc123def456",
  useSearchParams: searchParamsMock,
}));

import { WindowSizeSelector } from "@/components/WindowSizeSelector";

const FIGHT_ID = "abc123def456";

describe("WindowSizeSelector", () => {
  beforeEach(() => {
    pushMock.mockClear();
  });

  it("renders the dropdown with all preset values and marks the current as selected", () => {
    render(<WindowSizeSelector current={30} fightId={FIGHT_ID} />);
    const select = screen.getByTestId("window-s-selector") as HTMLSelectElement;
    // The <select> has 5 <option> children.
    expect(select.options).toHaveLength(5);
    // The currently-selected option is 30.
    expect(select.value).toBe("30");
    // The option labels match the preset list.
    const labels = Array.from(select.options).map((o) => o.value);
    expect(labels).toEqual(["1", "5", "30", "60", "300"]);
  });

  it("emits a bare URL (no query param) when the user picks the default (5)", () => {
    render(<WindowSizeSelector current={1} fightId={FIGHT_ID} />);
    const select = screen.getByTestId("window-s-selector");
    fireEvent.change(select, { target: { value: "5" } });
    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith("/fights/abc123def456");
  });

  it("emits a query-param URL when the user picks a non-default value", () => {
    render(<WindowSizeSelector current={5} fightId={FIGHT_ID} />);
    const select = screen.getByTestId("window-s-selector");
    fireEvent.change(select, { target: { value: "30" } });
    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith("/fights/abc123def456?window_s=30");
  });

  it("preserves other active query params when changing window_s", () => {
    searchParamsMock.mockReturnValue(
      new URLSearchParams("target=123&window_s=5"),
    );
    render(<WindowSizeSelector current={5} fightId={FIGHT_ID} />);
    const select = screen.getByTestId("window-s-selector");
    fireEvent.change(select, { target: { value: "30" } });
    expect(pushMock).toHaveBeenCalledWith(
      expect.stringContaining("target=123"),
    );
    expect(pushMock).toHaveBeenCalledWith(
      expect.stringContaining("window_s=30"),
    );
  });
});
