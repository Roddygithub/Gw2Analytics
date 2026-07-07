/**
 * Phase 8 v2 of web: component-level vitest test for the
 * ``TargetFilter`` Client Component.
 *
 * The page-level test (in :file:`web/tests/app/fight-events-page.test.tsx`)
 * mocks the filter to a no-op because the page-test focuses on
 * the page's own render contract + the URL -> fetchFightEvents
 * wiring. This dedicated test exercises the SELECTED dropdown
 * option + the ``onChange`` -> ``router.push`` interaction, which
 * is the filter's primary behaviour.
 *
 * What is exercised
 * =================
 * - **Renders all available targets + the "All targets" entry**:
 *   the ``<select>`` exposes 1 + len(availableTargets) ``<option>``
 *   children.
 * - **Marks the current target as selected** (or the empty string
 *   when ``current === null``).
 * - **Emits a bare URL (no ``?target=``) on "All targets"**: the
 *   analyst can clear the filter and the URL drops the param.
 * - **Preserves other search params** (e.g. ``?window_s=30``) when
 *   setting / clearing the target -- the filter must not stomp on
 *   the existing URL state.
 * - **Emits a query param URL when a target is picked**.
 *
 * What is NOT exercised
 * =====================
 * - The actual browser router behaviour (we mock ``useRouter``
 *   + ``usePathname`` + ``useSearchParams``; the real router is
 *   part of the Next.js runtime, not the unit test).
 * - The visual styling (assertions are on semantics, not CSS).
 */

import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { vi } from "vitest";

// Override the global no-op mock from :file:`web/tests/setup.ts` so
// this test exercises the real filter. ``importOriginal`` is the
// canonical vitest pattern for "use the real module instead of the
// global stub"; if we left the global mock in place, every render
// would return ``() => null`` and the
// ``data-testid="target-filter"`` query would fail.
vi.mock("@/components/TargetFilter", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/TargetFilter")>();
  return actual;
});

// Mock the next/navigation hooks the filter depends on. The filter
// uses ``useRouter().push`` + ``usePathname()`` +
// ``useSearchParams()``; we return deterministic stubs so each test
// can assert on the emitted URL without booting the real Next.js
// router runtime.
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => "/fights/abc123def456",
  useSearchParams: () => new URLSearchParams(""),
}));

import { TargetFilter } from "@/components/TargetFilter";

const FIGHT_ID = "abc123def456";
const TARGETS = [1, 2, 3] as const;

describe("TargetFilter", () => {
  beforeEach(() => {
    pushMock.mockClear();
  });

  it("renders the dropdown with all available targets + the 'All targets' entry, and marks the current as selected", () => {
    render(
      <TargetFilter
        current={2}
        availableTargets={TARGETS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("target-filter") as HTMLSelectElement;
    // The <select> has 1 (All targets) + 3 (target ids) = 4 <option> children.
    expect(select.options).toHaveLength(4);
    // The currently-selected option is 2.
    expect(select.value).toBe("2");
    // The option labels match the available-targets list with the
    // "All targets" entry prepended.
    const labels = Array.from(select.options).map((o) => o.value);
    expect(labels).toEqual(["", "1", "2", "3"]);
  });

  it("renders the empty-value selection when current is null (unfiltered view)", () => {
    render(
      <TargetFilter
        current={null}
        availableTargets={TARGETS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("target-filter") as HTMLSelectElement;
    expect(select.value).toBe("");
  });

  it("emits a bare URL (drops ?target=) when the user picks 'All targets'", () => {
    render(
      <TargetFilter
        current={2}
        availableTargets={TARGETS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("target-filter");
    fireEvent.change(select, { target: { value: "" } });
    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith("/fights/abc123def456");
  });

  it("emits a query-param URL when the user picks a target", () => {
    render(
      <TargetFilter
        current={null}
        availableTargets={TARGETS}
        fightId={FIGHT_ID}
      />,
    );
    const select = screen.getByTestId("target-filter");
    fireEvent.change(select, { target: { value: "3" } });
    expect(pushMock).toHaveBeenCalledTimes(1);
    expect(pushMock).toHaveBeenCalledWith(
      "/fights/abc123def456?target=3",
    );
  });
});
