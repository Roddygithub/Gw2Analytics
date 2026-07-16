import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import RootLayout, { metadata } from "@/app/layout";

/**
 * RootLayout renders an <html> element. jsdom wraps the rendered
 * tree in a <div>, which triggers a React hydration warning that
 * is not actionable in unit tests. We silence that specific
 * message around the render call so the test output stays clean
 * without affecting other tests.
 */
function withSuppressedHydrationWarning<T>(fn: () => T): T {
  const shouldSuppress = (...args: unknown[]) =>
    args.some((arg) => {
      if (typeof arg !== "string") return false;
      return (
        arg.includes("<html> cannot be a child of") ||
        arg.includes("<body> cannot be a child of") ||
        arg.includes("In HTML, <html>") ||
        arg.includes("In HTML, <body>") ||
        arg.includes("This will cause a hydration error")
      );
    });

  const originalError = console.error;
  const originalWarn = console.warn;

  const errorSpy = vi.spyOn(console, "error").mockImplementation((...args) => {
    if (!shouldSuppress(...args)) {
      originalError(...args);
    }
  });
  const warnSpy = vi.spyOn(console, "warn").mockImplementation((...args) => {
    if (!shouldSuppress(...args)) {
      originalWarn(...args);
    }
  });

  try {
    return fn();
  } finally {
    errorSpy.mockRestore();
    warnSpy.mockRestore();
  }
}

describe("RootLayout", () => {
  it("exposes the GW2Analytics title via Next.js Metadata", () => {
    expect(metadata.title).toBe("GW2Analytics");
    expect(metadata.description).toMatch(/WvW combat analytics/i);
  });

  it("wraps children in <html lang=fr> with the Geist font classes", () => {
    const { container } = withSuppressedHydrationWarning(() =>
      render(
        <RootLayout>
          <span data-testid="child">hello</span>
        </RootLayout>,
      ),
    );

    const html = container.ownerDocument.documentElement;
    expect(html.tagName).toBe("HTML");
    expect(html.getAttribute("lang")).toBe("fr");
    // next/font/google shim in setup.ts returns --mock-sans + --mock-mono
    // which RootLayout interpolates into the html className.
    expect(html.className).toContain("--mock-sans");
    expect(html.className).toContain("--mock-mono");

    const child = screen.getByTestId("child");
    expect(child).toHaveTextContent("hello");
    expect(child.closest("body")).not.toBeNull();
  });
});
