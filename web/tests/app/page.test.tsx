import { render, screen } from "@testing-library/react";

import Home from "@/app/page";

describe("Home", () => {
  it("renders the hero heading + tagline", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { level: 1, name: "GW2Analytics" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Independent combat analytics/i),
    ).toBeInTheDocument();
  });

  it("links to /fights and /account via next/link", () => {
    render(<Home />);
    const fightsLink = screen.getByRole("link", { name: /Browse fights/i });
    const accountLink = screen.getByRole("link", { name: /Resolve API key/i });
    expect(fightsLink.getAttribute("href")).toBe("/fights");
    expect(accountLink.getAttribute("href")).toBe("/account");
  });

  it("displays the (mocked) API base URL in the footer copy", () => {
    render(<Home />);
    // setup.ts shims displayedApiBaseUrl -> http://test/api
    expect(screen.getByText("http://test/api")).toBeInTheDocument();
  });
});
