import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { formatLarge, TopListCard } from "@/shared/stats";

describe("formatLarge", () => {
  it("formats billions as 1.0B, 2.5B", () => {
    expect(formatLarge(1_000_000_000)).toBe("1.0B");
    expect(formatLarge(2_500_000_000)).toBe("2.5B");
    expect(formatLarge(10_000_000_000)).toBe("10.0B");
  });

  it("formats millions as 1.0M, 2.5M", () => {
    expect(formatLarge(1_000_000)).toBe("1.0M");
    expect(formatLarge(2_500_000)).toBe("2.5M");
    expect(formatLarge(999_000_000)).toBe("999.0M");
  });

  it("formats thousands as 1.0K, 2.5K, 999.0K", () => {
    expect(formatLarge(1_000)).toBe("1.0K");
    expect(formatLarge(2_500)).toBe("2.5K");
    // 999_999 / 1000 = 999.999 → toFixed(1) = "1000.0"
    expect(formatLarge(999_000)).toBe("999.0K");
    expect(formatLarge(1_499)).toBe("1.5K");
  });

  it("returns raw rounded number for values < 1000", () => {
    expect(formatLarge(999)).toBe("999");
    expect(formatLarge(0)).toBe("0");
    expect(formatLarge(42)).toBe("42");
    expect(formatLarge(999.5)).toBe("1000");
  });

  it("handles edge cases", () => {
    expect(formatLarge(-1_000)).toBe("-1.0K");
    expect(formatLarge(1)).toBe("1");
  });
});

describe("TopListCard", () => {
  const mockPlayers = [
    { account_name: "alpha.1", name: "Alpha", profession: "PROF(1)", elite_spec: "ELITE(27)", fights_attended: 10, total_damage: 5000, total_healing: 3000, total_buff_removal: 100 },
    { account_name: "beta.2", name: "Beta", profession: "PROF(2)", elite_spec: "BASE", fights_attended: 8, total_damage: 8000, total_healing: 1000, total_buff_removal: 200 },
    { account_name: "gamma.3", name: "Gamma", profession: "PROF(3)", elite_spec: "ELITE(43)", fights_attended: 12, total_damage: 3000, total_healing: 5000, total_buff_removal: 50 },
  ];

  it("renders title and top 3 sorted by getValue descending", () => {
    const { container } = render(
      <TopListCard
        title="Top Damage"
        rows={mockPlayers}
        getValue={(r) => r.total_damage}
      />,
    );
    expect(container.textContent).toContain("Top Damage");
    // Sorted: Beta (8K), Alpha (5K), Gamma (3K)
    expect(container.textContent).toContain("Beta");
    expect(container.textContent).toContain("Alpha");
    expect(container.textContent).toContain("Gamma");
  });

  it("shows medal emojis for top 3", () => {
    const { container } = render(
      <TopListCard
        title="Top Heal"
        rows={mockPlayers}
        getValue={(r) => r.total_healing}
      />,
    );
    expect(container.textContent).toContain("🥇");
    expect(container.textContent).toContain("🥈");
    expect(container.textContent).toContain("🥉");
  });

  it("shows 'No data' when rows array is empty", () => {
    const { container } = render(
      <TopListCard
        title="Empty"
        rows={[]}
        getValue={(r) => r.total_damage}
      />,
    );
    expect(container.textContent).toContain("No data");
    expect(container.textContent).not.toContain("🥇");
  });

  it("formats values with formatLarge", () => {
    const { container } = render(
      <TopListCard
        title="Top Strip"
        rows={mockPlayers}
        getValue={(r) => r.total_buff_removal}
      />,
    );
    // Values are < 1000 so raw numbers: 200, 100, 50
    expect(container.textContent).toContain("200");
    expect(container.textContent).toContain("100");
    expect(container.textContent).toContain("50");
  });

  it("handles fewer than 3 players", () => {
    const { container } = render(
      <TopListCard
        title="Partial"
        rows={mockPlayers.slice(0, 2)}
        getValue={(r) => r.total_damage}
      />,
    );
    expect(container.textContent).toContain("🥇");
    expect(container.textContent).toContain("🥈");
    expect(container.textContent).not.toContain("🥉");
  });
});
