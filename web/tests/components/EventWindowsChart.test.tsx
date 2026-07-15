import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.unmock("@/components/EventWindowsChart");

import { EventWindowsChart } from "@/components/EventWindowsChart";

describe("EventWindowsChart", () => {
  it("renders an empty-state message when buckets is empty", () => {
    render(<EventWindowsChart buckets={[]} />);
    expect(screen.getByText("No event windows.")).toBeInTheDocument();
  });

  it("renders an SVG chart when buckets are provided", () => {
    const buckets = [
      {
        start_ms: 0,
        end_ms: 5000,
        damage_total: 1000,
        healing_total: 500,
        event_count: 10,
      },
      {
        start_ms: 5000,
        end_ms: 10000,
        damage_total: 2000,
        healing_total: 300,
        event_count: 5,
      },
    ];
    render(<EventWindowsChart buckets={buckets} />);
    const svg = screen.getByRole("img", {
      name: "Per-bucket event damage and healing",
    });
    expect(svg).toBeInTheDocument();
    expect(svg.querySelectorAll("rect").length).toBeGreaterThanOrEqual(2);
  });

  it("renders the damage and healing legend labels", () => {
    const buckets = [
      {
        start_ms: 0,
        end_ms: 5000,
        damage_total: 1000,
        healing_total: 500,
        event_count: 10,
      },
    ];
    const { container } = render(<EventWindowsChart buckets={buckets} />);
    expect(container).toHaveTextContent("Damage");
    expect(container).toHaveTextContent("Healing");
  });
});
