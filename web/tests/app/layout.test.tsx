import { render, screen } from "@testing-library/react";

import RootLayout, { metadata } from "@/app/layout";

describe("RootLayout", () => {
  it("exposes the GW2Analytics title via Next.js Metadata", () => {
    expect(metadata.title).toBe("GW2Analytics");
    expect(metadata.description).toMatch(/WvW combat analytics/i);
  });

  it("wraps children in <html lang=en> with the Geist font classes", () => {
    const { container } = render(
      <RootLayout>
        <span data-testid="child">hello</span>
      </RootLayout>,
    );

    const html = container.ownerDocument.documentElement;
    expect(html.tagName).toBe("HTML");
    expect(html.getAttribute("lang")).toBe("en");
    // next/font/google shim in setup.ts returns --mock-sans + --mock-mono
    // which RootLayout interpolates into the html className.
    expect(html.className).toContain("--mock-sans");
    expect(html.className).toContain("--mock-mono");

    const child = screen.getByTestId("child");
    expect(child).toHaveTextContent("hello");
    expect(child.closest("body")).not.toBeNull();
  });
});
