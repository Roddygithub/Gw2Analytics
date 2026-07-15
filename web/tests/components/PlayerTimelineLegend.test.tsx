import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { PlayerTimelineLegend } from "@/components/PlayerTimelineLegend";

describe("PlayerTimelineLegend", () => {
  it("renders a list with three legend items", () => {
    const { container } = render(<PlayerTimelineLegend />);
    const list = container.querySelector("[role='list']");
    expect(list).toBeInTheDocument();
    expect(list).toHaveAttribute("aria-label", "Timeline legend");
    const items = container.querySelectorAll("[role='listitem']");
    expect(items.length).toBe(3);
  });

  it("displays Damage, Healing, and Buff removal labels", () => {
    const { container } = render(<PlayerTimelineLegend />);
    const items = container.querySelectorAll("[role='listitem']");
    const labels = Array.from(items).map((item) => item.textContent);
    expect(labels).toContain("Damage");
    expect(labels).toContain("Healing");
    expect(labels).toContain("Buff removal");
  });

  it("renders three colour swatches with the expected fills", () => {
    const { container } = render(<PlayerTimelineLegend />);
    const swatches = container.querySelectorAll("span[aria-hidden='true']");
    expect(swatches.length).toBe(3);
    expect(swatches[0]).toHaveStyle({ background: "var(--accent)" });
    expect(swatches[1]).toHaveStyle({ background: "var(--foreground)" });
    expect(swatches[2]).toHaveStyle({ background: "#f59e0b" });
  });
});
