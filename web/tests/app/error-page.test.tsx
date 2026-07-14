import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import GlobalError from "@/app/error";
import { FIGHTS_GRID_LINK_ROOT } from "@/lib/copy/error-messages";

describe("app/error.tsx", () => {
  it("renders the 'Try again' button (data-testid global-error-retry)", () => {
    const error = new Error("synthetic boom") as Error & { digest?: string };
    render(<GlobalError error={error} reset={() => {}} />);

    expect(screen.getByTestId("global-error-retry")).toBeInTheDocument();
  });

  it("renders the headline explaining the failure class", () => {
    const error = new Error("synthetic boom") as Error & { digest?: string };
    render(<GlobalError error={error} reset={() => {}} />);

    // H1 should be the brand-recognizable error heading.
    expect(
      screen.getByRole("heading", { name: /something went wrong/i })
    ).toBeInTheDocument();
  });

  it("hints at the fallback datasets (fights grid + players list)", () => {
    const error = new Error("synthetic boom") as Error & { digest?: string };
    render(<GlobalError error={error} reset={() => {}} />);

    // The body copy should mention both fallback destinations so the
    // analyst never lands on a dead-end page.
    expect(screen.getByText(FIGHTS_GRID_LINK_ROOT)).toBeInTheDocument();
    expect(screen.getByText(/players list/i)).toBeInTheDocument();
  });
});
