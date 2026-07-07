/**
 * v0.9.0 plan/002: vitest cases for the
 * ``<ProfessionFilter>`` Client Component.
 *
 * Location: ``web/tests/components/`` matches the
 * vitest include pattern (the tests directory, all
 * ``.test.tsx`` files) so the test is picked up
 * by ``pnpm test:unit`` without needing a vitest config
 * change. The test imports the component via the ``@/``
 * alias to mirror the production import path.
 *
 * Test strategy
 * =============
 * The two cases cover the rendering contract (10 options +
 * the current value pre-selected from the URL) and the
 * update contract (selecting a value updates the URL via
 * the ``useRouter`` hook).
 *
 * Why ``fireEvent`` not ``userEvent``
 * -----------------------------------
 * The component only reacts to ``onChange`` on a ``<select>``
 * -- no focus, no keyboard, no timing-dependent events.
 * ``fireEvent.change`` is the canonical RTL shortcut for
 * that one event handler and avoids the ``@testing-library/user-event``
 * install (the rest of the test suite doesn't need it).
 * The ``useSearchParams`` hook is not exercised directly
 * here -- the Parent reads ``searchParams.profession`` and
 * passes it as a prop, so the ``useSearchParams`` call
 * inside the component is a defensive copy of the URL
 * state for the update handler.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ProfessionFilter } from "@/components/ProfessionFilter";

// Mock the Next.js navigation hooks so the test can assert
// the URL update without rendering a real router.
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("ProfessionFilter (v0.9.0 plan/002)", () => {
  it("renders 10 options + pre-selects the current value", () => {
    render(<ProfessionFilter currentValue="MESMER" />);
    // The <select> is wired with ``data-testid="profession-filter"``.
    const select = screen.getByTestId("profession-filter");
    expect(select).toBeInTheDocument();
    // 1 "All professions" + 9 base professions = 10 options.
    const options = select.querySelectorAll("option");
    expect(options).toHaveLength(10);
    // The pre-selected value is the current URL filter
    // (``MESMER`` passed as a prop). The <option> for
    // ``"Mesmer"`` is selected; the <option> for "All
    // professions" is NOT.
    expect(select).toHaveValue("MESMER");
    // The "All professions" option is the first <option>.
    expect(options[0]).toHaveValue("");
    expect(options[0]).toHaveTextContent("All professions");
  });

  it("updates the URL on selection change via the router", () => {
    // The ``currentValue`` prop is undefined (no filter on
    // first load). The "All professions" option is
    // pre-selected.
    render(<ProfessionFilter />);
    const select = screen.getByTestId("profession-filter");
    // Select "Mesmer" from the dropdown.
    fireEvent.change(select, { target: { value: "MESMER" } });
    // The ``useRouter().push`` mock is called with the
    // updated URL (``/players?profession=MESMER``).
    expect(pushMock).toHaveBeenCalledWith("/players?profession=MESMER");
    pushMock.mockClear();
    // Select "Guardian" -- the URL is updated again (the
    // mock's searchParams are empty, so the URL doesn't
    // accumulate multiple ``profession=`` params).
    fireEvent.change(select, { target: { value: "GUARDIAN" } });
    expect(pushMock).toHaveBeenCalledWith("/players?profession=GUARDIAN");
    pushMock.mockClear();
    // Select "All professions" (the empty value) -- the
    // ``profession=`` param is removed from the URL.
    fireEvent.change(select, { target: { value: "" } });
    expect(pushMock).toHaveBeenCalledWith("/players");
  });
});
