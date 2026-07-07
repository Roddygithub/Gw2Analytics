/**
 * v0.8.0 of web: vitest cases for the per-account
 * :class:`PlayerTimelineChart` SVG line chart.
 *
 * Coverage
 * ========
 * - zero points -> empty-state panel
 * - single point -> the chart renders the dot trio
 *   (damage + healing + strip) at the X midpoint, with a
 *   single x-axis label and the "0 / 100%" y-axis labels
 * - 3 points -> the chart draws 3 polyline ``d`` paths and
 *   3 dot trios (9 circles), plus the sampled x-axis labels
 *   (first + last are always drawn, middle is sampled in)
 *
 * Why DOM-level (not snapshot)
 * ===========================
 * The chart is a small SVG with stable structure; DOM
 * assertions (querySelector + count) are more robust than
 * a snapshot when a future refactor reorders an attribute
 * or adds a decorative group. A snapshot would break on
 * whitespace + attribute order changes the visual rendering
 * does not depend on.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  PlayerTimelineChart,
  buildTimelineLayout,
} from "@/components/PlayerTimelineChart";
import type { PlayerTimelinePoint } from "@/lib/api";

function makePoint(
  fight_id: string,
  started_at: string,
  total_damage: number,
  total_healing: number,
  total_buff_removal: number,
): PlayerTimelinePoint {
  return { fight_id, started_at, total_damage, total_healing, total_buff_removal };
}

const THREE_POINTS: PlayerTimelinePoint[] = [
  makePoint("f-1", "2025-01-01T12:00:00Z", 1_000, 200, 50),
  makePoint("f-2", "2025-01-08T12:00:00Z", 3_000, 100, 75),
  makePoint("f-3", "2025-01-15T12:00:00Z", 2_000, 300, 25),
];

describe("PlayerTimelineChart", () => {
  it("renders the empty-state panel when there are no points", () => {
    render(<PlayerTimelineChart points={[]} />);
    expect(screen.getByText("No timeline data available.")).toBeInTheDocument();
  });

  it("renders the empty-state panel when there is a single all-zero point", () => {
    // Single point with zeros -> the layout helper returns
    // a non-null layout (so the chart renders), but the
    // X-axis only has 1 label. The chart is intentionally NOT
    // empty-state in this case (a single zero point is data,
    // not "no data").
    const { container } = render(
      <PlayerTimelineChart
        points={[makePoint("f-1", "2025-01-01T12:00:00Z", 0, 0, 0)]}
      />,
    );
    expect(
      screen.queryByText("No timeline data available."),
    ).not.toBeInTheDocument();
    // 1 dot trio = 3 circles.
    expect(container.querySelectorAll("circle")).toHaveLength(3);
  });

  it("renders 3 dot trios and the legend swatches for 3 points", () => {
    const { container } = render(<PlayerTimelineChart points={THREE_POINTS} />);
    // 3 points x 3 series = 9 circles.
    expect(container.querySelectorAll("circle")).toHaveLength(9);
    // 3 polyline ``d`` paths (1 per series).
    expect(container.querySelectorAll("path")).toHaveLength(3);
    // Legend has 3 swatches.
    expect(screen.getByText("Damage")).toBeInTheDocument();
    expect(screen.getByText("Healing")).toBeInTheDocument();
    expect(screen.getByText("Buff removal")).toBeInTheDocument();
    // X-axis: first + last are always drawn; the middle label
    // is sampled in (labelStep is 1 for a small dataset, so
    // 3 of 3 indices land in xLabelIndices).
    expect(container.querySelectorAll("text")).toHaveLength(
      // 2 y-axis labels (0 + 100%) + 3 x-axis labels + 1 caption
      // ("Per-fight trend (normalized per series)") -- the
      // caption is in a <span>, not an SVG <text>, so only the
      // 5 SVG texts are counted here.
      5,
    );
  });
});

describe("buildTimelineLayout", () => {
  it("returns null for an empty point list", () => {
    expect(buildTimelineLayout([])).toBeNull();
  });

  it("returns a non-null layout for a single point", () => {
    const layout = buildTimelineLayout([
      makePoint("f-1", "2025-01-01T12:00:00Z", 100, 50, 25),
    ]);
    expect(layout).not.toBeNull();
    expect(layout?.maxDamage).toBe(100);
    expect(layout?.maxHealing).toBe(50);
    expect(layout?.maxStrip).toBe(25);
    // Single point -> X is the midpoint of the inner width.
    expect(layout?.xFor(0)).toBe(layout ? layout.innerW / 2 : 0);
  });

  it("clamps all-zero series to a max of 1 (defensive against /0)", () => {
    const layout = buildTimelineLayout([
      makePoint("f-1", "2025-01-01T12:00:00Z", 0, 0, 0),
      makePoint("f-2", "2025-01-02T12:00:00Z", 0, 0, 0),
    ]);
    expect(layout).not.toBeNull();
    // All zeros -> ``Math.max(1, ...values)`` returns 1 for each
    // series; yFor(v=0, max=1) returns innerH (the baseline).
    expect(layout?.maxDamage).toBe(1);
    expect(layout?.maxHealing).toBe(1);
    expect(layout?.maxStrip).toBe(1);
    expect(layout?.yFor(0, 1)).toBe(layout ? layout.innerH : 0);
  });

  it("uses the actual max for mixed-magnitude series", () => {
    const layout = buildTimelineLayout([
      makePoint("f-1", "2025-01-01T12:00:00Z", 5_000, 10, 1),
      makePoint("f-2", "2025-01-02T12:00:00Z", 1_000, 100, 10),
    ]);
    expect(layout).not.toBeNull();
    expect(layout?.maxDamage).toBe(5_000);
    expect(layout?.maxHealing).toBe(100);
    expect(layout?.maxStrip).toBe(10);
  });
});
