/**
 * v0.10.0 plan 032: vitest tests for the ``/players/compare``
 * Server Component page.
 *
 * Verifies:
 *  1. 0 ``?accounts=`` in URL -> empty-state copy.
 *  2. 5 ``?accounts=`` in URL -> "too many accounts" error.
 *  3. The page renders the back-link + heading + the
 *     CrossAccountCompareSection when 2+ accounts are
 *     supplied (the section's own behavior is covered
 *     by ``cross-account-compare-section.test.tsx``).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Mock the API client so the page's server fetch does
// NOT hit the network in vitest (the page is a Server
// Component; the test runs the rendered React tree in
// the vitest JSDOM environment, where a real fetch would
// fail).
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchPlayerCompareTimeline: vi.fn(async () => []),
  };
});

import ComparePage from "@/app/players/compare/page";

describe("/players/compare page", () => {
  it("renders the empty-state copy with 0 accounts", async () => {
    const page = await ComparePage({
      searchParams: Promise.resolve({ accounts: undefined }),
    });
    render(page);
    expect(
      screen.getByRole("heading", { name: "Compare accounts" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Add at least 2 accounts/)).toBeInTheDocument();
  });

  it("renders the too-many-accounts error with 5 accounts", async () => {
    const page = await ComparePage({
      searchParams: Promise.resolve({
        accounts: ["a", "b", "c", "d", "e"],
      }),
    });
    render(page);
    expect(
      screen.getByRole("heading", { name: "Compare accounts" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Too many accounts/)).toBeInTheDocument();
  });

  it("renders the section when 2 accounts are supplied", async () => {
    const page = await ComparePage({
      searchParams: Promise.resolve({
        accounts: ["TestAccount.1234", "TestAccount.5678"],
      }),
    });
    render(page);
    expect(
      screen.getByRole("heading", { name: "Compare accounts" }),
    ).toBeInTheDocument();
    // The "Comparison timeline" h2 lives inside the section.
    expect(
      screen.getByRole("heading", { name: /Comparison timeline/ }),
    ).toBeInTheDocument();
  });
});
