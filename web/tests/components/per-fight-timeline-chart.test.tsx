/**
 * v0.8.9 of web (plan/002): vitest cases for the per-fight
 * :class:`PerFightTimelineChart` SVG line chart.
 *
 * Strict parallel of the v0.8.0
 * :file:`web/tests/components/player-timeline-chart.test.tsx`
 * (per-account historical timeline). The differences are:
 *
 * - The point shape is :class:`PerFightTimelinePoint` (no
 *   ``fight_id`` / ``started_at``; instead ``window_start_ms`` /
 *   ``window_end_ms`` since all points share the same fight).
 * - The chart is keyed on the BUCKET INDEX, not ``fight_id``
 *   (all points share the same fight).
 * - The X-axis labels are RELATIVE TIME in ``M:SS``, not
 *   absolute wall-clock ``MM/DD HH:MM``.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  PerFightTimelineChart,
  buildPerFightTimelineLayout,
  formatPerFightLogTick,
} from "@/components/PerFightTimelineChart";
import type { PerFightTimelinePoint } from "@/lib/api";

function makePoint(
  window_start_ms: number,
  window_end_ms: number,
  total_damage: number,
  total_healing: number,
  total_buff_removal: number,
): PerFightTimelinePoint {
  return {
    window_start_ms,
    window_end_ms,
    total_damage,
    total_healing,
    total_buff_removal,
  };
}

// 3 buckets, 5s each -> total 15s of fight. Mixed magnitudes
// (damage >> healing >> strip) so the 3 series exercise the
// per-series-max normalisation.
const THREE_BUCKETS: PerFightTimelinePoint[] = [
  makePoint(0, 5_000, 1_000, 200, 50),
  makePoint(5_000, 10_000, 3_000, 100, 75),
  makePoint(10_000, 15_000, 2_000, 300, 25),
];

describe("PerFightTimelineChart", () => {
  it("renders the empty-state panel when there are no points", () => {
    render(<PerFightTimelineChart points={[]} />);
    expect(
      screen.getByText("No per-fight timeline data available."),
    ).toBeInTheDocument();
  });

  it("renders 3 dot trios + 3 polylines + the legend for 3 buckets", () => {
    const { container } = render(
      <PerFightTimelineChart points={THREE_BUCKETS} />,
    );
    // 3 buckets x 3 series = 9 circles.
    expect(container.querySelectorAll("circle")).toHaveLength(9);
    // 3 polyline ``d`` paths (1 per series).
    expect(container.querySelectorAll("path")).toHaveLength(3);
    // Legend (re-uses PlayerTimelineLegend -- 3 swatches).
    expect(screen.getByText("Damage")).toBeInTheDocument();
    expect(screen.getByText("Healing")).toBeInTheDocument();
    expect(screen.getByText("Buff removal")).toBeInTheDocument();
    // 2 y-axis labels (0 + 100%) + 3 x-axis labels (first +
    // middle + last) = 5 SVG texts. The caption is in a <span>
    // (not an SVG <text>).
    expect(container.querySelectorAll("text")).toHaveLength(5);
  });

  it("renders the M:SS X-axis label format", () => {
    // The 3 buckets span 0-5s, 5-10s, 10-15s. The X-axis
    // labels are the BUCKET START times: "0:00" (bucket 0
    // start), "0:05" (bucket 1 start), "0:10" (bucket 2
    // start). The chart renders the start of each bucket,
    // NOT the end -- so the last label is "0:10" (bucket 2
    // starts at 10000ms), not "0:15" (which would be the
    // bucket 2 end). The middle label is sampled in
    // (labelStep=1 for a 3-point dataset) so all 3 labels
    // render.
    //
    // Why ``container.querySelectorAll("text")`` (NOT
    // ``screen.getByText``): the chart's ``<title>`` tooltips
    // contain the M:SS labels as substrings of longer
    // "0:00–0:05 · bucket 1/3\n..." strings, which makes
    // ``getByText`` unreliable for SVG charts. Querying the
    // ``<text>`` elements directly is more robust -- the
    // ``<title>`` elements are NOT ``<text>`` elements so
    // they don't appear in this query.
    const { container } = render(
      <PerFightTimelineChart points={THREE_BUCKETS} />,
    );
    const textContents = Array.from(
      container.querySelectorAll("text"),
    ).map((t) => t.textContent ?? "");
    expect(textContents).toContain("0:00");
    expect(textContents).toContain("0:05");
    expect(textContents).toContain("0:10");
    // Sanity: no wall-clock-style "01/01" labels anywhere in
    // the rendered tree (including the <title> tooltips).
    expect(container.textContent).not.toMatch(/\d{2}\/\d{2}/);
  });
});

describe("buildPerFightTimelineLayout", () => {
  it("returns null for an empty point list", () => {
    expect(buildPerFightTimelineLayout([])).toBeNull();
  });

  it("uses the actual max for mixed-magnitude series", () => {
    const layout = buildPerFightTimelineLayout([
      makePoint(0, 5_000, 5_000, 10, 1),
      makePoint(5_000, 10_000, 1_000, 100, 10),
    ]);
    expect(layout).not.toBeNull();
    expect(layout?.maxDamage).toBe(5_000);
    expect(layout?.maxHealing).toBe(100);
    expect(layout?.maxStrip).toBe(10);
  });

  it("clamps all-zero series to a max of 1 (defensive against /0)", () => {
    const layout = buildPerFightTimelineLayout([
      makePoint(0, 5_000, 0, 0, 0),
      makePoint(5_000, 10_000, 0, 0, 0),
    ]);
    expect(layout).not.toBeNull();
    expect(layout?.maxDamage).toBe(1);
    expect(layout?.maxHealing).toBe(1);
    expect(layout?.maxStrip).toBe(1);
  });

  it("supports the log scale (v0.8.2 lineage)", () => {
    // globalMax=1M (damage) dwarfs strip=50. In log mode the
    // globalMax sits at the TOP of the chart (y=0) and the
    // strip at 50 is still visible (well above the baseline).
    const layout = buildPerFightTimelineLayout(
      [
        makePoint(0, 5_000, 1_000_000, 100, 50),
        makePoint(5_000, 10_000, 500_000, 200, 30),
      ],
      "log",
    );
    expect(layout).not.toBeNull();
    expect(layout?.scale).toBe("log");
    expect(layout?.globalMax).toBe(1_000_000);
    expect(layout?.yFor(1_000_000)).toBe(0);
    expect(layout?.yFor(0)).toBe(layout ? layout.innerH : 0);
  });
});

describe("formatPerFightLogTick", () => {
  it("returns the formatted string for each decade", () => {
    expect(formatPerFightLogTick(0)).toBe("0");
    expect(formatPerFightLogTick(1)).toBe("1");
    expect(formatPerFightLogTick(50)).toBe("50");
    expect(formatPerFightLogTick(1_000)).toBe("1k");
    expect(formatPerFightLogTick(1_500)).toBe("1.5k");
    expect(formatPerFightLogTick(1_000_000)).toBe("1M");
    expect(formatPerFightLogTick(1_500_000)).toBe("1.5M");
    expect(formatPerFightLogTick(1_000_000_000)).toBe("1B");
    expect(formatPerFightLogTick(1_500_000_000)).toBe("1.5B");
  });
});
