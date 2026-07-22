/**
 * Unit tests for PlayerPositionHeatmap (v0.14.3 Phase H).
 *
 * Verifies loading, error, empty, and populated states. Mocks
 * ``fetchFightPositions`` so tests are hermetic (no network).
 */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

// Unmock the component under test.
vi.unmock("@/components/PlayerPositionHeatmap");

// Mock the position API.
const mockFetchFightPositions = vi.fn();
vi.mock("@/lib/api", () => ({
  fetchFightPositions: (...args: unknown[]) => mockFetchFightPositions(...args),
}));

import { PlayerPositionHeatmap } from "@/components/PlayerPositionHeatmap";

const MOCK_PLAYERS = [
  {
    account_name: "user.1234",
    name: "Test Guardian",
    profession: "Guardian",
    elite_spec: "ELITE(18)",
    stack_dist: 150.0,
    dist_to_com: 80.0,
    samples: [
      { x: 1000, y: 2000, z: 0 },
      { x: 1100, y: 2100, z: 0 },
      { x: 1200, y: 2200, z: 0 },
    ],
  },
  {
    account_name: "user.5678",
    name: "Test Necro",
    profession: "Necromancer",
    elite_spec: "ELITE(34)",
    stack_dist: 200.0,
    dist_to_com: 120.0,
    samples: [
      { x: 3000, y: 4000, z: 0 },
      { x: 3100, y: 4100, z: 0 },
    ],
  },
];

describe("PlayerPositionHeatmap", () => {
  it("renders loading state initially", () => {
    mockFetchFightPositions.mockReturnValueOnce(new Promise(() => {})); // never resolves

    render(<PlayerPositionHeatmap fightId="test-fight" />);
    expect(screen.getByText("Chargement des positions…")).toBeInTheDocument();
  });

  it("renders error state on fetch failure", async () => {
    mockFetchFightPositions.mockRejectedValueOnce(new Error("Network error"));

    render(<PlayerPositionHeatmap fightId="test-fight" />);
    await waitFor(() => {
      expect(screen.getByText(/Erreur/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Network error/)).toBeInTheDocument();
  });

  it("renders empty state when no players", async () => {
    mockFetchFightPositions.mockResolvedValueOnce({ players: [] });

    render(<PlayerPositionHeatmap fightId="test-fight" />);
    await waitFor(() => {
      expect(
        screen.getByText("Aucune donnée de position pour ce combat."),
      ).toBeInTheDocument();
    });
  });

  it("renders canvas, controls, and legend with player data", async () => {
    mockFetchFightPositions.mockResolvedValueOnce({
      players: MOCK_PLAYERS,
    });

    const { container } = render(
      <PlayerPositionHeatmap fightId="test-fight" />,
    );

    // Wait for data to load.
    await waitFor(() => {
      expect(screen.queryByText("Chargement des positions…")).toBeNull();
    });

    // Canvas should have role="img".
    const canvas = screen.getByRole("img", {
      name: /Carte des positions/,
    });
    expect(canvas).toBeInTheDocument();
    expect(canvas.tagName).toBe("CANVAS");

    // Play/pause button.
    expect(
      screen.getByRole("button", { name: "Lecture" }),
    ).toBeInTheDocument();

    // Time slider.
    const slider = screen.getByRole("slider", {
      name: "Curseur temporel",
    });
    expect(slider).toBeInTheDocument();
    expect(slider).toHaveAttribute("max", "1000"); // 2 samples × 500ms

    // Time display.
    expect(container).toHaveTextContent("0:00 / 0:01");

    // Legend should show profession abbreviations.
    expect(container).toHaveTextContent("Guar");
    expect(container).toHaveTextContent("Necr");
    expect(container).toHaveTextContent("COM");
  });

  it("toggles play/pause on button click", async () => {
    mockFetchFightPositions.mockResolvedValueOnce({
      players: [MOCK_PLAYERS[0]],
    });

    render(<PlayerPositionHeatmap fightId="test-fight" />);

    await waitFor(() => {
      expect(screen.queryByText("Chargement des positions…")).toBeNull();
    });

    const button = screen.getByRole("button", { name: "Lecture" });
    expect(button).toHaveTextContent("▶ Lecture");

    // Click to play — button should switch to pause.
    fireEvent.click(button);
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Pause" }),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Pause" })).toHaveTextContent(
      "⏸ Pause",
    );

    // Click again to pause — button should switch back to play.
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Lecture" }),
      ).toBeInTheDocument();
    });
  });

  it("updates time on slider change", async () => {
    mockFetchFightPositions.mockResolvedValueOnce({
      players: [MOCK_PLAYERS[0]],
    });

    const { container } = render(
      <PlayerPositionHeatmap fightId="test-fight" />,
    );

    await waitFor(() => {
      expect(screen.queryByText("Chargement des positions…")).toBeNull();
    });

    // Initial time: 0:00 / 0:01 (max 1000ms from 3 samples × 500ms)
    expect(container).toHaveTextContent("0:00 / 0:01");

    const slider = screen.getByRole("slider", {
      name: "Curseur temporel",
    });

    // Move slider to 1000ms → display should show 0:01 / 0:01.
    fireEvent.change(slider, { target: { value: "1000" } });
    await waitFor(() => {
      expect(container).toHaveTextContent("0:01 / 0:01");
    });
  });
});
