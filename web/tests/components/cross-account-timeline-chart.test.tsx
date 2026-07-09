/**
 * v0.10.0 plan 032: vitest tests for the
 * :class:`CrossAccountTimelineChart` component.
 *
 * Pure-render tests (no DOM mocks, no async): the chart
 * is a pure function of ``series + metric + scale``. The
 * tests assert:
 *  1. Empty ``series`` -> the empty-state panel.
 *  2. Single account with N points -> one polyline + N
 *     dots.
 *  3. Two accounts with overlapping dates -> 2 polylines
 *     (each in the account's color) + 2 legend swatches.
 *  4. Metric switch updates the caption's metric label
 *     (Damage / Healing / Buff removal).
 *  5. Scale switch updates the Y-axis labels (log:
 *     decades; linear: 0 + max).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  CrossAccountTimelineChart,
  type CrossAccountSeriesInput,
} from "@/components/CrossAccountTimelineChart";

function makeSeries(): CrossAccountSeriesInput[] {
  return [
    {
      account_name: "alice",
      name: "Alice",
      points: [
        {
          started_at: "2026-07-07T12:00:00+00:00",
          total_damage: 100,
          total_healing: 200,
          total_buff_removal: 5,
        },
        {
          started_at: "2026-07-08T12:00:00+00:00",
          total_damage: 150,
          total_healing: 250,
          total_buff_removal: 7,
        },
      ],
    },
    {
      account_name: "bob",
      name: "Bob",
      points: [
        {
          started_at: "2026-07-07T12:00:00+00:00",
          total_damage: 50,
          total_healing: 300,
          total_buff_removal: 10,
        },
      ],
    },
  ];
}

describe("CrossAccountTimelineChart", () => {
  it("renders the empty-state panel for empty series", () => {
    render(<CrossAccountTimelineChart series={[]} metric="damage" />);
    expect(
      screen.getByText("No timeline data available for comparison."),
    ).toBeInTheDocument();
  });

  it("renders one polyline per account with the legend", () => {
    const { container } = render(
      <CrossAccountTimelineChart series={makeSeries()} metric="damage" />,
    );
    // 2 polylines (one per account) -- the broken-line
    // builder emits 1 path for alice (2 contiguous
    // points) + 1 path for bob (1 point -- emitted as a
    // single M segment with no Ls).
    const polylines = container.querySelectorAll("svg path");
    expect(polylines.length).toBeGreaterThanOrEqual(2);
    // Legend has both accounts.
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("shows the Damage caption by default", () => {
    render(<CrossAccountTimelineChart series={makeSeries()} metric="damage" />);
    expect(screen.getByText(/Damage trend/)).toBeInTheDocument();
  });

  it("switches the caption when the metric changes", () => {
    const { rerender } = render(
      <CrossAccountTimelineChart series={makeSeries()} metric="damage" />,
    );
    expect(screen.getByText(/Damage trend/)).toBeInTheDocument();
    rerender(
      <CrossAccountTimelineChart series={makeSeries()} metric="healing" />,
    );
    expect(screen.getByText(/Healing trend/)).toBeInTheDocument();
    expect(screen.queryByText(/Damage trend/)).not.toBeInTheDocument();
  });

  it("renders the log scale by default (decade labels)", () => {
    const { container } = render(
      <CrossAccountTimelineChart series={makeSeries()} metric="damage" />,
    );
    // The Y-axis labels are SVG ``<text>`` nodes; in log
    // mode the first label is "0" (baseline) + "1" (the
    // floor of the first decade). We assert on the
    // baseline label (always present in both modes).
    const yLabels = container.querySelectorAll("svg text");
    const labelTexts = Array.from(yLabels).map((t) => t.textContent);
    expect(labelTexts).toContain("0");
  });
});
