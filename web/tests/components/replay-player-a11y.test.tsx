import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { ReplayPlayer } from "@/components/ReplayPlayer";
import type { FightTimeline } from "@/lib/api/fights";

expect.extend(toHaveNoViolations);

function makeTimeline(windowS: number = 5, nBuckets: number = 6): FightTimeline {
  const points = [];
  for (let i = 0; i < nBuckets; i++) {
    points.push({
      window_start_ms: i * windowS * 1000,
      window_end_ms: (i + 1) * windowS * 1000,
      total_damage: (i + 1) * 1000,
      total_healing: (i + 1) * 100,
      total_buff_removal: (i + 1) * 10,
    });
  }
  return {
    fight_id: "test-fight-123",
    window_s: windowS,
    duration_s: nBuckets * windowS,
    points,
  };
}

describe("ReplayPlayer accessibility", () => {
  it("has no critical axe violations on initial render", async () => {
    const { container } = render(
      <ReplayPlayer fightId="test-fight" timeline={makeTimeline()} />,
    );
    const results = await axe(container, {
      rules: {
        "color-contrast": { enabled: false },
      },
    });
    expect(results.violations.filter((v) => v.impact === "critical")).toHaveLength(0);
  });
});
