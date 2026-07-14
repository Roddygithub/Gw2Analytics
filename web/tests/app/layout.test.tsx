import { render, screen } from "@testing-library/react";

import RootLayout, { metadata } from "@/app/layout";

/**
 * RootLayout renders an <html> element. jsdom wraps the rendered
 * tree in a <div>, which triggers a React hydration warning that
 * is not actionable in unit tests. We silence that specific
 * message around the render call so the test output stays clean
 * without affecting other tests.
 */
function withSuppressedHydrationWarning<T>(fn: () => T): T {
  const originalConsoleError = console.error;
  console.error = (...args: unknown[]) => {
    const message = typeof args[0] === "string" ? args[0] : "";
    if (
      message.includes("<html> cannot be a child of") ||
      message.includes("<body> cannot be a child of")
    ) {
      return;
    }
    originalConsoleError(...args);
  };
  try {
    return fn();
  } finally {
    console.error = originalConsoleError;
  }
}

describe("RootLayout", () => {
  it("exposes the GW2Analytics title via Next.js Metadata", () => {
    expect(metadata.title).toBe("GW2Analytics");
    expect(metadata.description).toMatch(/WvW combat analytics/i);
  });

  it("wraps children in <html lang=en> with the Geist font classes", () => {
    const { container } = withSuppressedHydrationWarning(() =>
      render(
        <RootLayout>
          <span data-testid="child">hello</span>
        </RootLayout>,
      ),
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
