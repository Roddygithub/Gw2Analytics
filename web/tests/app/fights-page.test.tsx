import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchFights: vi.fn(),
}));

import FightsPage from "@/app/fights/page";
import { fetchFights } from "@/lib/api";
import { UPSTREAM_ERROR_PREFIX } from "@/lib/copy/error-messages";

// CI smoke only: this test invokes the Server Component as a plain
// TypeScript async function, not inside Next.js's RSC runtime. It
// therefore does not exercise `headers()` / `cookies()` / streaming
// SSR. If FightsPage ever starts using those, this test must either:
//
//   (a) refactor FightsPage into a thin RSC that hands pre-fetched
//       rows to a Client Component (RTL-testable out of the box), or
//   (b) extract the `fetchFights -> render` chain into a pure
//       helper tested with `vi.mocked(fetchFights)`.
//
// Playwright is an E2E framework, not a unit-test harness - do not
// reach for it here.
describe("FightsPage", () => {
  it("renders the empty-state counter when fetchFights returns []", async () => {
    vi.mocked(fetchFights).mockResolvedValue([]);
    const tree = await FightsPage();
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: "Fights" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/0 fights parsed and persisted/),
    ).toBeInTheDocument();
  });

  it("renders the upstream-error card when fetchFights throws", async () => {
    vi.mocked(fetchFights).mockRejectedValue(
      new Error("502: upstream gateway"),
    );
    const tree = await FightsPage();
    render(tree);
    expect(
      screen.getByText(`${UPSTREAM_ERROR_PREFIX}502: upstream gateway`),
    ).toBeInTheDocument();
  });
});
