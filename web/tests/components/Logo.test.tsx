import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Logo } from "@/components/Logo";

describe("Logo", () => {
  it("renders an inline SVG", () => {
    const { container } = render(<Logo />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("viewBox", "0 0 24 24");
  });

  it("respects the size prop", () => {
    const { container } = render(<Logo size={42} />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "42");
    expect(svg).toHaveAttribute("height", "42");
  });

  it("renders the layered diamond icon paths using the accent colour", () => {
    const { container } = render(<Logo />);
    const fillPath = container.querySelector("path[fill='var(--accent)']");
    const strokePath = container.querySelector("path[stroke='var(--accent)']");
    expect(fillPath).toBeInTheDocument();
    expect(strokePath).toBeInTheDocument();
  });
});
