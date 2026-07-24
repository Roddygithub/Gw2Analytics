import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const routerRefresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerRefresh,
  }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  // Import the real module to preserve type contracts; only
  // mock the network-touching functions. ``formatApiError`` is
  // kept real so the revoke-failure error matches what a real
  // operator would see (no test-only rendering divergence).
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    revokeWebhook: vi.fn(),
  };
});

import { WebhookSubscriptionsGrid } from "@/components/WebhookSubscriptionsGrid";
import { revokeWebhook, type WebhookSubscriptionRow } from "@/lib/api";

const SAMPLE_ROW: WebhookSubscriptionRow = {
  id: "whsub_xyz789",
  url: "https://example.com/wh",
  description: "smoke tests",
  filter: { upload_status: "completed" },
  created_at: "2026-07-15T00:00:00+00:00",
};

describe("WebhookSubscriptionsGrid", () => {
  beforeEach(() => {
    vi.mocked(revokeWebhook).mockReset();
    routerRefresh.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the empty state when there are zero rows", () => {
    render(<WebhookSubscriptionsGrid rows={[]} />);
    expect(
      screen.getByTestId("webhook-subscriptions-empty"),
    ).toBeInTheDocument();
  });

  // AG Grid renders cells asynchronously after the initial
  // ``render`` completes --- ``getByTestId`` returns the first
  // match synchronously and would throw if the row hasn't been
  // mounted yet. ``findByTestId`` polls until the row appears.
  it("calls revokeWebhook + router.refresh on Revoke click", async () => {
    vi.mocked(revokeWebhook).mockResolvedValueOnce(undefined);
    render(<WebhookSubscriptionsGrid rows={[SAMPLE_ROW]} />);
    const revokeButton = await screen.findByTestId(`revoke-${SAMPLE_ROW.id}`);
    fireEvent.click(revokeButton);
    await waitFor(() => {
      expect(revokeWebhook).toHaveBeenCalledWith(SAMPLE_ROW.id);
    });
    await waitFor(() => {
      expect(routerRefresh).toHaveBeenCalled();
    });
  });

  it("renders a revoke-failure error card when revokeWebhook rejects", async () => {
    vi.mocked(revokeWebhook).mockRejectedValueOnce(
      new Error("404: webhook subscription whsub_xyz789 not found"),
    );
    render(<WebhookSubscriptionsGrid rows={[SAMPLE_ROW]} />);
    const revokeButton = await screen.findByTestId(`revoke-${SAMPLE_ROW.id}`);
    fireEvent.click(revokeButton);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/not found/i);
    });
  });
});
