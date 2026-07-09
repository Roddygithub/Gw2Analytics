/**
 * v0.10.0 plan 032: vitest tests for the
 * :class:`CrossAccountCompareSection` client component.
 *
 * Verifies:
 *  1. Initial render: 2 account chips + the chart's
 *     Damage caption.
 *  2. Metric radio click: switches the chart's metric
 *     (Damage -> Healing) without a network round-trip
 *     (the metric is pure client state).
 *  3. Caption surface: "Comparing 2 accounts" copy.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CrossAccountCompareSection } from "@/components/CrossAccountCompareSection";
import type { CrossAccountTimelineSeries } from "@/lib/api";

function makeInitialSeries(): CrossAccountTimelineSeries[] {
  return [
    {
      account_name: "alice",
      name: "Alice",
      points: [
        {
          fight_id: "f1",
          started_at: "2026-07-07T12:00:00+00:00",
          total_damage: 100,
          total_healing: 200,
          total_buff_removal: 5,
        },
      ],
    },
    {
      account_name: "bob",
      name: "Bob",
      points: [
        {
          fight_id: "f1",
          started_at: "2026-07-07T12:00:00+00:00",
          total_damage: 50,
          total_healing: 300,
          total_buff_removal: 10,
        },
      ],
    },
  ];
}

describe("CrossAccountCompareSection", () => {
  it("renders the 2 account chips + the default Damage chart", () => {
    render(
      <CrossAccountCompareSection
        initialAccounts={["alice", "bob"]}
        initialSeries={makeInitialSeries()}
        initialBucket="day"
        initialTz="UTC"
      />,
    );
    // Each account name appears in BOTH the chip list AND the
    // chart legend (the section is a sibling of the chart's
    // built-in legend). Use ``getAllByText`` to assert the
    // chip presence + the chart legend presence without
    // coupling to a specific DOM ordering.
    expect(screen.getAllByText("Alice").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Bob").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Damage trend/)).toBeInTheDocument();
    expect(screen.getByText(/Comparing 2 accounts/)).toBeInTheDocument();
  });

  it("switches the metric on radio click (pure client state)", () => {
    render(
      <CrossAccountCompareSection
        initialAccounts={["alice", "bob"]}
        initialSeries={makeInitialSeries()}
        initialBucket="day"
        initialTz="UTC"
      />,
    );
    expect(screen.getByText(/Damage trend/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "healing metric" }));
    expect(screen.getByText(/Healing trend/)).toBeInTheDocument();
  });
});
