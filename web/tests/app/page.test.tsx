import { render, screen } from "@testing-library/react";

import Home from "@/app/page";

describe("Home", () => {
  it("renders the hero heading + tagline", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { level: 1 }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Analysez vos combats WvW/i),
    ).toBeInTheDocument();
  });

  it("links to /fights and /players via next/link", () => {
    render(<Home />);
    // Use getAllByRole to find all nav links, then check specific hrefs
    const links = screen.getAllByRole("link");
    const fightsLink = links.find((l) => l.getAttribute("href") === "/fights");
    const playersLink = links.find((l) => l.getAttribute("href") === "/players");
    expect(fightsLink).toBeTruthy();
    expect(playersLink).toBeTruthy();
  });

  it("shows the drag-drop upload zone", () => {
    render(<Home />);
    expect(
      screen.getByText(/Glissez-déposez votre log/i),
    ).toBeInTheDocument();
  });
});
