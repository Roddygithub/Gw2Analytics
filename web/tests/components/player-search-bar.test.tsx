/**
 * v0.7.1 of web: component-level vitest cases for
 * :class:`PlayerSearchBar`. Overrides the global no-op mock
 * in :file:`web/tests/setup.ts` via
 * ``vi.mock(..., importOriginal)`` so the real Client Component
 * runs, then asserts on the form's submit + router.push
 * interaction.
 *
 * Why a dedicated component test (vs the page-level smoke)
 * ========================================================
 * The page-level tests in :file:`web/tests/app/page.test.tsx`
 * mock the search bar as a no-op (the layout's header is
 * outside the page's render tree). The component-level
 * behaviour -- form submit, empty-input no-op, whitespace
 * trim, URL encoding -- lives here so a future refactor of
 * the submit handler can lock the wire contract.
 */

import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

/**
 * Override the global no-op mock for
 * :class:`PlayerSearchBar` declared in
 * :file:`web/tests/setup.ts` so the real Client Component
 * runs. Without this override, the global ``vi.mock`` would
 * take precedence (the mock is registered before any test file
 * imports) and the component would render nothing, so
 * ``container.querySelector('input[type="search"]')`` would
 * return ``null`` and every test would fail with "search
 * input not found".
 *
 * The ``importOriginal`` pattern is the same one used in the
 * other component-level tests (window-size-selector, target-
 * filter) so the test setup stays consistent.
 */
vi.mock("@/components/PlayerSearchBar", async (importOriginal) => {
  return await importOriginal<
    typeof import("@/components/PlayerSearchBar")
  >();
});

import { PlayerSearchBar } from "@/components/PlayerSearchBar";

/**
 * Why ``container.querySelector`` instead of role-based queries
 * =============================================================
 * jsdom's resolution of ``<label htmlFor>`` + ``<input id>`` is
 * unreliable for ``type="search"`` inputs (the role mapping is
 * inconsistent across jsdom versions), and ``getByPlaceholderText``
 * hits a similar gotcha when the form wrapper carries
 * ``role="search"`` (the form intercepts the role resolution).
 * Querying the DOM directly via ``container.querySelector`` is
 * the most stable path: it finds the input by its type attribute
 * regardless of label / role / aria-attribute shenanigans.
 */
function getInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="search"]');
  if (!input) throw new Error("search input not found");
  return input as HTMLInputElement;
}

describe("PlayerSearchBar", () => {
  it("renders the search input + button", () => {
    const { container, getByText } = render(<PlayerSearchBar />);
    expect(getInput(container)).toBeInTheDocument();
    expect(getByText("Search")).toBeInTheDocument();
  });

  it("does nothing when the input is empty", () => {
    const { container } = render(<PlayerSearchBar />);
    const form = container.querySelector("form");
    if (!form) throw new Error("form not found");
    fireEvent.submit(form);
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("does nothing when the input is whitespace-only", () => {
    const { container } = render(<PlayerSearchBar />);
    const input = getInput(container);
    fireEvent.change(input, { target: { value: "   " } });
    const form = container.querySelector("form");
    if (!form) throw new Error("form not found");
    fireEvent.submit(form);
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("emits router.push with URL-encoded account name on submit", () => {
    const { container } = render(<PlayerSearchBar />);
    const input = getInput(container);
    fireEvent.change(input, { target: { value: ":account.1234" } });
    const form = container.querySelector("form");
    if (!form) throw new Error("form not found");
    fireEvent.submit(form);
    expect(pushMock).toHaveBeenCalledWith(
      "/players/%3Aaccount.1234",
    );
  });

  it("trims surrounding whitespace before encoding", () => {
    const { container } = render(<PlayerSearchBar />);
    const input = getInput(container);
    fireEvent.change(input, { target: { value: "  :synth.abc  " } });
    const form = container.querySelector("form");
    if (!form) throw new Error("form not found");
    fireEvent.submit(form);
    expect(pushMock).toHaveBeenCalledWith(
      "/players/%3Asynth.abc",
    );
  });
});
