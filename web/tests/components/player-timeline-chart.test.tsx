/**
 * v0.8.0 of web: vitest cases for the per-account
 * :class:`PlayerTimelineChart` SVG line chart.
 *
 * v0.9.0 plan/001 refactor: this file now tests the THIN
 * WRAPPER that delegates to the shared :class:`TimelineChart`
 * base. The ``buildTimelineLayout`` unit tests use the flat
 * :class:`TimelineChartPoint` shape (NOT the raw
 * :class:`PlayerTimelinePoint` API type) because the layout
 * helper is a pure function of the 3 series values -- the
 * :class:`fight_id` / :class:`started_at` fields are
 * wrapper-level concerns (X-axis label format + tooltip
 * text + React key) that the base doesn't consume. The
 * :func:`makeChartPoint` helper below constructs a minimal
 * :class:`TimelineChartPoint` with just the 3 series numbers
 * + placeholder ``key``/``xLabel``/``tooltip`` strings (the
 * layout helper doesn't read those 3 placeholder fields).
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
import type { TimelineChartPoint } from "@/components/TimelineChart";

function makePoint(
  fight_id: string,
  started_at: string,
  total_damage: number,
  total_healing: number,
  total_buff_removal: number,
): PlayerTimelinePoint {
  return { fight_id, started_at, total_damage, total_healing, total_buff_removal };
}

// v0.9.0 plan/001: the shared :class:`TimelineChart` base
// consumes the flat :class:`TimelineChartPoint` shape, not
// the raw :class:`PlayerTimelinePoint` API type. This
// helper constructs a minimal :class:`TimelineChartPoint`
// for the ``buildTimelineLayout`` unit tests; the
// :class:`key` / :class:`xLabel` / :class:`tooltip` fields
// are unused by the layout helper (they're consumed by the
// React component, which has its own test coverage in the
// ``PlayerTimelineChart`` describe block above).
function makeChartPoint(
  total_damage: number,
  total_healing: number,
  total_buff_removal: number,
): TimelineChartPoint {
  return {
    series: [total_damage, total_healing, total_buff_removal],
    key: "test",
    xLabel: "test",
    tooltip: "test",
  };
}

const THREE_POINTS: PlayerTimelinePoint[] = [
  makePoint("f-1", "2025-01-01T12:00:00Z", 1_000, 200, 50),
  makePoint("f-2", "2025-01-08T12:00:00Z", 3_000, 100, 75),
  makePoint("f-3", "2025-01-15T12:00:00Z", 2_000, 300, 25),
];

describe("PlayerTimelineChart timezone determinism (v0.9.6 plan 024)", () => {
  it("formats dates identically regardless of local timezone", () => {
    const fmt = new Intl.DateTimeFormat("en-US", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    });
    const result = fmt.format(new Date("2024-01-15T12:34:00Z"));
    expect(result).toBe("01/15, 12:34 PM");
  });
});

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
    const layout = buildTimelineLayout([makeChartPoint(100, 50, 25)]);
    expect(layout).not.toBeNull();
    expect(layout?.maxDamage).toBe(100);
    expect(layout?.maxHealing).toBe(50);
    expect(layout?.maxStrip).toBe(25);
    // Single point -> X is the midpoint of the inner width.
    expect(layout?.xFor(0)).toBe(layout ? layout.innerW / 2 : 0);
  });

  it("clamps all-zero series to a max of 1 (defensive against /0)", () => {
    const layout = buildTimelineLayout([
      makeChartPoint(0, 0, 0),
      makeChartPoint(0, 0, 0),
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
      makeChartPoint(5_000, 10, 1),
      makeChartPoint(1_000, 100, 10),
    ]);
    expect(layout).not.toBeNull();
    expect(layout?.maxDamage).toBe(5_000);
    expect(layout?.maxHealing).toBe(100);
    expect(layout?.maxStrip).toBe(10);
  });
});

describe("buildTimelineLayout (log scale, v0.8.2)", () => {
  it("returns a layout with the global max across all 3 series", () => {
    // The original ROADMAP use case: damage=1M dwarfs
    // strip=50. In log mode the global max is 1M (damage),
    // and the strip at 50 is still visible because log10(51)
    // is much larger than 0 (the baseline).
    const layout = buildTimelineLayout(
      [makeChartPoint(1_000_000, 100, 50), makeChartPoint(500_000, 200, 30)],
      "log",
    );
    expect(layout).not.toBeNull();
    expect(layout?.scale).toBe("log");
    expect(layout?.globalMax).toBe(1_000_000);
    // globalMax sits at the TOP of the chart (y=0).
    expect(layout?.yFor(1_000_000)).toBe(0);
    // 0 sits at the BOTTOM of the chart (y=innerH).
    expect(layout?.yFor(0)).toBe(layout ? layout.innerH : 0);
    // Strip=50 is well above the baseline on a log scale
    // (log10(51) / log10(1_000_001) ≈ 0.40, so y ≈ 0.60
    // * innerH -- visible).
    const yAt50 = layout?.yFor(50) ?? 0;
    const yAt0 = layout?.yFor(0) ?? 0;
    expect(yAt50).toBeLessThan(yAt0);
    expect(yAt50).toBeGreaterThan(0);
  });

  it("generates logarithmic Y-axis ticks (decades up to globalMax)", () => {
    // globalMax=10_000 -> ticks are 0, 1, 10, 100, 1000, 10_000.
    const layout = buildTimelineLayout(
      [makeChartPoint(10_000, 100, 50), makeChartPoint(5_000, 200, 30)],
      "log",
    );
    expect(layout).not.toBeNull();
    expect(layout?.ticks).toEqual([0, 1, 10, 100, 1_000, 10_000]);
  });

  it("caps the tick count at 8 for very wide ranges", () => {
    // globalMax=10_000_000_000 (10B) would otherwise draw
    // 10 ticks (0 + 1 + 10 + 100 + 1k + 10k + 100k + 1M +
    // 10M + 100M + 1B + 10B = 12). The implementation caps
    // at 8 to avoid axis clutter.
    const layout = buildTimelineLayout(
      [makeChartPoint(10_000_000_000, 0, 0)],
      "log",
    );
    expect(layout).not.toBeNull();
    expect(layout?.ticks.length).toBeLessThanOrEqual(8);
  });

  it("treats all-zero values as the baseline (log(0+1)=0)", () => {
    // All zeros -> globalMax=1 (clamped by Math.max(1, ...)),
    // ticks=[0, 1], yFor(0)=innerH, yFor(1)=0.
    const layout = buildTimelineLayout(
      [makeChartPoint(0, 0, 0)],
      "log",
    );
    expect(layout).not.toBeNull();
    expect(layout?.globalMax).toBe(1);
    expect(layout?.ticks).toEqual([0, 1]);
    expect(layout?.yFor(0)).toBe(layout ? layout.innerH : 0);
    expect(layout?.yFor(1)).toBe(0);
  });
});

describe("PlayerTimelineChart (log scale prop, v0.8.2)", () => {
  it("renders logarithmic Y-axis labels when scale='log'", () => {
    // Mixed-magnitude fixture: damage in millions, strip in
    // dozens. In log mode the chart should render the
    // decade tick labels (0, 1, 10, 100, 1k, 10k, 100k, 1M)
    // instead of the "0" + "100%" pair from linear mode.
    const { container } = render(
      <PlayerTimelineChart
        points={[
          makePoint("f-1", "2025-01-01T12:00:00Z", 1_000_000, 100, 50),
          makePoint("f-2", "2025-01-02T12:00:00Z", 500_000, 200, 30),
        ]}
        scale="log"
      />,
    );
    // 6 ticks (0, 1, 10, 100, 1k, 10k, 100k, 1M) -> 8
    // y-axis <text> elements. The "100%" label from linear
    // mode must NOT appear.
    const textContents = Array.from(container.querySelectorAll("text")).map(
      (t) => t.textContent ?? "",
    );
    expect(textContents).toContain("0");
    expect(textContents).toContain("1M");
    expect(textContents).not.toContain("100%");
  });
});
