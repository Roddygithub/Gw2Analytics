import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import NotFound from "@/app/not-found";

describe("app/not-found.tsx", () => {
  it("renders the '404' heading and the domain-aware subtitle", () => {
    render(<NotFound />);

    expect(screen.getByRole("heading", { name: /^404$/ })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /this page is not in the dataset/i })
    ).toBeInTheDocument();
  });

  it("renders the browse-fallback links (/fights, /players, /upload)", () => {
    render(<NotFound />);

    // The 3 links are the analyst's exit routes from a 404 page —
    // any future change must keep these present.
    expect(
      screen.getByRole("link", { name: /browse fights/i })
    ).toHaveAttribute("href", "/fights");
    expect(
      screen.getByRole("link", { name: /browse players/i })
    ).toHaveAttribute("href", "/players");
    expect(
      screen.getByRole("link", { name: /upload a replay/i })
    ).toHaveAttribute("href", "/upload");
  });

  it("marks the panel with a stable data-testid for downstream e2e", () => {
    render(<NotFound />);
    expect(screen.getByTestId("not-found-panel")).toBeInTheDocument();
  });
});
